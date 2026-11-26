/* grv_dma.h - firmware helpers for the DMA channels of OpenGRV (design document, section 9.7),
 * independent of the graph. A channel is addressed by its base address: the base of the graph plus
 * the channel offset of the generated header (e.g. NBFM_RX_BASE + NBFM_RX_DMA_SPECTRUM).
 *
 *   grv_dma_single(ch, buf, n, flags)    one block of n samples, DONE at the end
 *   grv_dma_ring(ch, buf, n, wm, flags)  circular buffer of n samples, WM interrupt every wm samples
 *   grv_dma_desc_*                       chains of descriptors (one buffer each, OWN handshake)
 *
 * PicoRV32 has no data cache: memory written by the DMA is visible to the CPU once the channel says
 * so (DONE, HW_IDX, OWN cleared). The compiler barrier grv_dma_sync() keeps the accesses in order.
 * SPDX-License-Identifier: MIT */
#ifndef GRV_DMA_H
#define GRV_DMA_H
#include <stdint.h>
#include "grv.h"

/* registers, relative to the channel */
#define GRV_DMA_CTRL        0x00u
#define GRV_DMA_STATUS      0x04u           /* W1C: DONE, WM, ERR, OVF */
#define GRV_DMA_ADDR        0x08u
#define GRV_DMA_LEN         0x0Cu           /* [23:0] samples */
#define GRV_DMA_HW_IDX      0x10u
#define GRV_DMA_SW_IDX      0x14u
#define GRV_DMA_WM          0x18u
#define GRV_DMA_DESC        0x1Cu
#define GRV_DMA_TOTAL       0x20u
#define GRV_DMA_FRAME       0x24u
#define GRV_DMA_ERR_ADDR    0x28u
#define GRV_DMA_INFO        0x2Cu
#define GRV_DMA_KICK        0x30u

/* CTRL */
#define GRV_DMA_EN          (1u << 0)
#define GRV_DMA_ABORT       (1u << 1)
#define GRV_DMA_SINGLE      (0u << 2)
#define GRV_DMA_RING        (1u << 2)
#define GRV_DMA_DESC_MODE   (2u << 2)
#define GRV_DMA_I_DONE      (1u << 4)       /* interrupt at DONE */
#define GRV_DMA_I_WM        (1u << 5)       /* interrupt at a watermark */
#define GRV_DMA_I_ERR       (1u << 6)       /* interrupt at an error */
#define GRV_DMA_FLOW        (1u << 7)       /* ring: wait for SW_IDX (queue between DMA and CPU) */
#define GRV_DMA_DROP        (1u << 8)       /* S2MM: drop samples it cannot write (real-time graphs) */
#define GRV_DMA_MSBA        (1u << 9)       /* components left-aligned in their containers */
#define GRV_DMA_EOFL        (1u << 10)      /* tlast ends a block (S2MM) / marks its last sample (MM2S) */
#define GRV_DMA_BURST(n)    ((((uint32_t)(n) - 1u) & 15u) << 12)
#define GRV_DMA_GAP(n)      (((uint32_t)(n) & 0xFFu) << 16)
#define GRV_DMA_PRIO        (1u << 24)
/* STATUS */
#define GRV_DMA_BUSY        (1u << 0)
#define GRV_DMA_DONE        (1u << 1)
#define GRV_DMA_WMF         (1u << 2)
#define GRV_DMA_ERR         (1u << 3)
#define GRV_DMA_STALLED     (1u << 4)
#define GRV_DMA_OVF         (1u << 5)
#define GRV_DMA_ECODE(st)   (((st) >> 6) & 3u)    /* 1 timeout, 2 outside the window, 3 bad descriptor / alignment */
#define GRV_DMA_IRQ         (1u << 8)
#define GRV_DMA_LEVEL(st)   ((st) >> 16)
#define GRV_DMA_W1C         (GRV_DMA_DONE | GRV_DMA_WMF | GRV_DMA_ERR | GRV_DMA_OVF)
/* INFO */
#define GRV_DMA_INFO_CB(i)  (1u << (((i) >> 14) & 3u))  /* bytes per component */
#define GRV_DMA_INFO_S2MM   (1u << 16)

/* descriptor (16-byte aligned) */
typedef struct grv_dma_desc {
    uint32_t next;                  /* next descriptor, 0 ends the chain */
    uint32_t addr;                  /* buffer (4-byte aligned) */
    uint32_t ctrl;                  /* [23:0] LEN, [24] IRQ, [25] EOF, [31] OWN */
    uint32_t stat;                  /* [23:0] count, [24] EOF, [25] OVF, [31] DONE (written by the DMA) */
} __attribute__((aligned(16))) grv_dma_desc_t;
#define GRV_DESC_LEN(n)     ((uint32_t)(n) & 0x00FFFFFFu)
#define GRV_DESC_IRQ        (1u << 24)
#define GRV_DESC_EOF        (1u << 25)
#define GRV_DESC_OWN        (1u << 31)
#define GRV_STAT_COUNT(s)   ((s) & 0x00FFFFFFu)
#define GRV_STAT_EOF        (1u << 24)
#define GRV_STAT_OVF        (1u << 25)
#define GRV_STAT_DONE       (1u << 31)

#define grv_dma_sync()      __asm__ volatile ("" ::: "memory")

static inline uint32_t grv_dma_status(uintptr_t ch) { return GRV_REG(ch, GRV_DMA_STATUS); }
static inline int grv_dma_done(uintptr_t ch) { return (GRV_REG(ch, GRV_DMA_STATUS) & GRV_DMA_DONE) != 0; }

/* stop the channel after the access in progress and flush its FIFO */
static inline void grv_dma_stop(uintptr_t ch)
{
    GRV_REG(ch, GRV_DMA_CTRL) = GRV_DMA_ABORT;
    while (GRV_REG(ch, GRV_DMA_STATUS) & GRV_DMA_BUSY)
        ;
}

/* one block of n samples from or to buf; returns at once, DONE (and the interrupt with GRV_DMA_I_DONE)
 * tells the end. flags: GRV_DMA_DROP, GRV_DMA_EOFL, GRV_DMA_MSBA, GRV_DMA_I_*, GRV_DMA_BURST(), ... */
static inline void grv_dma_single(uintptr_t ch, void *buf, uint32_t n, uint32_t flags)
{
    grv_dma_sync();
    GRV_REG(ch, GRV_DMA_STATUS) = GRV_DMA_W1C;
    GRV_REG(ch, GRV_DMA_ADDR) = (uint32_t)(uintptr_t)buf;
    GRV_REG(ch, GRV_DMA_LEN) = n;
    GRV_REG(ch, GRV_DMA_CTRL) = (flags & ~(GRV_DMA_ABORT | (3u << 2))) | GRV_DMA_SINGLE | GRV_DMA_EN;
}

/* circular buffer of n samples; wm = 0 or n / 2 (ping-pong) ...; with GRV_DMA_FLOW the CPU moves
 * SW_IDX (grv_dma_ring_release) and the DMA never overtakes it */
static inline void grv_dma_ring(uintptr_t ch, void *buf, uint32_t n, uint32_t wm, uint32_t flags)
{
    grv_dma_sync();
    GRV_REG(ch, GRV_DMA_STATUS) = GRV_DMA_W1C;
    GRV_REG(ch, GRV_DMA_ADDR) = (uint32_t)(uintptr_t)buf;
    GRV_REG(ch, GRV_DMA_LEN) = n;
    GRV_REG(ch, GRV_DMA_SW_IDX) = 0;
    GRV_REG(ch, GRV_DMA_WM) = wm;
    GRV_REG(ch, GRV_DMA_CTRL) = (flags & ~(GRV_DMA_ABORT | (3u << 2))) | GRV_DMA_RING | GRV_DMA_EN;
}

/* index of the next sample the channel transfers */
static inline uint32_t grv_dma_ring_hw(uintptr_t ch) { return GRV_REG(ch, GRV_DMA_HW_IDX); }

/* S2MM ring with FLOW: samples written by the DMA and not yet released by the CPU, from index sw */
static inline uint32_t grv_dma_ring_avail(uintptr_t ch, uint32_t sw, uint32_t n)
{
    uint32_t hw = GRV_REG(ch, GRV_DMA_HW_IDX);
    grv_dma_sync();
    return hw >= sw ? hw - sw : hw + n - sw;
}

/* MM2S ring with FLOW: free samples the CPU may write from index sw (one slot stays empty) */
static inline uint32_t grv_dma_ring_space(uintptr_t ch, uint32_t sw, uint32_t n)
{
    uint32_t hw = GRV_REG(ch, GRV_DMA_HW_IDX);
    return (hw > sw ? hw - sw : hw + n - sw) - 1u;
}

/* hand samples back (S2MM: consumed) or over (MM2S: written) up to index sw */
static inline void grv_dma_ring_release(uintptr_t ch, uint32_t sw)
{
    grv_dma_sync();
    GRV_REG(ch, GRV_DMA_SW_IDX) = sw;
}

/* descriptor d for a buffer of n samples; owned by the DMA (OWN) unless own = 0 */
static inline void grv_dma_desc_set(grv_dma_desc_t *d, grv_dma_desc_t *next, void *buf, uint32_t n, uint32_t dflags, int own)
{
    d->next = (uint32_t)(uintptr_t)next;
    d->addr = (uint32_t)(uintptr_t)buf;
    d->stat = 0;
    grv_dma_sync();
    d->ctrl = GRV_DESC_LEN(n) | (dflags & (GRV_DESC_IRQ | GRV_DESC_EOF)) | (own ? GRV_DESC_OWN : 0u);
}

/* a circular chain of k descriptors over k buffers of n samples each, laid out one after the other
 * in bufs (bytes_per_sample from the header, e.g. NBFM_RX_DMA_SPECTRUM_EB), all owned by the DMA */
static inline void grv_dma_desc_ring(grv_dma_desc_t *d, uint32_t k, void *bufs, uint32_t n, uint32_t bytes_per_sample,
                                     uint32_t dflags)
{
    uint8_t *b = (uint8_t *)bufs;
    for (uint32_t i = 0; i < k; i++)
        grv_dma_desc_set(&d[i], &d[(i + 1) % k], b + (uintptr_t)i * n * bytes_per_sample, n, dflags, 1);
}

/* start a channel on the chain at first */
static inline void grv_dma_desc_start(uintptr_t ch, grv_dma_desc_t *first, uint32_t flags)
{
    grv_dma_sync();
    GRV_REG(ch, GRV_DMA_STATUS) = GRV_DMA_W1C;
    GRV_REG(ch, GRV_DMA_DESC) = (uint32_t)(uintptr_t)first;
    GRV_REG(ch, GRV_DMA_CTRL) = (flags & ~(GRV_DMA_ABORT | (3u << 2))) | GRV_DMA_DESC_MODE | GRV_DMA_EN;
}

/* the buffer of d is complete (the DMA cleared OWN); its status word holds the count */
static inline int grv_dma_desc_ready(const grv_dma_desc_t *d)
{
    uint32_t c = ((volatile const grv_dma_desc_t *)d)->ctrl;
    grv_dma_sync();
    return !(c & GRV_DESC_OWN);
}

/* give d back to the DMA and wake the channel if it waits for it */
static inline void grv_dma_desc_give(uintptr_t ch, grv_dma_desc_t *d)
{
    d->stat = 0;
    grv_dma_sync();
    ((volatile grv_dma_desc_t *)d)->ctrl |= GRV_DESC_OWN;
    GRV_REG(ch, GRV_DMA_KICK) = 0;
}

#endif /* GRV_DMA_H */
