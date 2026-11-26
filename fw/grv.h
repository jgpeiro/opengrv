/* grv.h - register offsets of the OpenGRV control plane (all generated graphs).
 * The graph-specific header <top>_regs.h (written by grvgen) gives the base address, the
 * endpoint and parameter offsets and the conversion of parameter values.
 * SPDX-License-Identifier: MIT */
#ifndef GRV_H
#define GRV_H
#include <stdint.h>

#define GRV_ID_VALUE        0x47525631u     /* "GRV1" */

/* global registers */
#define GRV_ID              0x0000u
#define GRV_VERSION         0x0004u
#define GRV_GRAPH_HASH      0x0008u
#define GRV_CONFIG          0x000Cu         /* [7:0] sources, [15:8] sinks, [23:16] probes */
#define GRV_CLK_HZ          0x0010u
#define GRV_CTRL            0x0014u
#define GRV_STATUS          0x0018u         /* [0] RUN, [2] OVF, [3] ERR */
#define GRV_IRQ_EN          0x001Cu         /* [15:0] sink k, [31:16] source k */
#define GRV_IRQ_STATUS      0x0020u
#define GRV_TIMEOUT         0x0024u
#define GRV_OVF_MAP_LO      0x0028u         /* W1C */
#define GRV_OVF_MAP_HI      0x002Cu
#define GRV_ERR_MAP_LO      0x0030u
#define GRV_ERR_MAP_HI      0x0034u
#define GRV_SCRATCH         0x003Cu
#define GRV_PARAM(n)        (0x0100u + 4u * (n))

#define GRV_CTRL_RUN        (1u << 0)
#define GRV_CTRL_SOFT_RST   (1u << 1)
#define GRV_CTRL_COMMIT     (1u << 2)
#define GRV_CTRL_IRQ_EN     (1u << 8)
#define GRV_CTRL_OVF_IRQ_EN (1u << 9)
#define GRV_CTRL_ERR_IRQ_EN (1u << 10)
#define GRV_STATUS_OVF      (1u << 2)
#define GRV_STATUS_ERR      (1u << 3)
#define GRV_IRQ_SNK(k)      (1u << (k))
#define GRV_IRQ_SRC(k)      (1u << (16 + (k)))

/* source endpoint (0x1000 + 0x100 k) */
#define GRV_SRC_DATA        0x00u
#define GRV_SRC_DATA_HI     0x04u
#define GRV_SRC_STATUS      0x08u           /* [15:0] LEVEL [16] EMPTY [17] FULL [18] OVF [20] TIMEOUT [24] IRQ */
#define GRV_SRC_CTRL        0x0Cu
#define GRV_SRC_THRESH      0x10u
#define GRV_SRC_FRAME       0x14u
#define GRV_SRC_COUNT       0x18u
#define GRV_SRC_INFO        0x1Cu
#define GRV_SRC_FREE        0x20u
#define GRV_SRC_WINDOW      0x40u           /* 16 aliases of DATA, for unrolled copies */
#define GRV_SRC_EN          (1u << 0)
#define GRV_SRC_FLUSH       (1u << 1)
#define GRV_SRC_WAIT        (1u << 2)
#define GRV_SRC_PACK        (1u << 3)
#define GRV_SRC_IRQ_EN      (1u << 4)
#define GRV_SRC_MODE_LOOP   (1u << 8)

/* sink endpoint (0x2000 + 0x100 k), capture window 0x8000 + 0x2000 k */
#define GRV_SNK_DATA        0x00u
#define GRV_SNK_DATA_HI     0x04u
#define GRV_SNK_STATUS      0x08u           /* [15:0] LEVEL [16] EMPTY [17] FULL [18] OVF [19] UNF [20] TIMEOUT [21] DONE [22] ARMED [23] TRIGGERED */
#define GRV_SNK_CTRL        0x0Cu
#define GRV_SNK_THRESH      0x10u
#define GRV_SNK_CAPLEN      0x14u           /* [15:0] samples, [31:16] pre-trigger samples */
#define GRV_SNK_COUNT       0x18u
#define GRV_SNK_INFO        0x1Cu
#define GRV_SNK_TRIG_LEVEL  0x20u
#define GRV_SNK_DECIM       0x24u
#define GRV_SNK_TRIG_POS    0x28u
#define GRV_SNK_WINDOW      0x40u
#define GRV_SNK_EN          (1u << 0)
#define GRV_SNK_FLUSH       (1u << 1)
#define GRV_SNK_WAIT        (1u << 2)
#define GRV_SNK_PACK        (1u << 3)
#define GRV_SNK_IRQ_EN      (1u << 4)
#define GRV_SNK_DROP        (1u << 5)
#define GRV_SNK_MODE_CAPTURE (1u << 6)
#define GRV_SNK_ARM         (1u << 8)
#define GRV_SNK_TRIG_NOW    (0u << 9)
#define GRV_SNK_TRIG_RISE   (1u << 9)
#define GRV_SNK_TRIG_FALL   (2u << 9)
#define GRV_SNK_TRIG_LAST   (4u << 9)
#define GRV_SNK_TRIG_Q      (1u << 12)
#define GRV_SNK_DONE        (1u << 21)

/* probes (0x3000 + 8 k): word 0 = bits [31:0] (latches the high word), word 1 = bits [63:32] */
#define GRV_PROBE_LO        0x0u
#define GRV_PROBE_HI        0x4u

#define GRV_REG(base, off)  (*(volatile uint32_t *)((uintptr_t)(base) + (off)))

/* ---------------------------------------------------------------- revision 0.2 */
/* global registers */
#define GRV_CONFIG2         0x0038u         /* [7:0] peripheral endpoints, [15:8] DMA channels, [16] memory port */
#define GRV_IRQ2_EN         0x0040u         /* [15:0] peripheral endpoint k, [31:16] DMA channel k */
#define GRV_IRQ2_STATUS     0x0044u         /* pending conditions; cleared by servicing the endpoint or channel */
#define GRV_DMA_WIN_LO      0x0048u         /* lowest address the DMA may access */
#define GRV_DMA_WIN_HI      0x004Cu         /* highest address the DMA may access */
#define GRV_IRQ2_PE(k)      (1u << (k))
#define GRV_IRQ2_DMA(k)     (1u << (16 + (k)))
#define GRV_PE_OFFSET(k)    (0x6000u + 0x100u * (k))
#define GRV_DMA_OFFSET(k)   (0x7000u + 0x100u * (k))

/* peripheral endpoints (UART, SPI, GPIO): registers relative to the endpoint */
#define GRV_PE_CTRL         0x00u
#define GRV_PE_STATUS       0x04u           /* [15:0] LEVEL [16] EMPTY [17] FULL [18] OVF [19] UNF [20] ERR [21] BUSY [24] IRQ */
#define GRV_PE_THRESH       0x08u
#define GRV_PE_COUNT        0x0Cu
#define GRV_PE_ERRCNT       0x10u           /* [15:0] errors, [31:16] lost samples; a write clears both */
#define GRV_PE_INFO         0x14u
#define GRV_PE_TIMING       0x18u           /* 24.8 clocks: UART bit time, SPI master / GPIO sample period */
#define GRV_PE_FORMAT       0x1Cu
#define GRV_PE_SCLK         0x20u           /* SPI: [7:0] HALF (half period HALF + 1 clocks) */
#define GRV_PE_KIND(info)   (((info) >> 20) & 15u)   /* 1 UART, 2 SPI master, 3 SPI slave, 4 GPIO, 5 I2S */
#define GRV_PE_CMD          0x24u           /* SPI: frame bits with the I (or only) component; slave output: fill word */
#define GRV_PE_CMD_Q        0x28u           /* SPI: frame bits with the Q component */
#define GRV_PE_CS_TIMING    0x2Cu           /* SPI: [7:0] SETUP [15:8] HOLD [23:16] GAP, clocks */
#define GRV_PE_EN           (1u << 0)
#define GRV_PE_FLUSH        (1u << 1)
#define GRV_PE_IRQ_EN       (1u << 2)
#define GRV_PE_DROP         (1u << 3)
#define GRV_PE_REPEAT       (1u << 4)
#define GRV_PE_LEVEL(st)    ((st) & 0xFFFFu)
#define GRV_PE_EMPTY        (1u << 16)
#define GRV_PE_FULL         (1u << 17)
#define GRV_PE_OVF          (1u << 18)      /* W1C */
#define GRV_PE_UNF          (1u << 19)      /* W1C */
#define GRV_PE_ERR          (1u << 20)      /* W1C */
#define GRV_PE_BUSY         (1u << 21)
#define GRV_PE_IRQ          (1u << 24)
/* TIMING for a rate in Hz (sample rate, or baud rate for a UART) */
#define GRV_TIMING(clk_hz, hz) ((uint32_t)((((uint64_t)(clk_hz) << 8) + (uint64_t)(hz) / 2u) / (uint64_t)(hz)))
/* UART FORMAT */
#define GRV_UART_PAR_NONE   (0u << 0)
#define GRV_UART_PAR_EVEN   (1u << 0)
#define GRV_UART_PAR_ODD    (2u << 0)
#define GRV_UART_STOP2      (1u << 2)
#define GRV_UART_MSBF       (1u << 3)       /* most significant byte first */
#define GRV_UART_FLOW       (1u << 4)       /* rts_n / cts_n */
#define GRV_UART_INV        (1u << 5)
#define GRV_UART_TEXT       (1u << 6)       /* transmitter: hexadecimal digits and a separator */
#define GRV_UART_GAP(n)     (((uint32_t)(n) & 0xFFu) << 8)
#define GRV_UART_FRAME(n)   (((uint32_t)(n) & 0xFFFFu) << 16)   /* receiver: tlast every n samples */
/* SPI FORMAT */
#define GRV_SPI_FBITS(n)    ((uint32_t)(n) - 1u)
#define GRV_SPI_DPOS(p)     ((uint32_t)(p) << 8)
#define GRV_SPI_CPHA        (1u << 16)
#define GRV_SPI_CPOL        (1u << 17)
#define GRV_SPI_MODE(m)     (((uint32_t)(m) & 3u) << 16)
#define GRV_SPI_LSBF        (1u << 18)
#define GRV_SPI_OFS         (1u << 19)
#define GRV_SPI_SDLY(n)     (((uint32_t)(n) & 3u) << 20)
#define GRV_SPI_CS(setup, hold, gap) ((uint32_t)(setup) | ((uint32_t)(hold) << 8) | ((uint32_t)(gap) << 16))
/* I2S FORMAT; TIMING is the half period of bclk (master), K0 (GRV_PE_SCLK) the mclk divider */
#define GRV_I2S_SLOT(n)     ((uint32_t)(n) - 1u)              /* bits per channel slot, 8 .. 32 */
#define GRV_I2S_PHILIPS     (0u << 8)
#define GRV_I2S_LEFT_J      (1u << 8)
#define GRV_I2S_RIGHT_J     (2u << 8)
#define GRV_I2S_MONO_R      (1u << 10)      /* mono stream on the right channel */
#define GRV_I2S_DUP         (1u << 11)      /* output: mono on both channels */
#define GRV_I2S_WSINV       (1u << 13)
#define GRV_I2S_MCLKO       (1u << 16)
#define GRV_I2S_TIMING(clk_hz, fs, slot) ((uint32_t)((((uint64_t)(clk_hz) << 6) + (uint64_t)(fs) * (slot) / 2u) / ((uint64_t)(fs) * (slot))))
#define GRV_PE_MCLK         0x20u           /* I2S: [7:0] mclk half period - 1, clocks */
/* GPIO FORMAT */
#define GRV_GPIO_PERIODIC   0u              /* inputs */
#define GRV_GPIO_STROBE     1u
#define GRV_GPIO_CHANGE     2u
#define GRV_GPIO_PARALLEL   0u              /* outputs */
#define GRV_GPIO_PWM        1u
#define GRV_GPIO_SDM        2u
#define GRV_GPIO_EDGE_FALL  (1u << 2)
#define GRV_GPIO_OFS        (1u << 3)
#define GRV_GPIO_CLKO       (1u << 4)
#define GRV_GPIO_SDM_ORD1   (1u << 5)
#define GRV_GPIO_PHASE(n)   (((uint32_t)(n) & 0xFFu) << 8)
#define GRV_GPIO_FILTER(n)  (((uint32_t)(n) & 0xFFu) << 16)    /* inputs, CHANGE */
#define GRV_GPIO_SDM_DIV(n) (((uint32_t)(n) & 0xFFu) << 16)    /* outputs, SDM */

#endif
