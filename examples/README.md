# Examples

Every example is a GNU Radio Companion flowgraph that grvgen turns into a top level. `python3 tools/run_examples.py` generates and simulates all of them against their bit-exact models (`-k NAME` for one, `-j N` in parallel). The flowgraphs come from `tools/mkexamples.py`; the pictures from `tools/grc2svg.py`.

| Example | What it is | Interfaces |
|---|---|---|
| [nbfm_rx](nbfm_rx/nbfm_rx.grc) | The NBFM receiver of the design document | pad, AXI4-Lite, probe |
| [nbfm_rx_pe](nbfm_rx_pe/nbfm_rx_pe.grc) | The same receiver with a sigma-delta pin, DMA and a UART log | pad, GPIO, DMA, UART |
| [am_rx_i2s](am_rx_i2s/README.md) | AM receiver with I2S audio | I2S, pad, probe |
| [wbfm_rx_i2s](wbfm_rx_i2s/README.md) | Wideband FM receiver with I2S audio | I2S, pad |
| [qpsk_tx_spi](qpsk_tx_spi/README.md) | QPSK transmitter to a dual SPI DAC | SPI master |
| [bpsk_rx_uart](bpsk_rx_uart/README.md) | BPSK receiver with a UART data output | UART, pad |
| [spectrum_dma](spectrum_dma/README.md) | Spectrum analyser with DMA | DMA, pad |
| [audio_eq_i2s](audio_eq_i2s/README.md) | Stereo three-band equaliser between I2S codecs | I2S |
| [dtmf_gen](dtmf_gen/README.md) | DTMF generator on a sigma-delta pin and I2S | GPIO, I2S |
| [ddc_cic_dma](ddc_cic_dma/README.md) | Digital down-converter with CIC and DMA | DMA, pad, probe |
| [level_meter_spi](level_meter_spi/README.md) | Level meter: SPI ADC, LED and UART log | GPIO, SPI master, UART, probe |
| [siggen_spi_dac](siggen_spi_dac/README.md) | Two-channel signal generator | GPIO, SPI master |
