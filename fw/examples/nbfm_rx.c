/* nbfm_rx.c - PicoRV32 firmware for the NBFM receiver example (examples/nbfm_rx).
 * Build the header first:  python3 grvgen/grvgen.py examples/nbfm_rx/nbfm_rx.grc -o build/nbfm
 * then compile with -Ifw -Ibuild/nbfm. audio_put() is the application's audio output (e.g. an I2S FIFO).
 * SPDX-License-Identifier: MIT */
#include <stdint.h>
#include "grv.h"
#include "nbfm_rx_top_regs.h"

#define R(off) GRV_REG(NBFM_RX_BASE, (off))

extern void audio_put(int16_t sample);
extern void panic(const char *msg);

/* start the receiver tuned to tune_hz (-400 kHz .. 400 kHz from the ADC centre) */
void radio_start(int32_t tune_hz)
{
    if (R(GRV_ID) != GRV_ID_VALUE || R(GRV_GRAPH_HASH) != NBFM_RX_HASH)
        panic("bitstream does not match the firmware");
    R(NBFM_RX_P_TUNE)   = nbfm_rx_top_tune_hw(tune_hz);      /* integer only: no soft float */
    R(NBFM_RX_P_VOLUME) = NBFM_RX_P_VOLUME_INIT;            /* 1.0 in s18.15 */
    R(NBFM_RX_SNK_AUDIO + GRV_SNK_THRESH) = 256;
    R(NBFM_RX_SNK_AUDIO + GRV_SNK_CTRL)   = GRV_SNK_EN | GRV_SNK_IRQ_EN;          /* STREAM */
    R(GRV_IRQ_EN) = NBFM_RX_IRQ_SNK_AUDIO;
    R(GRV_CTRL)   = GRV_CTRL_COMMIT | GRV_CTRL_RUN | GRV_CTRL_IRQ_EN;
}

/* retune while running: the parameter word is live, it takes effect on the write */
void radio_tune(int32_t tune_hz)
{
    R(NBFM_RX_P_TUNE) = nbfm_rx_top_tune_hw(tune_hz);
}

/* interrupt handler: at least 256 audio samples (s16.12) are waiting, every 5.3 ms at 48 kS/s */
void radio_irq(void)
{
    uint32_t n = R(NBFM_RX_SNK_AUDIO + GRV_SNK_STATUS) & 0xFFFFu;
    while (n--) {
        int32_t s = (int32_t)R(NBFM_RX_SNK_AUDIO + GRV_SNK_DATA);  /* sign-extended s16.12 */
        int32_t v = s << (15 - NBFM_RX_SNK_AUDIO_FRAC);              /* to Q15, saturate */
        audio_put((int16_t)(v > 32767 ? 32767 : v < -32768 ? -32768 : v));
    }
}

/* one spectrum snapshot: 1024 complex samples of the ADC stream into buf (I in bits 15:0, Q in 31:16) */
void radio_snapshot(uint32_t *buf)
{
    R(NBFM_RX_SNK_SPECTRUM + GRV_SNK_CAPLEN) = NBFM_RX_CAP_SPECTRUM_LEN;
    R(NBFM_RX_SNK_SPECTRUM + GRV_SNK_CTRL) = GRV_SNK_EN | GRV_SNK_MODE_CAPTURE | GRV_SNK_ARM | GRV_SNK_TRIG_NOW;
    while (!(R(NBFM_RX_SNK_SPECTRUM + GRV_SNK_STATUS) & GRV_SNK_DONE))
        ;
    for (uint32_t i = 0; i < NBFM_RX_CAP_SPECTRUM_LEN; i++)
        buf[i] = R(NBFM_RX_CAP_SPECTRUM + 4 * i);
}

/* channel power from the probe (s16.11): mean |x|^2 of the channel */
int32_t radio_rssi_q11(void)
{
    return (int32_t)R(NBFM_RX_PROBE_RSSI + GRV_PROBE_LO);
}
