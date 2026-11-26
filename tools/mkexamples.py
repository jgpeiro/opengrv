#!/usr/bin/env python3
"""Writes the example flowgraphs examples/<name>/<name>.grc (GNU Radio Companion, file format 1) with a
layered layout, and their run settings (examples/examples.json) used by tools/run_examples.py.
    python3 tools/mkexamples.py [NAME ...]"""
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'tb', 'graph'))
sys.path.insert(0, HERE)
from mkgrc import G  # noqa: E402

EX = {}


def example(name, title, n, desc, params=None, args=None):
    def deco(f):
        EX[name] = dict(f=f, title=title, n=n, desc=desc, params=params or {}, args=args or [])
        return f
    return deco


def layout(g):
    """GRC coordinates: variables in a row at the top, blocks in columns by their depth in the graph, each
    column ordered by the rows of its inputs; widths and heights as tools/grc2svg.py draws the blocks"""
    from grc2svg import box
    names = [b['name'] for b in g.blocks]
    blk = {b['name']: b for b in g.blocks}
    isvar = {n: blk[n]['id'].startswith('variable') for n in names}
    preds = {n: [] for n in names}
    for a, _, b, pb in g.conns:
        preds[b].append((a, int(pb)))
    depth = {}

    def d(n, seen=()):
        if n in depth:
            return depth[n]
        if n in seen:
            return 0
        depth[n] = 0 if not preds[n] else 1 + max(d(p, seen + (n,)) for p, _ in preds[n])
        return depth[n]
    size = {n: box(blk[n], g.conns) for n in names}
    cols = {}
    for n in names:
        if not isvar[n]:
            cols.setdefault(d(n), []).append(n)
    row = {}
    for k in sorted(cols):
        def key(n):
            ps = [row[p] + 0.01 * pb for p, pb in preds[n] if p in row]
            return (sum(ps) / len(ps) if ps else 0, names.index(n))
        cols[k].sort(key=key)
        used = set()
        for n in cols[k]:
            r = max(0, round(key(n)[0]))
            while r in used:
                r += 1
            used.add(r)
            row[n] = r
    pitch = max(size[n]['h'] for n in names if not isvar[n]) + 30
    x = 16
    for k in sorted(cols):
        for n in cols[k]:
            blk[n]['states']['coordinate'] = [x, 150 + pitch * row[n] + (pitch - 30 - size[n]['h']) // 2]
        x += max(size[n]['w'] for n in cols[k]) + 84
    vx = 200
    for n in names:
        if isvar[n]:
            blk[n]['states']['coordinate'] = [vx, 12]
            vx += size[n]['w'] + 24


def var(g, name, value, lo=None, hi=None, step=None, label=None):
    if lo is None:
        return g.var(name, value)
    return g.var(name, value, kind='variable_qtgui_range', start=lo, stop=hi, step=step, label=label or name,
                 rangeType='float', widget='counter_slider', orient='QtCore.Qt.Horizontal', min_len=200, gui_hint='')


# ------------------------------------------------------------------ 1. AM receiver, audio on I2S
@example('am_rx_i2s', 'AM receiver with I2S audio', 20000,
         'An AM receiver for a complex ADC at 1.92 MS/s: channel selection with a frequency-translating FIR, '
         'a second filter to 48 kS/s, envelope detection, DC removal and AGC; the audio goes to an I2S DAC '
         '(both channels) and the CPU reads the signal level from a probe.', params={'tune': 50e3})
def ex_am(g):
    g.var('samp_rate', 1.92e6)
    var(g, 'tune', 0, -400e3, 400e3, 1e3, 'Tuning (Hz)')
    var(g, 'volume', 1, 0, 2, 0.05, 'Volume')
    adc = g.b('pad_source', 'adc_iq', type='complex', label='adc_iq', num_streams=1, vlen=1, optional=False,
              comment='@grv rate=samp_rate')
    xl = g.b('freq_xlating_fir_filter_xxx', 'xlate', type='ccf', decim=8, center_freq='tune', samp_rate='samp_rate',
             taps='firdes.low_pass(1, samp_rate, 20e3, 40e3)')
    ch = g.b('low_pass_filter', 'chan', type='fir_filter_ccf', decim=5, interp=1, gain=1, samp_rate='samp_rate / 8',
             cutoff_freq=5e3, width=3e3, win='window.WIN_HAMMING', beta=6.76)
    env = g.b('blocks_complex_to_mag', 'env', vlen=1)
    dc = g.b('dc_blocker_xx', 'dcb', type='ff', length=64, long_form=False)
    agc = g.b('analog_agc_xx', 'agc', type='float', rate=1e-3, reference=0.3, gain=1, max_gain=200)
    vol = g.b('blocks_multiply_const_vxx', 'vol', type='float', const='volume', vlen=1)
    dac = g.b('grv_i2s_sink', 'audio', type='float', role='master', samp_rate=48e3, slot_bits=32, data_bits=16,
              format='i2s', duplicate='True', drop='True', repeat='True')
    g.chain(adc, xl, ch, env, dc, agc, vol, dac)
    m2 = g.b('blocks_complex_to_mag_squared', 'pwr', vlen=1)
    av = g.b('single_pole_iir_filter_xx', 'avg', type='float', alpha=0.01, vlen=1)
    pr = g.b('blocks_probe_signal_x', 'level', type='float')
    g.chain(ch, m2, av, pr)


# ------------------------------------------------------------------ 2. wideband FM receiver
@example('wbfm_rx_i2s', 'Wideband FM receiver with I2S audio', 24000,
         'A broadcast FM receiver built from primitive blocks: channel filter to 480 kS/s, quadrature '
         'demodulator, 75 us de-emphasis, audio filter and decimation to 48 kS/s, volume and an I2S DAC.')
def ex_wbfm(g):
    g.var('samp_rate', 1.92e6)
    var(g, 'volume', 0.8, 0, 2, 0.05, 'Volume')
    adc = g.b('pad_source', 'adc_iq', type='complex', label='adc_iq', num_streams=1, vlen=1, optional=False,
              comment='@grv rate=samp_rate')
    ch = g.b('low_pass_filter', 'chan', type='fir_filter_ccf', decim=4, interp=1, gain=1, samp_rate='samp_rate',
             cutoff_freq=110e3, width=60e3, win='window.WIN_HAMMING', beta=6.76)
    qd = g.b('analog_quadrature_demod_cf', 'fmdemod', gain='(samp_rate / 4) / (2 * math.pi * 75e3)',
             comment='@grv range=2')
    de = g.b('single_pole_iir_filter_xx', 'deemph', type='float', alpha='1 - math.exp(-1 / (480e3 * 75e-6))', vlen=1)
    au = g.b('low_pass_filter', 'audio_lpf', type='fir_filter_fff', decim=10, interp=1, gain=1, samp_rate=480e3,
             cutoff_freq=15e3, width=5e3, win='window.WIN_HAMMING', beta=6.76)
    vol = g.b('blocks_multiply_const_vxx', 'vol', type='float', const='volume', vlen=1)
    dac = g.b('grv_i2s_sink', 'audio', type='float', role='master', samp_rate=48e3, slot_bits=32, data_bits=24,
              format='i2s', duplicate='True', drop='True', repeat='True')
    g.chain(adc, ch, qd, de, au, vol, dac)


# ------------------------------------------------------------------ 3. QPSK transmitter
@example('qpsk_tx_spi', 'QPSK transmitter to a dual SPI DAC', 2000,
         'A QPSK modulator: a PRBS feeds pairs of bits to the constellation mapper, a root-raised-cosine '
         'interpolator shapes the symbols (4 samples per symbol), and a dual 12-bit SPI DAC (I on channel A, '
         'Q on channel B) plays them at 250 kS/s.')
def ex_qpsk_tx(g):
    var(g, 'gain', 0.7, 0, 1, 0.01, 'Output level')
    prbs = g.b('digital_glfsr_source_x', 'prbs', type='byte', degree=15, mask=0x6000, seed=1, repeat=True)
    pk = g.b('blocks_pack_k_bits_bb', 'pack2', k=2)
    cs = g.b('digital_chunks_to_symbols_xx', 'mapper', in_type='byte', out_type='complex', dimension=1, num_ports=1,
             symbol_table='[(-1-1j)/1.4142, (1-1j)/1.4142, (-1+1j)/1.4142, (1+1j)/1.4142]')
    rrc = g.b('interp_fir_filter_xxx', 'rrc', type='ccf', interp=4, samp_delay=0,
              taps='firdes.root_raised_cosine(4, 4, 1, 0.35, 41)')
    k = g.b('blocks_multiply_const_vxx', 'level', type='complex', const='gain', vlen=1)
    dac = g.b('grv_spi_sink', 'dac', type='complex', role='master', samp_rate=250e3, sclk=13.5e6, mode=0,
              frame_bits=16, data_pos=0, data_bits=12, offset_binary='True', cmd=0x3000, cmd_q=0xB000,
              repeat='True')
    g.chain(prbs, pk, cs, rrc, k, dac)


# ------------------------------------------------------------------ 4. BPSK receiver to UART
@example('bpsk_rx_uart', 'BPSK receiver with a UART data output', 16000,
         'A BPSK receiver for a complex ADC at 1 MS/s and 125 kbit/s: root-raised-cosine matched filter, '
         'AGC, Costas loop for the carrier, one sample per symbol, slicer, and bytes out on a UART at '
         '921600 Bd. The symbol clock is assumed known (a fixed phase), as in a lab link.')
def ex_bpsk_rx(g):
    g.var('samp_rate', 1e6)
    g.var('sps', 8)
    adc = g.b('pad_source', 'adc_iq', type='complex', label='adc_iq', num_streams=1, vlen=1, optional=False,
              comment='@grv rate=samp_rate')
    mf = g.b('root_raised_cosine_filter', 'mf', type='fir_filter_ccf', decim=1, interp=1, gain=1,
             samp_rate='samp_rate', sym_rate='samp_rate / sps', alpha=0.35, ntaps=65)
    agc = g.b('analog_agc_xx', 'agc', type='complex', rate=1e-3, reference=0.7, gain=1, max_gain=100)
    co = g.b('digital_costas_loop_cc', 'costas', w=0.02, order=2, use_snr=False)
    k = g.b('blocks_keep_one_in_n', 'strobe', type='complex', n='sps', vlen=1)
    re = g.b('blocks_complex_to_real', 're', vlen=1)
    sl = g.b('digital_binary_slicer_fb', 'slicer')
    pk = g.b('blocks_pack_k_bits_bb', 'bytes', k=8)
    u = g.b('grv_uart_sink', 'data', type='byte', baud=921600, parity='none', stop_bits=1)
    g.chain(adc, mf, agc, co, k, re, sl, pk, u)


# ------------------------------------------------------------------ 5. spectrum snapshots by DMA
@example('spectrum_dma', 'Spectrum analyser with DMA', 6144,
         'A 256-point spectrum analyser: one frame in eight of the ADC stream goes through a windowed '
         'FFT and a magnitude-squared stage, and a DMA channel writes the power spectra into a ring of '
         'buffers in RAM, one frame per buffer, without the CPU.')
def ex_spectrum(g):
    g.var('samp_rate', 1.92e6)
    g.var('nfft', 256)
    adc = g.b('pad_source', 'adc_iq', type='complex', label='adc_iq', num_streams=1, vlen=1, optional=False,
              comment='@grv rate=samp_rate')
    kf = g.b('blocks_keep_m_in_n', 'frames', type='complex', m='nfft', n='8 * nfft', offset=0, vlen=1)
    s2v = g.b('blocks_stream_to_vector', 's2v', type='complex', num_items='nfft', vlen=1)
    ff = g.b('fft_vxx', 'fft', type='complex', fft_size='nfft', forward=True, window='window.blackmanharris(nfft)',
             shift=True, nthreads=1)
    v2s = g.b('blocks_vector_to_stream', 'v2s', type='complex', num_items='nfft', vlen=1)
    m2 = g.b('blocks_complex_to_mag_squared', 'power', vlen=1)
    dma = g.b('grv_dma_sink', 'spectra', type='float', mode='desc', burst=4, eof_last='False', drop='True')
    g.chain(adc, kf, s2v, ff, v2s, m2, dma)


# ------------------------------------------------------------------ 6. three-band audio equaliser
@example('audio_eq_i2s', 'Stereo three-band equaliser between I2S codecs', 4000,
         'A stereo three-band equaliser: the codec ADC delivers left and right as one complex stream, '
         'two one-pole low-pass filters split it into bass, mid and treble, each band has a runtime gain, '
         'and the sum goes to the codec DAC. Both I2S ports are masters at 48 kHz.',
         params={'bass': 1.5, 'treble': 0.5})
def ex_eq(g):
    var(g, 'bass', 1, 0, 2, 0.05, 'Bass')
    var(g, 'mid', 1, 0, 2, 0.05, 'Mid')
    var(g, 'treble', 1, 0, 2, 0.05, 'Treble')
    adc = g.b('grv_i2s_source', 'codec_in', type='complex', role='master', samp_rate=48e3, slot_bits=32,
              data_bits=24, format='i2s')
    lp = g.b('single_pole_iir_filter_xx', 'lp300', type='complex', alpha=0.04, vlen=1)
    lp2 = g.b('single_pole_iir_filter_xx', 'lp4k', type='complex', alpha=0.41, vlen=1)
    hp = g.b('blocks_sub_xx', 'treble_band', type='complex', num_inputs=2, vlen=1)
    md = g.b('blocks_sub_xx', 'mid_band', type='complex', num_inputs=2, vlen=1)
    gb = g.b('blocks_multiply_const_vxx', 'g_bass', type='complex', const='bass', vlen=1)
    gm = g.b('blocks_multiply_const_vxx', 'g_mid', type='complex', const='mid', vlen=1)
    gt = g.b('blocks_multiply_const_vxx', 'g_treble', type='complex', const='treble', vlen=1)
    ad = g.b('blocks_add_xx', 'mix', type='complex', num_inputs=3, vlen=1)
    dac = g.b('grv_i2s_sink', 'codec_out', type='complex', role='master', samp_rate=48e3, slot_bits=32,
              data_bits=24, format='i2s', drop='True', repeat='True')
    g.c(adc, lp); g.c(adc, lp2)
    g.c(adc, hp, 0, 0); g.c(lp2, hp, 0, 1)
    g.c(lp2, md, 0, 0); g.c(lp, md, 0, 1)
    g.c(lp, gb); g.c(md, gm); g.c(hp, gt)
    g.c(gb, ad, 0, 0); g.c(gm, ad, 0, 1); g.c(gt, ad, 0, 2)
    g.c(ad, dac)


# ------------------------------------------------------------------ 7. DTMF generator
@example('dtmf_gen', 'DTMF generator on a sigma-delta pin and I2S', 600,
         'A DTMF tone generator: two oscillators with runtime frequencies (the row and column tones of a '
         'key) are summed and scaled, then played on a single pin as a second-order sigma-delta bit stream '
         '(an RC filter makes it analogue) and on an I2S DAC.', params={'f_row': 852, 'f_col': 1477})
def ex_dtmf(g):
    g.var('fs', 48e3)
    var(g, 'f_row', 697, 600, 1000, 1, 'Row tone (Hz)')
    var(g, 'f_col', 1209, 1100, 1700, 1, 'Column tone (Hz)')
    var(g, 'volume', 0.4, 0, 0.5, 0.01, 'Level')
    a = g.b('analog_sig_source_x', 'row', type='float', samp_rate='fs', waveform='analog.GR_SIN_WAVE', freq='f_row',
            amp=1, offset=0, phase=0)
    b = g.b('analog_sig_source_x', 'col', type='float', samp_rate='fs', waveform='analog.GR_SIN_WAVE', freq='f_col',
            amp=1, offset=0, phase=0)
    ad = g.b('blocks_add_xx', 'sum', type='float', num_inputs=2, vlen=1)
    k = g.b('blocks_multiply_const_vxx', 'level', type='float', const='volume', vlen=1)
    sd = g.b('grv_gpio_sink', 'pin', type='float', pins=1, mode='sdm', data_bits=12, samp_rate='fs', repeat='True')
    i2s = g.b('grv_i2s_sink', 'audio', type='float', role='master', samp_rate='fs', slot_bits=16, data_bits=16,
              format='left', duplicate='True', repeat='True')
    g.c(a, ad, 0, 0); g.c(b, ad, 0, 1)
    g.chain(ad, k, sd)
    g.c(k, i2s)


# ------------------------------------------------------------------ 8. digital down-converter
@example('ddc_cic_dma', 'Digital down-converter with CIC and DMA', 65536,
         'A digital down-converter for an ADC at 27 MS/s: a rotator moves the channel to 0 Hz, a '
         'four-stage CIC decimates by 32, a compensating FIR by 2 more, and a DMA channel writes the '
         '421.875 kS/s baseband into a ring buffer in RAM. A probe tracks the channel power.',
         params={'tune': 1.5e6})
def ex_ddc(g):
    g.var('samp_rate', 27e6)
    var(g, 'tune', 0, -10e6, 10e6, 1e3, 'Centre (Hz)')
    adc = g.b('pad_source', 'adc_iq', type='complex', label='adc_iq', num_streams=1, vlen=1, optional=False,
              comment='@grv rate=samp_rate')
    rot = g.b('blocks_rotator_cc', 'mixer', phase_inc='-2 * math.pi * tune / samp_rate')
    cic = g.b('grv_cic_decim', 'cic', type='complex', stages=4, ratio=32, diff_delay=1)
    fir = g.b('low_pass_filter', 'cfir', type='fir_filter_ccf', decim=2, interp=1, gain=1,
              samp_rate='samp_rate / 32', cutoff_freq=150e3, width=60e3, win='window.WIN_BLACKMAN', beta=6.76)
    dma = g.b('grv_dma_sink', 'baseband', type='complex', mode='ring', burst=4, drop='True')
    g.chain(adc, rot, cic, fir, dma)
    m2 = g.b('blocks_complex_to_mag_squared', 'pwr', vlen=1)
    av = g.b('single_pole_iir_filter_xx', 'avg', type='float', alpha=0.02, vlen=1)
    pr = g.b('blocks_probe_signal_x', 'power', type='float')
    g.chain(fir, m2, av, pr)


# ------------------------------------------------------------------ 9. level meter
@example('level_meter_spi', 'Level meter: SPI ADC, LED and UART log', 20000,
         'An audio level meter: a 12-bit SPI ADC samples at 200 kS/s, DC is removed, the rectified signal '
         'is averaged over 1 ms and read 1000 times per second. The level drives an alarm LED through a '
         'threshold with hysteresis, is logged as text on a UART and is readable from a probe.')
def ex_meter(g):
    g.var('fs', 200e3)
    adc = g.b('grv_spi_source', 'adc', type='float', role='master', samp_rate='fs', sclk=13.5e6, mode=0,
              frame_bits=16, data_pos=1, data_bits=12, offset_binary='True')
    dc = g.b('dc_blocker_xx', 'dcb', type='ff', length=32, long_form=False)
    ab = g.b('blocks_abs_xx', 'rect', type='float', vlen=1)
    ma = g.b('blocks_moving_average_xx', 'mean', type='float', length=200, scale=1 / 200, max_iter=4000, vlen=1)
    k = g.b('blocks_keep_one_in_n', 'every_1ms', type='float', n=200, vlen=1)
    th = g.b('blocks_threshold_ff', 'alarm', low=0.2, high=0.3, init=0)
    tc = g.b('blocks_float_to_uchar', 'to_led', vlen=1, scale=1, bias=0)
    led = g.b('grv_gpio_sink', 'led', type='byte', pins=1, mode='parallel')
    log = g.b('grv_uart_sink', 'log', type='float', baud=115200, text='True', drop='True')
    pr = g.b('blocks_probe_signal_x', 'level', type='float')
    g.chain(adc, dc, ab, ma, k, th, tc, led)
    g.c(k, log); g.c(k, pr)


# ------------------------------------------------------------------ 10. signal generator
@example('siggen_spi_dac', 'Two-channel signal generator', 1500,
         'A signal generator: a quadrature oscillator with runtime frequency and level drives a dual SPI '
         'DAC (sine and cosine on channels A and B) at 100 kS/s, and a sawtooth drives a PWM pin.',
         params={'freq': 2500, 'amp': 0.8})
def ex_siggen(g):
    g.var('fs', 100e3)
    var(g, 'freq', 1000, 10, 20e3, 10, 'Frequency (Hz)')
    var(g, 'amp', 0.5, 0, 1, 0.01, 'Level')
    q = g.b('analog_sig_source_x', 'quad', type='complex', samp_rate='fs', waveform='analog.GR_COS_WAVE', freq='freq',
            amp=1, offset=0, phase=0)
    k = g.b('blocks_multiply_const_vxx', 'level', type='complex', const='amp', vlen=1)
    dac = g.b('grv_spi_sink', 'dac', type='complex', role='master', samp_rate='fs', sclk=13.5e6, mode=0, frame_bits=16,
              data_pos=0, data_bits=12, offset_binary='True', cmd=0x3000, cmd_q=0xB000, repeat='True')
    g.chain(q, k, dac)
    saw = g.b('analog_sig_source_x', 'saw', type='float', samp_rate='fs', waveform='analog.GR_SAW_WAVE', freq=200,
              amp=1.8, offset=-0.9, phase=0)
    pwm = g.b('grv_gpio_sink', 'pwm', type='float', pins=1, mode='pwm', data_bits=8)
    g.chain(saw, pwm)


def build(name):
    e = EX[name]
    g = G(name)
    e['f'](g)
    layout(g)
    d = os.path.join(ROOT, 'examples', name)
    os.makedirs(d, exist_ok=True)
    path = g.write(os.path.join(d, name + '.grc'))
    # title and description in the options block
    import yaml
    y = yaml.safe_load(open(path))
    y['options']['parameters'].update(title=e['title'], description=e['desc'], author='OpenGRV examples')
    y['options']['states']['coordinate'] = [16, 12]
    with open(path, 'w') as f:
        yaml.safe_dump(y, f, sort_keys=False, default_flow_style=None, width=200)
    return path


def main():
    names = sys.argv[1:] or list(EX)
    for n in names:
        print(build(n))
    meta = {n: dict(title=EX[n]['title'], n=EX[n]['n'], desc=EX[n]['desc'], params=EX[n]['params'], args=EX[n]['args'])
            for n in EX}
    json.dump(meta, open(os.path.join(ROOT, 'examples', 'examples.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
