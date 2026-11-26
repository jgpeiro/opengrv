#!/usr/bin/env python3
"""Graph-level tests: each test writes a GRC flowgraph, compiles it with grvgen, builds the generated
Verilator testbench and checks the hardware (through AXI4-Lite and the pads, with random handshakes)
against the bit-exact model of the graph.

    python3 tb/graph/test_graphs.py [-k NAME,...] [-j JOBS] [-n SAMPLES]"""
import os, sys, subprocess, argparse, shutil, time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
from mkgrc import G  # noqa: E402

TESTS = {}


def test(name, args=(), n=600, tbargs=()):
    def deco(f):
        TESTS[name] = (f, list(args), n, list(tbargs))
        return f
    return deco


def snk(g, src, name, t='float', port=0):
    s = g.b('grv_axil_sink', name, type=t, depth=64)
    g.c(src, s, port, 0)
    return s


# ------------------------------------------------------------------ sources and arithmetic
@test('sources_math')
def g_sources_math(g):
    g.var('samp_rate', 1e6)
    cos = g.b('analog_sig_source_x', 'cosw', type='float', samp_rate='samp_rate', waveform='analog.GR_COS_WAVE', freq=12345, amp=0.8, offset=0, phase=0)
    nz = g.b('analog_noise_source_x', 'nz', type='float', noise_type='analog.GR_GAUSSIAN', amp=0.1, seed=3)
    add = g.b('blocks_add_xx', 'add', type='float', num_inputs=2, vlen=1)
    g.c(cos, add, 0, 0); g.c(nz, add, 0, 1)
    k = g.b('blocks_multiply_const_vxx', 'k075', type='float', const=0.75, vlen=1)
    g.c(add, k); snk(g, k, 'o_add')
    mul = g.b('blocks_multiply_xx', 'mul', type='float', num_inputs=2, vlen=1)
    g.c(cos, mul, 0, 0); g.c(nz, mul, 0, 1); snk(g, mul, 'o_mul')
    sub = g.b('blocks_sub_xx', 'sub', type='float', num_inputs=2, vlen=1)
    g.c(cos, sub, 0, 0); g.c(k, sub, 0, 1); snk(g, sub, 'o_sub')
    waves = []
    for w in ('SQR', 'TRI', 'SAW'):
        waves.append(g.b('analog_sig_source_x', f'w{w.lower()}', type='float', samp_rate='samp_rate', waveform=f'analog.GR_{w}_WAVE',
                         freq=23456, amp=0.5, offset=0.1, phase=0))
    mx = g.b('blocks_max_xx', 'mx', type='float', num_inputs=3, vlen=1)
    for i, w in enumerate(waves):
        g.c(w, mx, 0, i)
    snk(g, mx, 'o_max')
    mn = g.b('blocks_min_xx', 'mn', type='float', num_inputs=2, vlen=1)
    g.c(waves[0], mn, 0, 0); g.c(waves[1], mn, 0, 1); snk(g, mn, 'o_min')
    th = g.b('blocks_threshold_ff', 'th', low=-0.2, high=0.3, init=0)
    g.c(waves[2], th); snk(g, th, 'o_thr')
    cs = g.b('analog_const_source_x', 'cs', type='float', const=0.25)
    ac = g.b('blocks_add_const_vxx', 'ac', type='float', const=-0.125, vlen=1)
    ab = g.b('blocks_abs_xx', 'ab', type='float', vlen=1)
    g.chain(cs, ac, ab); snk(g, ab, 'o_const')


@test('complex_math')
def g_complex_math(g):
    g.var('samp_rate', 1e6)
    a = g.b('analog_sig_source_x', 'ca', type='complex', samp_rate='samp_rate', waveform='analog.GR_COS_WAVE', freq=50e3, amp=0.5, offset=0, phase=0.3)
    n = g.b('analog_noise_source_x', 'cn', type='complex', noise_type='analog.GR_UNIFORM', amp=0.3, seed=7)
    rot = g.b('blocks_rotator_cc', 'rot', phase_inc=0.1)
    cj = g.b('blocks_conjugate_cc', 'cj')
    g.chain(a, rot, cj)
    mc = g.b('blocks_multiply_conjugate_cc', 'mc', vlen=1)
    g.c(cj, mc, 0, 0); g.c(n, mc, 0, 1)
    m2 = g.b('blocks_complex_to_mag_squared', 'm2', vlen=1)
    g.c(mc, m2); snk(g, m2, 'o_mag2')
    ar = g.b('blocks_complex_to_arg', 'arg', vlen=1)
    g.c(n, ar); snk(g, ar, 'o_arg')
    mg = g.b('blocks_complex_to_mag', 'mag', vlen=1)
    g.c(rot, mg); snk(g, mg, 'o_mag')
    c2f = g.b('blocks_complex_to_float', 'c2f', vlen=1)
    g.c(a, c2f)
    f2c = g.b('blocks_float_to_complex', 'f2c', vlen=1)
    g.c(c2f, f2c, 1, 0); g.c(c2f, f2c, 0, 1)
    snk(g, f2c, 'o_swap', 'complex')
    re = g.b('blocks_complex_to_real', 're', vlen=1)
    g.c(mc, re); snk(g, re, 'o_re')
    mk = g.b('blocks_multiply_const_vxx', 'mkc', type='complex', const='0.5-0.25j', vlen=1)
    g.c(n, mk); snk(g, mk, 'o_kc', 'complex')
    mul = g.b('blocks_multiply_xx', 'cmul', type='complex', num_inputs=2, vlen=1)
    g.c(a, mul, 0, 0); g.c(n, mul, 0, 1); snk(g, mul, 'o_cmul', 'complex')
    mp = g.b('blocks_complex_to_magphase', 'mp', vlen=1)
    g.c(cj, mp); snk(g, mp, 'o_mpm', port=0); snk(g, mp, 'o_mpp', port=1)


# ------------------------------------------------------------------ stream operations
@test('stream_ops')
def g_stream(g):
    def vs(name, vec):
        return g.b('blocks_vector_source_x', name, type='short', vector=vec, repeat=True, vlen=1, tags='[]')
    v1 = vs('v1', 'list(range(1, 21))')
    v2 = vs('v2', '[-100, -200, -300, -400, -500, -600, -700]')
    rp = g.b('blocks_repeat', 'rp', type='short', interp=3, vlen=1)
    k1 = g.b('blocks_keep_one_in_n', 'k1', type='short', n=2, vlen=1)
    dl = g.b('blocks_delay', 'dl', type='short', delay=5, num_ports=1, vlen=1)
    g.chain(v1, rp, k1, dl)
    sm = g.b('blocks_stream_mux', 'sm', type='short', lengths='[2, 3]', num_inputs=2, vlen=1)
    g.c(dl, sm, 0, 0); g.c(v2, sm, 0, 1)
    di = g.b('blocks_deinterleave', 'di', type='short', num_streams=2, blocksize=1, vlen=1)
    g.c(sm, di)
    snk(g, di, 'o_d0', 'short', 0); snk(g, di, 'o_d1', 'short', 1)
    v3, v4 = vs('v3', '[1, 2, 3, 4, 5]'), vs('v4', '[10, 20, 30]')
    il = g.b('blocks_interleave', 'il', type='short', num_streams=2, blocksize=2, vlen=1)
    g.c(v3, il, 0, 0); g.c(v4, il, 0, 1)
    hd = g.b('blocks_head', 'hd', type='short', num_items=37, vlen=1)
    sk = g.b('blocks_skiphead', 'sk', type='short', num_items=7)
    g.chain(il, sk, hd); snk(g, hd, 'o_head', 'short')
    v5 = vs('v5', 'list(range(-50, 50, 7))')
    km = g.b('blocks_keep_m_in_n', 'km', type='short', m=2, n=5, offset=1, vlen=1)
    g.c(v5, km); snk(g, km, 'o_kmn', 'short')
    v6, v7 = vs('v6', 'list(range(0, 3000, 13))'), vs('v7', 'list(range(5, -900, -31))')
    ad = g.b('blocks_add_xx', 'iadd', type='short', num_inputs=2, vlen=1)
    g.c(v6, ad, 0, 0); g.c(v7, ad, 0, 1)
    an = g.b('blocks_and_const_xx', 'anc', type='short', const=0x3F)
    xo = g.b('blocks_xor_xx', 'xo', type='short', num_inputs=2)
    g.c(ad, an); g.c(an, xo, 0, 0); g.c(v6, xo, 0, 1); snk(g, xo, 'o_logic', 'short')
    v8 = vs('v8', '[7, 8, 9]')
    cp = g.b('blocks_copy', 'cp', type='short', enabled=True, showports=False, vlen=1)
    g.c(v8, cp); snk(g, cp, 'o_copy', 'short')
    v9 = vs('v9', 'list(range(100))')
    s2v = g.b('blocks_stream_to_vector', 's2v', type='short', num_items=4, vlen=1)
    v2s = g.b('blocks_vector_to_stream', 'v2s', type='short', num_items=4, vlen=1)
    g.chain(v9, s2v, v2s); snk(g, v2s, 'o_vec', 'short')


@test('vectors_fft')
def g_fft(g):
    g.var('samp_rate', 1e6)
    a = g.b('analog_sig_source_x', 'tone', type='complex', samp_rate='samp_rate', waveform='analog.GR_COS_WAVE', freq=125e3, amp=0.7, offset=0, phase=0)
    n = g.b('analog_noise_source_x', 'nz', type='complex', noise_type='analog.GR_GAUSSIAN', amp=0.05, seed=1)
    ad = g.b('blocks_add_xx', 'ad', type='complex', num_inputs=2, vlen=1)
    g.c(a, ad, 0, 0); g.c(n, ad, 0, 1)
    s2v = g.b('blocks_stream_to_vector', 's2v', type='complex', num_items=64, vlen=1)
    ff = g.b('fft_vxx', 'ff', type='complex', fft_size=64, forward=True, window='window.blackmanharris(64)', shift=True, nthreads=1)
    v2s = g.b('blocks_vector_to_stream', 'v2s', type='complex', num_items=64, vlen=1)
    g.chain(ad, s2v, ff, v2s)
    m2 = g.b('blocks_complex_to_mag_squared', 'm2', vlen=1)
    g.c(v2s, m2); snk(g, m2, 'o_psd')
    snk(g, v2s, 'o_fft', 'complex')


# ------------------------------------------------------------------ filters
def filt_graph(g, fold):
    g.var('samp_rate', 1e6)
    x = g.b('pad_source', 'xin', type='float', label='xin', comment='@grv rate=samp_rate' if fold else '', vlen=1, num_streams=1)
    f1 = g.b('fir_filter_xxx', 'f_dec', type='fff', decim=3, taps='firdes.low_pass(1, 1, 0.1, 0.05)', samp_delay=0)
    g.c(x, f1); snk(g, f1, 'o_dec')
    f2 = g.b('interp_fir_filter_xxx', 'f_int', type='fff', interp=2, taps='[0.1, -0.2, 0.5, 0.9, 0.5, -0.2, 0.1]', samp_delay=0)
    g.c(x, f2); snk(g, f2, 'o_int')
    f3 = g.b('rational_resampler_xxx', 'rr', type='fff', interp=3, decim=2, taps='[]', fbw=0.4)
    g.c(x, f3); snk(g, f3, 'o_rr')
    ma = g.b('blocks_moving_average_xx', 'ma', type='float', length=8, scale=0.125, max_iter=4000, vlen=1)
    g.c(x, ma); snk(g, ma, 'o_ma')
    it = g.b('blocks_integrate_xx', 'it', type='float', decim=4, vlen=1)
    g.c(x, it); snk(g, it, 'o_int4')
    dc = g.b('dc_blocker_xx', 'dc', type='ff', length=16, long_form=False)
    g.c(x, dc); snk(g, dc, 'o_dc')
    ii = g.b('single_pole_iir_filter_xx', 'ii', type='float', alpha=0.1, vlen=1)
    g.c(x, ii); snk(g, ii, 'o_iir')
    ci = g.b('grv_cic_decim', 'cic', stages=3, ratio=4, diff_delay=1)
    g.c(x, ci); snk(g, ci, 'o_cic')
    y = g.b('pad_source', 'yin', type='complex', label='yin', comment='@grv rate=samp_rate' if fold else '', vlen=1, num_streams=1)
    bp = g.b('band_pass_filter', 'bp', type='fir_filter_ccc', decim=2, interp=1, gain=1, samp_rate='samp_rate',
             low_cutoff_freq=50e3, high_cutoff_freq=150e3, width=50e3, win='window.WIN_HAMMING', beta=6.76)
    g.c(y, bp); snk(g, bp, 'o_bp', 'complex')
    rc = g.b('root_raised_cosine_filter', 'rrc', type='fir_filter_ccf', decim=1, interp=1, gain=1, samp_rate=4, sym_rate=1, alpha=0.35, ntaps=33)
    g.c(y, rc); snk(g, rc, 'o_rrc', 'complex')
    xl = g.b('freq_xlating_fir_filter_xxx', 'xl', type='ccc', decim=4, taps='firdes.low_pass(1, samp_rate, 60e3, 30e3)', center_freq=-125e3, samp_rate='samp_rate')
    g.c(y, xl); snk(g, xl, 'o_xl', 'complex')


@test('filters_folded', n=1200)
def g_filt_f(g):
    filt_graph(g, True)


@test('filters_parallel', args=['--fold', 'off'], n=600)
def g_filt_p(g):
    filt_graph(g, False)


# ------------------------------------------------------------------ digital
@test('digital', n=800)
def g_digital(g):
    g.var('qpsk', 0, kind='variable_constellation', const_points='[(-1-1j)/1.4142, (1-1j)/1.4142, (-1+1j)/1.4142, (1+1j)/1.4142]',
          sym_map='[0, 1, 2, 3]', type='calcdist', dims=1, rot_sym=4, precision=8, soft_dec_lut='None')
    bits = g.b('digital_glfsr_source_x', 'prbs', type='byte', degree=9, mask=0x110, seed=1, repeat=True)
    pk = g.b('blocks_pack_k_bits_bb', 'pk', k=2)
    de = g.b('digital_diff_encoder_bb', 'de', modulus=4, coding='digital.DIFF_DIFFERENTIAL')
    cs = g.b('digital_chunks_to_symbols_xx', 'c2s', in_type='byte', out_type='complex', symbol_table='[(-1-1j)/1.4142, (1-1j)/1.4142, (-1+1j)/1.4142, (1+1j)/1.4142]',
             dimension=1, num_ports=1)
    rot = g.b('blocks_rotator_cc', 'chan', phase_inc=0.002)
    co = g.b('digital_costas_loop_cc', 'costas', w=0.05, order=4, use_snr=False)
    dec = g.b('digital_constellation_decoder_cb', 'cdec', constellation='qpsk')
    dd = g.b('digital_diff_decoder_bb', 'dd', modulus=4, coding='digital.DIFF_DIFFERENTIAL')
    g.chain(bits, pk, de, cs, rot, co, dec, dd)
    snk(g, dd, 'o_syms', 'byte'); snk(g, co, 'o_costas', 'complex')
    sc = g.b('digital_scrambler_bb', 'scr', mask=0x8A, seed=0x7F, len=7)
    ds = g.b('digital_descrambler_bb', 'dscr', mask=0x8A, seed=0x7F, len=7)
    g.chain(bits, sc, ds); snk(g, ds, 'o_descr', 'byte'); snk(g, sc, 'o_scr', 'byte')
    asc = g.b('digital_additive_scrambler_bb', 'ascr', mask=0x8A, seed=0x7F, len=7, count=100, bits_per_byte=1, reset_tag_key='""')
    g.c(bits, asc); snk(g, asc, 'o_ascr', 'byte')
    ac = g.b('digital_correlate_access_code_bb', 'acc', access_code='"101100111000"', threshold=1)
    g.c(bits, ac); snk(g, ac, 'o_acc', 'byte')
    up = g.b('blocks_packed_to_unpacked_xx', 'p2u', type='byte', bits_per_chunk=2, endianness='gr.GR_MSB_FIRST', num_ports=1)
    u2p = g.b('blocks_unpacked_to_packed_xx', 'u2p', type='byte', bits_per_chunk=1, endianness='gr.GR_LSB_FIRST', num_ports=1)
    g.chain(bits, u2p, up); snk(g, up, 'o_p2u', 'byte')
    rb = g.b('blocks_repack_bits_bb', 'rb', k=2, l=3, endianness='gr.GR_LSB_FIRST', align_output=False, len_tag_key='""')
    g.c(pk, rb); snk(g, rb, 'o_repack', 'byte')
    mp = g.b('digital_map_bb', 'mp', map='[3, 2, 1, 0]')
    g.c(pk, mp); snk(g, mp, 'o_map', 'byte')
    fb = g.b('digital_chunks_to_symbols_xx', 'c2f', in_type='byte', out_type='float', symbol_table='[-1.0, 1.0]', dimension=1, num_ports=1)
    sl = g.b('digital_binary_slicer_fb', 'sl')
    g.chain(bits, fb, sl); snk(g, sl, 'o_slice', 'byte')


@test('modem_misc', n=800)
def g_modem(g):
    g.var('samp_rate', 1e6)
    a = g.b('analog_sig_source_x', 'tone', type='float', samp_rate='samp_rate', waveform='analog.GR_SIN_WAVE', freq=7e3, amp=0.5, offset=0, phase=0)
    fm = g.b('analog_frequency_modulator_fc', 'fm', sensitivity=0.3)
    g.c(a, fm); snk(g, fm, 'o_fm', 'complex')
    k = g.b('blocks_multiply_const_vxx', 'att', type='complex', const=0.05, vlen=1)
    agc = g.b('analog_agc_xx', 'agc', type='complex', rate=1e-2, reference=0.5, gain=1, max_gain=100)
    g.chain(fm, k, agc); snk(g, agc, 'o_agc', 'complex')
    sq = g.b('analog_pwr_squelch_xx', 'sq', type='complex', threshold=-30, alpha=0.01, ramp=0, gate=False)
    g.c(k, sq); snk(g, sq, 'o_sq', 'complex')
    i16 = g.b('blocks_complex_to_interleaved_short', 'c2is', scale_factor=32768, vector=False)
    g.c(fm, i16); snk(g, i16, 'o_is', 'short')
    back = g.b('blocks_interleaved_short_to_complex', 'is2c', scale_factor='1/32768', swap=False, vector_input=False)
    g.c(i16, back); snk(g, back, 'o_isc', 'complex')
    f2s = g.b('blocks_float_to_short', 'f2s', scale=1000, vlen=1)
    s2f = g.b('blocks_short_to_float', 's2f', scale=1000, vlen=1)
    g.chain(a, f2s, s2f); snk(g, s2f, 'o_s2f')
    f2c = g.b('blocks_float_to_char', 'f2ch', scale=100, vlen=1)
    g.c(a, f2c); snk(g, f2c, 'o_char', 'byte')
    src = g.b('grv_axil_source', 'host', type='float', depth=64)
    q = g.b('analog_quadrature_demod_cf', 'qd', gain=2)
    g.chain(fm, q); snk(g, q, 'o_qd')
    hm = g.b('blocks_multiply_xx', 'hm', type='float', num_inputs=2, vlen=1)
    g.c(src, hm, 0, 0); g.c(a, hm, 0, 1)
    po = g.b('pad_sink', 'hout', type='float', label='hout', vlen=1, num_streams=1)
    g.c(hm, po)
    pr = g.b('blocks_probe_signal_x', 'prb', type='float')
    g.c(hm, pr)
    nul = g.b('blocks_null_sink', 'nul', type='complex', vlen=1, num_inputs=1)
    g.c(agc, nul)


@test('misc_params', n=600, tbargs=['--param', 'sel=2', '--param', 'gain=1.2', '--param', 'en=False'])
def g_misc_p(g):
    g_misc(g)


@test('misc_runtime', n=600)
def g_misc(g):
    g.var('samp_rate', 1e6)
    g.var('sel', 1, kind='variable_qtgui_chooser', num_opts=3, option0=0, option1=1, option2=2, labels='[]', type='int')
    g.var('en', True, kind='variable_qtgui_check_box', true=True, false=False, type='bool')
    g.var('gain', 0.5, kind='variable_qtgui_range', start=0, stop=1.5, step=0.01)
    a = g.b('analog_sig_source_x', 'a', type='float', samp_rate='samp_rate', waveform='analog.GR_COS_WAVE', freq=3e3, amp='gain', offset=0, phase=0)
    b = g.b('analog_sig_source_x', 'b', type='float', samp_rate='samp_rate', waveform='analog.GR_SAW_WAVE', freq=9e3, amp=0.3, offset=0, phase=0)
    c = g.b('analog_noise_source_x', 'c', type='float', noise_type='analog.GR_UNIFORM', amp=0.2, seed=5)
    se = g.b('blocks_selector', 'se', type='float', num_inputs=3, num_outputs=1, input_index='sel', output_index=0, enabled='en', vlen=1, showports=True)
    g.c(a, se, 0, 0); g.c(b, se, 0, 1); g.c(c, se, 0, 2)
    snk(g, se, 'o_sel')
    hp = g.b('high_pass_filter', 'hp', type='fir_filter_fff', decim=1, interp=1, gain=2, samp_rate='samp_rate', cutoff_freq=100e3, width=50e3, win='window.WIN_HANN', beta=6.76)
    g.c(c, hp); snk(g, hp, 'o_hp')
    br = g.b('band_reject_filter', 'br', type='fir_filter_fff', decim=1, interp=1, gain=1, samp_rate='samp_rate', low_cutoff_freq=100e3, high_cutoff_freq=200e3, width=50e3, win='window.WIN_BLACKMAN', beta=6.76)
    g.c(c, br); snk(g, br, 'o_br')
    ci = g.b('grv_cic_interp', 'ci', type='float', stages=2, ratio=3, diff_delay=1)
    g.c(b, ci); snk(g, ci, 'o_cici')
    pm = g.b('analog_phase_modulator_fc', 'pm', sensitivity=1.5)
    g.c(a, pm); snk(g, pm, 'o_pm', 'complex')
    sq = g.b('analog_simple_squelch_cc', 'ssq', threshold=-20, alpha=0.05)
    g.c(pm, sq); snk(g, sq, 'o_ssq', 'complex')
    q = g.b('grv_quantize', 'q8', type='float', comment='@grv fmt=s8.6')
    g.c(c, q); snk(g, q, 'o_q8')
    gf = g.b('digital_glfsr_source_x', 'gf', type='float', degree=7, mask=0x44, seed=3, repeat=True)
    mk = g.b('blocks_multiply_const_vxx', 'mk', type='float', const='gain', vlen=1)
    g.chain(gf, mk); snk(g, mk, 'o_glfsr')
    f2i = g.b('blocks_float_to_int', 'f2i', scale=1000, vlen=1)
    i2f = g.b('blocks_int_to_float', 'i2f', scale=1000, vlen=1)
    g.chain(b, f2i, i2f); snk(g, i2f, 'o_i2f')
    f2c = g.b('blocks_float_to_char', 'f2c', scale=100, vlen=1)
    c2s = g.b('blocks_char_to_short', 'c2s', vlen=1)
    s2c = g.b('blocks_short_to_char', 's2c', vlen=1)
    g.chain(b, f2c, c2s, s2c); snk(g, s2c, 'o_s2c', 'byte')
    nt = g.b('blocks_not_xx', 'nt', type='byte')
    g.chain(s2c, nt); snk(g, nt, 'o_not', 'byte')
    th = g.b('blocks_throttle', 'th', type='float', samples_per_second=5e6, ignoretag=True, vlen=1)
    g.c(a, th); snk(g, th, 'o_thr')


# ------------------------------------------------------------------ peripheral endpoints and DMA (revision 0.2)
def src(g, name, t='short', **kw):
    return g.b('grv_axil_source', name, type=t, depth=64, **kw)


@test('pe_uart', n=300)
def g_pe_uart(g):
    # receiver (even parity, two stop bits) -> x2 -> AXI4-Lite
    urx = g.b('grv_uart_source', 'urx', type='short', baud=921600, parity='even', stop_bits=2)
    k = g.b('blocks_multiply_const_vxx', 'k2', type='short', const=2, vlen=1)
    g.chain(urx, k); snk(g, k, 'o_urx', 'short')
    # AXI4-Lite -> transmitter, most significant byte first
    a = src(g, 'i_bin')
    g.c(a, g.b('grv_uart_sink', 'utx', type='short', baud=921600, msb_first='True'))
    # complex samples as hexadecimal text (8 digits and a line feed)
    c = src(g, 'i_txt', 'complex')
    g.c(c, g.b('grv_uart_sink', 'utxt', type='complex', baud=921600, text='True'))
    # flow control and inverted lines on both sides: receiver -> transmitter
    urf = g.b('grv_uart_source', 'urf', type='byte', baud=1e6, flow='True', invert='True', parity='odd')
    g.c(urf, g.b('grv_uart_sink', 'utf', type='byte', baud=1e6, flow='True', invert='True', parity='odd'))
    # a standard block mapped with @grv via=uart
    b = src(g, 'i_via')
    g.c(b, g.b('blocks_file_sink', 'fvia', type='short', file='/dev/null', comment='@grv via=uart baud=460800'))


@test('pe_spi_master', n=300)
def g_pe_spi_master(g):
    g.var('fs', 270e3)
    # ADC: 12-bit field at bit 2 of a 16-bit frame, offset binary, mode 0
    adc = g.b('grv_spi_source', 'adc', type='float', role='master', samp_rate='fs', sclk=13.5e6, frame_bits=16,
              data_pos=2, data_bits=12, offset_binary='True', cmd=0x8000)
    snk(g, adc, 'o_adc')
    # complex ADC: 24-bit frames, 16-bit field at bit 4, mode 3, LSB first, command words for I and Q
    adq = g.b('grv_spi_source', 'adq', type='complex', role='master', samp_rate='fs / 3', sclk=6.75e6, mode=3,
              frame_bits=24, data_pos=4, data_bits=16, lsb_first='True', cmd=0x100000, cmd_q=0x200000, sample_delay=1)
    snk(g, adq, 'o_adq', 'complex')
    # DAC, paced, mode 1, 16-bit frames with a command in the upper bits
    d = src(g, 'i_dac', 'float')
    g.c(d, g.b('grv_spi_sink', 'dac', type='float', role='master', samp_rate='fs / 3', sclk=13.5e6, mode=1,
               frame_bits=16, data_bits=12, cmd=0x3000))
    # complex DAC, unpaced (a frame as soon as a sample is there), mode 2
    dq = src(g, 'i_dacq', 'complex')
    g.c(dq, g.b('grv_spi_sink', 'dacq', type='complex', role='master', sclk=9e6, mode=2, frame_bits=20, data_pos=8,
                data_bits=10, cs_setup=3, cs_hold=2, cs_gap=5))


@test('pe_spi_slave', n=200)
def g_pe_spi_slave(g):
    rx = g.b('grv_spi_source', 'srx', type='short', role='slave', frame_bits=16, data_bits=16)
    snk(g, rx, 'o_srx', 'short')
    rq = g.b('grv_spi_source', 'srxq', type='complex', role='slave', mode=3, frame_bits=16, data_pos=2, data_bits=12,
             offset_binary='True')
    snk(g, rq, 'o_srxq', 'complex')
    t = src(g, 'i_stx')
    g.c(t, g.b('grv_spi_sink', 'stx', type='short', role='slave', mode=1, frame_bits=16, data_bits=16, cmd=0xFFFF))
    tq = src(g, 'i_stxq', 'complex')
    g.c(tq, g.b('grv_spi_sink', 'stxq', type='complex', role='slave', mode=2, frame_bits=12, data_bits=10, lsb_first='True'))


@test('pe_gpio', n=300)
def g_pe_gpio(g):
    g.var('samp_rate', 540e3)
    # periodic input with a sample clock, offset binary
    gp = g.b('grv_gpio_source', 'gper', type='float', pins=10, mode='periodic', samp_rate='samp_rate',
             offset_binary='True', clk_out='True', phase=3)
    snk(g, gp, 'o_gper')
    # strobed complex input (2 x 6 pins), falling edge
    gs = g.b('grv_gpio_source', 'gstb', type='complex', pins=12, mode='strobe', edge='falling')
    snk(g, gs, 'o_gstb', 'complex')
    # input sampled on change (bytes)
    gc = g.b('grv_gpio_source', 'gchg', type='byte', pins=8, mode='change', filter=3)
    snk(g, gc, 'o_gchg', 'byte')
    # parallel output, paced, offset binary, with a clock for the DAC
    a = src(g, 'i_par', 'float')
    g.c(a, g.b('grv_gpio_sink', 'gpar', type='float', pins=12, mode='parallel', samp_rate='samp_rate / 2',
               offset_binary='True', clk_out='True'))
    # PWM (8 bits, one sample per period)
    pw = src(g, 'i_pwm', 'float')
    g.c(pw, g.b('grv_gpio_sink', 'gpwm', type='float', pins=1, mode='pwm', data_bits=8))
    # second-order sigma-delta, complex (two pins), paced
    sc = g.b('analog_sig_source_x', 'sc', type='complex', samp_rate='samp_rate / 8', waveform='analog.GR_COS_WAVE',
             freq=600, amp=0.7, offset=0, phase=0)
    g.c(sc, g.b('grv_gpio_sink', 'gsdm', type='complex', pins=2, mode='sdm', data_bits=12, samp_rate='samp_rate / 8'))


@test('pe_i2s', n=200)
def g_pe_i2s(g):
    # stereo ADC, master, Philips I2S, 16-bit slots
    a = g.b('grv_i2s_source', 'adc', type='complex', role='master', samp_rate=96e3, slot_bits=16, data_bits=16)
    k = g.b('blocks_multiply_const_vxx', 'k', type='complex', const=0.5, vlen=1)
    g.chain(a, k); snk(g, k, 'o_adc', 'complex')
    # microphone, slave, left-justified, 24 of 32 bits, right channel
    b = g.b('grv_i2s_source', 'mic', type='float', role='slave', samp_rate=48e3, slot_bits=32, data_bits=24,
            format='left', channel='right')
    snk(g, b, 'o_mic')
    # stereo DAC, master with MCLK
    c = src(g, 'i_dac', 'complex')
    g.c(c, g.b('grv_i2s_sink', 'dac', type='complex', role='master', samp_rate=96e3, slot_bits=16, data_bits=16,
               mclk=13.5e6))
    # amplifier, slave, right-justified 20 of 32 bits, mono on both channels
    d = src(g, 'i_amp', 'float')
    g.c(d, g.b('grv_i2s_sink', 'amp', type='float', role='slave', samp_rate=48e3, slot_bits=32, data_bits=20,
               format='right', duplicate='True'))
    # a standard block mapped with @grv via=i2s
    e = src(g, 'i_via', 'float')
    g.c(e, g.b('audio_sink', 'spk', samp_rate=48000, device_name='', ok_to_block='True', num_inputs=1,
               comment='@grv via=i2s samp_rate=48e3 slot_bits=16 data_bits=16'))


@test('pe_dma', n=400)
def g_pe_dma(g):
    # AXI4-Lite -> S2MM, complex 16-bit (4-byte elements)
    a = src(g, 'i_cap', 'complex')
    g.c(a, g.b('grv_dma_sink', 'dcap', type='complex', mode='single'))
    # MM2S -> x3 -> AXI4-Lite (shorts)
    m = g.b('grv_dma_source', 'dplay', type='short', mode='ring', burst=4)
    k = g.b('blocks_multiply_const_vxx', 'k3', type='short', const=3, vlen=1)
    g.chain(m, k); snk(g, k, 'o_play', 'short')
    # MM2S -> S2MM with 8-byte elements (cs20.19)
    m2 = g.b('grv_dma_source', 'dwide', type='complex', comment='@grv width=20', prio='True')
    g.c(m2, g.b('grv_dma_sink', 'dwcap', type='complex', burst=2, gap=3))
    # bytes (1-byte elements, partial last word) and MSB-aligned 12-bit samples
    b = src(g, 'i_b', 'byte')
    g.c(b, g.b('grv_dma_sink', 'dbyte', type='byte'))
    sg = g.b('analog_sig_source_x', 'sg', type='float', samp_rate=1e6, waveform='analog.GR_SAW_WAVE', freq=1234,
             amp=0.9, offset=0, phase=0, comment='@grv fmt=s12.11')
    g.c(sg, g.b('grv_dma_sink', 'dmsb', type='float', msb_align='True'))
    # a standard block mapped with @grv via=dma
    c = src(g, 'i_via', 'float')
    g.c(c, g.b('zeromq_push_sink', 'zvia', type='float', address='tcp://*:5555', comment='@grv via=dma'))


# ------------------------------------------------------------------ runner
def run_one(name, nsamp, keep):
    f, args, n, tbargs = TESTS[name]
    d = os.path.join(ROOT, 'build', 'tbg', name)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    g = G(name)
    f(g)
    grc = g.write(os.path.join(d, f'{name}.grc'))
    t0 = time.time()
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'grvgen', 'grvgen.py'), grc, '-o', d, '-q'] + args,
                       capture_output=True, text=True)
    if r.returncode:
        return name, False, 'grvgen: ' + r.stderr.strip()
    r = subprocess.run([os.path.join(d, f'{name}_top_sim.sh'), '-n', str(nsamp or n)] + tbargs, capture_output=True, text=True)
    out = r.stdout + r.stderr
    ok = r.returncode == 0 and 'PASS' in out
    return name, ok, out.strip() if not ok else f'{time.time() - t0:.0f} s, ' + ' | '.join(
        l.split()[0] + ' ' + l.split()[2] for l in out.splitlines() if 'samples,' in l)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-k', default='')
    ap.add_argument('-j', type=int, default=4)
    ap.add_argument('-n', type=int, default=0)
    ap.add_argument('--keep', action='store_true')
    a = ap.parse_args()
    names = [n for n in TESTS if not a.k or any(k in n for k in a.k.split(','))]
    fails = 0
    with ThreadPoolExecutor(a.j) as ex:
        for name, ok, msg in ex.map(lambda n: run_one(n, a.n, a.keep), names):
            print(f'{"PASS" if ok else "FAIL"} {name}: {msg if ok else ""}')
            if not ok:
                print('    ' + msg.replace('\n', '\n    ')[-3000:])
                fails += 1
    print(f'{len(names) - fails} / {len(names)} graph tests passed')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
