/* nbfm_rx_pe.c - PicoRV32 firmware for the NBFM receiver with peripheral endpoints and DMA
 * (examples/nbfm_rx_pe, design document section 9.10). The audio leaves on a sigma-delta pin and the
 * channel power on the UART, both without any code; the CPU only asks for spectrum snapshots, which
 * the DMA writes into RAM, and runs the FFT on them.
 * Build the header first:  python3 grvgen/grvgen.py examples/nbfm_rx_pe/nbfm_rx_pe.grc -o build/nbfm_pe
 * then compile with -Ifw -Ibuild/nbfm_pe.
 * SPDX-License-Identifier: MIT */
#include <stdint.h>
#include "grv.h"
#include "grv_dma.h"
#include "nbfm_rx_top_regs.h"

#define R(off) GRV_REG(NBFM_RX_BASE, (off))
#define SPEC   (NBFM_RX_BASE + NBFM_RX_DMA_SPECTRUM)

extern void panic(const char *msg);

static uint32_t snap[1024];            /* cs16: I in bits 15:0, Q in bits 31:16 */
static volatile int snap_ready;

void radio_start(int32_t tune_hz)
{
    if (R(GRV_ID) != GRV_ID_VALUE || R(GRV_GRAPH_HASH) != NBFM_RX_HASH)
        panic("bitstream does not match the firmware");
    /* keep the DMA inside the sample RAM (the firmware is below it) */
    R(GRV_DMA_WIN_LO) = (uint32_t)(uintptr_t)&snap[0];
    R(GRV_DMA_WIN_HI) = (uint32_t)(uintptr_t)&snap[1023] + 3u;
    R(NBFM_RX_P_TUNE) = nbfm_rx_top_tune_hw(tune_hz);
    R(GRV_IRQ2_EN)    = NBFM_RX_IRQ_DMA_SPECTRUM;
    R(GRV_CTRL)       = GRV_CTRL_COMMIT | GRV_CTRL_RUN | GRV_CTRL_IRQ_EN;
}

void spectrum_request(void)            /* returns at once */
{
    snap_ready = 0;
    grv_dma_single(SPEC, snap, 1024, GRV_DMA_DROP | GRV_DMA_I_DONE);
}

void grv_irq_handler(void)
{
    uint32_t p = R(GRV_IRQ2_STATUS);
    if (p & NBFM_RX_IRQ_DMA_SPECTRUM) {
        uint32_t st = GRV_REG(SPEC, GRV_DMA_STATUS);
        GRV_REG(SPEC, GRV_DMA_STATUS) = GRV_DMA_W1C;         /* clears DONE (and ERR) */
        if (st & GRV_DMA_ERR)
            panic("DMA error");
        snap_ready = 1;        /* the main loop runs the FFT on snap[] */
    }
}

/* audio health: underflows of the sigma-delta output since the last call */
uint32_t audio_underflows(void)
{
    uint32_t e = GRV_REG(NBFM_RX_BASE + NBFM_RX_PE_AUDIO, GRV_PE_ERRCNT) >> 16;
    GRV_REG(NBFM_RX_BASE + NBFM_RX_PE_AUDIO, GRV_PE_ERRCNT) = 0;
    return e;
}

int spectrum_ready(void) { return snap_ready; }
const uint32_t *spectrum_buffer(void) { return snap; }
