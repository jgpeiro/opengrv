"""Block mappers: GRC block -> OpenGRV instance(s), formats, ranges, rates and runtime parameters.
Each mapper gets the compiler, the GRC block and its input nets, creates instances and returns
the output nets in GRC port order."""
import math, cmath
from fractions import Fraction
import numpy as np
from .core import Inst, Cfg, INT_FMT
from .fmt import Fmt, for_range, int_bits
from .expr import evaluate, GrvError, Constellation
from .fx import cordic_gain, to_u
from .models import pack_taps

MAPPERS, FINALIZE = {}, {}
WAVE = {100: 0, 101: 1, 102: 2, 103: 3, 104: 4, 105: 5}


def mapper(*ids):
    def deco(f):
        for i in ids:
            MAPPERS[i] = f
        return f
    return deco


def finalize(*mods):
    def deco(f):
        for m in mods:
            FINALIZE[m] = f
        return f
    return deco


# ------------------------------------------------------------------ helpers
def mk(cc, blk, module, params, ins=(), outs=(), kind='block', ovf=True, name=None, ratio=None):
    """ins: [(net, component width)], outs: [(fmt, rng[, ratio[, vlen]])]"""
    i = Inst(cc.uniq(name or blk.prag.get('name', blk.name)), module, params, kind, blk)
    for k, (net, w) in enumerate(ins):
        i.ins.append((net, w))
        net.dst.append((i, k))
    for k, o in enumerate(outs):
        f, r = o[0], o[1]
        n = cc.new_net(f, r, o[3] if len(o) > 3 else 1)
        n.ratio = Fraction(o[2]) if len(o) > 2 and o[2] is not None else Fraction(ratio if ratio is not None else 1)
        n.src = (i, k)
        i.outs.append(n)
    i.ovf = ovf
    cc.insts.append(i)
    return i


def rs(cc, blk, p):
    """rounding and saturation (pragmas)"""
    p['ROUND'] = int(blk.prag.get('round', p.get('ROUND', 1)))
    p['SAT'] = int(blk.prag.get('sat', p.get('SAT', 1)))
    p['OREG'] = 0 if cc.slices == 'none' else 1
    return p


def gtype(cc, blk, default='float'):
    t = cc.raw(blk, 'type', default)
    return {'fc32': 'complex', 'f32': 'float', 's32': 'int', 's16': 'short', 's8': 'byte', 'sc16': 'complex'}.get(t, t)


def out_fmt(cc, blk, t, rng):
    return cc.fmt_for(t, rng, blk.prag)


def coef_q(v, w, rngmax=None):
    """fraction bits for a signed constant of width w holding |v| <= rngmax"""
    m = abs(rngmax if rngmax is not None else v)
    if m == 0:
        return w - 2
    f = w - 1 - math.ceil(math.log2(m))
    while round(m * 2 ** f) > (1 << (w - 1)) - 1:
        f -= 1
    return f


def unify(cc, b, ins):
    """inputs that a block passes through unchanged must share one format: convert the others to
    the format with the most integer bits (inserted grv_convert instances)"""
    if len({n.fmt for n in ins}) <= 1:
        return ins
    if len({(n.fmt.cplx, n.fmt.signed) for n in ins}) > 1:
        cc.diag.err('E202', f'{b.name}: inputs of different kinds ({", ".join(str(n.fmt) for n in ins)})')
    w = max(n.fmt.w for n in ins)
    ib = max(n.fmt.w - n.fmt.f for n in ins)
    tgt = ins[0].fmt.with_(w=w, f=w - ib)
    out = []
    for k, n in enumerate(ins):
        if n.fmt == tgt:
            out.append(n)
            continue
        p = dict(IW=n.fmt.w, CPLX=int(n.fmt.cplx), ISIGNED=int(n.fmt.signed), OW=tgt.w, OSIGNED=int(tgt.signed), MULK=0, KW=18, K=1,
                 SHIFT=n.fmt.f - tgt.f, ROUND=1, SAT=1, OREG=oreg(cc))
        i = mk(cc, b, 'grv_convert', p, ins=[(n, n.fmt.w)], outs=[(tgt, n.rng)], name=f'{b.name}_cv{k}')
        i.meta.update(latency=2)
        out.append(i.outs[0])
        cc.diag.note(f'{b.name}: input {k} converted from {n.fmt} to {tgt}')
    return out


def same_in_width(ins):
    return max(n.fmt.w for n in ins)


def need_cplx(cc, blk, net, want):
    if net.fmt.cplx != want:
        cc.diag.err('E201', f'{blk.name}: input is {"complex" if net.fmt.cplx else "real"}, '
                            f'expected {"complex" if want else "real"}')


def quant_taps(cc, blk, h, cw):
    hs = np.array(h, dtype=complex)
    cplx = bool(np.any(np.abs(hs.imag) > 1e-15))
    mx = float(max(np.max(np.abs(hs.real)), np.max(np.abs(hs.imag)) if cplx else 0.0))
    cf = coef_q(None, cw, mx)
    if cplx:
        q = [(int(round(x.real * 2 ** cf)), int(round(x.imag * 2 ** cf))) for x in hs]
        err = np.array([complex(a, b) for a, b in q]) / 2.0 ** cf - hs
    else:
        q = [int(round(x.real * 2 ** cf)) for x in hs]
        err = np.array(q) / 2.0 ** cf - hs.real
    sig = float(np.sum(np.abs(hs) ** 2))
    sqnr = 10 * math.log10(sig / max(float(np.sum(np.abs(err) ** 2)), 1e-300)) if sig > 0 else 0
    if sqnr < 60 and sig > 0:
        cc.diag.warn('W201', f'{blk.name}: taps quantised with SNR {sqnr:.1f} dB')
    l1 = float(np.sum(np.abs(hs.real)) + (np.sum(np.abs(hs.imag)) if cplx else 0))
    return q, cf, cplx, l1, sqnr


# ------------------------------------------------------------------ sources
@mapper('analog_sig_source_x')
def m_sig(cc, b, ins):
    t = gtype(cc, b)
    wave = WAVE[int(cc.ev(b, 'waveform', 102))]
    cplx = t == 'complex'
    if cplx and wave > 2:
        cc.diag.err('E102', f'{b.name}: complex {["const","sin","cos","square","triangle","saw"][wave]} wave is not supported')
    sr = float(cc.ev(b, 'samp_rate', 1))
    amax = max(abs(x) for x in cc.range_of(b, 'amp', 1.0)) or 1.0
    omax = max(abs(complex(x)) for x in cc.range_of(b, 'offset', 0.0))
    rng = amax + omax
    of = out_fmt(cc, b, t, rng)
    aw, ofw = cc.prof['gain'], cc.prof['gain']
    af = coef_q(None, aw, amax)
    off_f = min(coef_q(None, ofw, omax), 17 + af)
    p = rs(cc, b, dict(OW=of.w, CPLX=int(cplx), WAVE=wave, AW=aw, OFW=ofw, OFSH=17 + af - off_f,
                       PHASE0=int(round(float(cc.ev(b, 'phase', 0)) / (2 * math.pi) * 2 ** 32)) & 0xFFFFFFFF,
                       SHIFT=17 + af - of.f))
    i = mk(cc, b, 'grv_sig_source', p, outs=[(of, rng)], kind='block')
    i.extra['run'] = 'run'
    cc.cfg(i, 'cfg_freq', 32, b, 'freq', lambda v: wrap32(round(float(v) / sr * 2 ** 32)), desc='phase increment, freq / samp_rate * 2^32')
    cc.cfg(i, 'cfg_amp', aw, b, 'amp', lambda v: round(float(abs(v) if isinstance(v, complex) else v) * 2 ** af), desc=f'amplitude s{aw}.{af}')
    cc.cfg(i, 'cfg_offset', ofw, b, 'offset', lambda v: round(complex(v).real * 2 ** off_f), desc=f'offset s{ofw}.{off_f}')
    cc.cfg(i, 'cfg_offset_q', ofw, b, 'offset', lambda v: round(complex(v).imag * 2 ** off_f), desc=f'offset Q s{ofw}.{off_f}')
    anchor(cc, b, i)
    i.meta.update(latency=6, fill=0)
    i.cost.update(mult=2 if cplx else 1, bram=1, lut=150)
    return i.outs


def wrap32(v):
    v = int(v) & 0xFFFFFFFF
    return v - (1 << 32) if v >> 31 else v


def anchor(cc, b, i):
    r = b.prag.get('rate')
    if r is not None:
        rate = float(evaluate(str(r), cc.env))
        for o in i.outs:
            o.rate = rate
        i.meta['anchor'] = rate


@mapper('analog_noise_source_x', 'analog_fastnoise_source_x')
def m_noise(cc, b, ins):
    t = gtype(cc, b)
    nt = int(cc.ev(b, 'noise_type', 201))
    if nt not in (200, 201):
        cc.diag.err('E102', f'{b.name}: only uniform and Gaussian noise are supported')
    gauss = nt == 201
    amax = max(abs(x) for x in cc.range_of(b, 'amp', 1.0)) or 1.0
    scale = 1 / math.sqrt(4 / 3.0) if gauss else 1.0
    rng = amax * (4 * scale if gauss else 1.0)
    of = out_fmt(cc, b, t, rng)
    aw = cc.prof['gain']
    af = coef_q(None, aw, amax * scale)
    p = rs(cc, b, dict(OW=of.w, CPLX=int(t == 'complex'), TYPE=int(gauss), SEED=int(cc.ev(b, 'seed', 0)) & 0xFFFFFFFF,
                       AW=aw, SHIFT=17 + af - of.f))
    i = mk(cc, b, 'grv_noise_source', p, outs=[(of, rng)])
    i.extra['run'] = 'run'
    cc.cfg(i, 'cfg_amp', aw, b, 'amp', lambda v: round(float(v) * scale * 2 ** af), desc=f'amplitude s{aw}.{af}')
    anchor(cc, b, i)
    i.meta.update(latency=4, fill=0)
    i.cost.update(mult=2 if t == 'complex' else 1, lut=200)
    return i.outs


@mapper('analog_const_source_x', 'blocks_null_source')
def m_const(cc, b, ins):
    t = gtype(cc, b)
    if b.id == 'blocks_null_source':
        v = 0
        src_expr = '0'
    else:
        v = cc.ev(b, 'const', 0)
        src_expr = None
    rng = max(abs(complex(x)) for x in cc.range_of(b, 'const', 0.0)) if b.id != 'blocks_null_source' else 0
    of = out_fmt(cc, b, t, max(rng, 1e-9))
    p = rs(cc, b, dict(OW=of.w, CPLX=int(of.cplx)))
    i = mk(cc, b, 'grv_const_source', p, outs=[(of, rng)], ovf=False)
    i.extra['run'] = 'run'

    def conv(x):
        x = complex(x)
        r = round(x.real * 2 ** of.f)
        if of.cplx:
            return (to_u(round(x.imag * 2 ** of.f), of.w) << of.w) | to_u(r, of.w)
        return r
    c = cc.cfg(i, 'cfg_value', of.tw, b, 'const', conv, signed=not of.cplx, env_expr=src_expr, desc=f'value {of}')
    anchor(cc, b, i)
    return i.outs


@mapper('blocks_vector_source_x')
def m_vsrc(cc, b, ins):
    t = gtype(cc, b)
    vec = list(cc.ev(b, 'vector', [0]))
    rep = bool(cc.ev(b, 'repeat', True))
    vlen = int(cc.ev(b, 'vlen', 1))
    rng = max(abs(complex(x)) for x in vec) if vec else 0
    of = out_fmt(cc, b, t, max(rng, 1e-9))
    if len(vec) > 4096:
        cc.diag.err('E104', f'{b.name}: vector of {len(vec)} items (at most 4096)')
    from .fx import pack
    vals = []
    for x in vec:
        x = complex(x)
        r = (round(x.real * 2 ** of.f), round(x.imag * 2 ** of.f)) if of.cplx else round(x.real * 2 ** of.f)
        vals.append(pack(r, of.w, of.cplx))
    sw = of.tw
    p = dict(SW=sw, N=len(vals), VEC=(sw * len(vals), sum(v << (k * sw) for k, v in enumerate(vals))), REPEAT=int(rep),
             VLEN=vlen if vlen > 1 else 0, OREG=0 if cc.slices == 'none' else 1)
    i = mk(cc, b, 'grv_vector_rom', p, outs=[(of, rng, 1, vlen)], ovf=False)
    i.extra['run'] = 'run'
    anchor(cc, b, i)
    i.cost.update(bram=1 if sw * len(vals) > 1024 else 0, lut=40)
    return i.outs


@mapper('digital_glfsr_source_x', 'digital_glfsr_source_b', 'digital_glfsr_source_f')
def m_glfsr(cc, b, ins):
    t = cc.raw(b, 'type', 'byte')
    deg = int(cc.ev(b, 'degree', 8))
    mask = int(cc.ev(b, 'mask', 0))
    if mask == 0:
        cc.diag.err('E102', f'{b.name}: give the LFSR mask explicitly (mask 0 uses a GNU Radio table)')
    f = t == 'float'
    of = out_fmt(cc, b, 'float', 1.0) if f else Fmt(8, 0, False, False)
    p = dict(DEGREE=deg, MASK=mask, SEED=int(cc.ev(b, 'seed', 1)), REPEAT=int(bool(cc.ev(b, 'repeat', True))), OUTF=int(f),
             OW=of.w, ONE=(1 << of.f) if f else 1, OREG=0 if cc.slices == 'none' else 1)
    i = mk(cc, b, 'grv_glfsr', p, outs=[(of, 1.0)], ovf=False)
    i.extra['run'] = 'run'
    anchor(cc, b, i)
    return i.outs


# ------------------------------------------------------------------ endpoints and pads
SRC_IDS = ('blocks_file_source', 'zeromq_pull_source', 'zeromq_sub_source', 'zeromq_req_source', 'zeromq_rep_source',
           'network_udp_source', 'network_tcp_source', 'grv_axil_source')
HW_SRC = ('uhd_usrp_source', 'audio_source', 'soapy_rtlsdr_source', 'soapy_hackrf_source', 'soapy_custom_source',
          'osmosdr_source', 'iio_pluto_source')
SNK_IDS = ('blocks_vector_sink_x', 'blocks_file_sink', 'zeromq_push_sink', 'zeromq_pub_sink', 'zeromq_req_sink',
           'zeromq_rep_sink', 'network_udp_sink', 'network_tcp_sink', 'grv_axil_sink')
CAP_IDS = ('qtgui_time_sink_x', 'qtgui_const_sink_x', 'qtgui_freq_sink_x', 'qtgui_waterfall_sink_x',
           'qtgui_time_raster_sink_x', 'qtgui_histogram_sink_x', 'qtgui_vector_sink_f')
HW_SNK = ('uhd_usrp_sink', 'audio_sink', 'soapy_hackrf_sink', 'soapy_custom_sink', 'osmosdr_sink', 'iio_pluto_sink')
PROBE_IDS = ('blocks_probe_signal_x', 'blocks_probe_signal_vx', 'qtgui_number_sink', 'grv_axil_probe')


def default_rate(cc, b):
    r = b.prag.get('rate')
    if r is not None:
        return float(evaluate(str(r), cc.env))
    if 'samp_rate' in b.params and str(b.params['samp_rate']).strip():
        return float(cc.ev(b, 'samp_rate'))
    if 'samp_rate' in cc.env:
        return float(cc.env['samp_rate'])
    return None


@mapper(*SRC_IDS, *HW_SRC, 'pad_source')
def m_src(cc, b, ins):
    if b.prag.get('via') not in (None, 'axil', 'pad'):
        from .periph import via
        return via(cc, b, ins, 'src')
    t = gtype(cc, b, 'complex')
    pad = (b.id == 'pad_source' or b.id in HW_SRC) and not (b.prag.get('axil') or b.prag.get('via') == 'axil')
    if b.prag.get('pad') or b.prag.get('via') == 'pad':
        pad = True
    rng = 1.0
    of = cc.fmt_for(t, rng, b.prag)
    rng = of.maxval() if t not in INT_FMT else float(2 ** (of.w - 1))
    vlen = int(cc.ev(b, 'vlen', 1) or 1)
    if pad:
        label = cc.raw(b, 'label', b.name) if b.id == 'pad_source' else b.name
        i = mk(cc, b, 'pad_in', {}, outs=[(of, rng, 1, vlen)], kind='pad_in', ovf=False)
        i.ep = dict(label=re_id(label or b.name))
        i.model = False
    else:
        depth = int(b.prag.get('depth', cc.ev(b, 'depth', 512) or 512))
        rep = bool(cc.ev(b, 'repeat', False)) if 'repeat' in b.params else False
        i = mk(cc, b, 'grv_ep_src', dict(W=of.tw, CW=of.w, NC=of.nc, SIGNED=int(of.signed), FRAC=max(of.f, 0),
                                         DEPTH=pow2(depth), FRAME0=vlen if vlen > 1 else 0),
               outs=[(of, rng, 1, vlen)], kind='src', ovf=False)
        i.ep = dict(depth=pow2(depth), loop=rep, fmt=of)
        i.model = False
        i.cost.update(bram=bram_for(pow2(depth) * of.tw), lut=180)
    r = default_rate(cc, b)
    if r:
        for o in i.outs:
            o.rate = r
        i.meta['anchor'] = r
    return i.outs


def re_id(s):
    import re
    s = re.sub(r'[^A-Za-z0-9_]', '_', s)
    return s if not s[0].isdigit() else 'p_' + s


def pow2(n):
    return 1 << max(1, math.ceil(math.log2(max(int(n), 2))))


def bram_for(bits):
    return 0 if bits <= 1024 else math.ceil(bits / 18432)


@mapper(*SNK_IDS, *CAP_IDS, *HW_SNK, 'pad_sink', 'blocks_null_sink', *PROBE_IDS)
def m_snk(cc, b, ins):
    if b.prag.get('via') not in (None, 'axil', 'pad'):
        if len(ins) != 1:
            cc.diag.err('E609', f'{b.name}: @grv via on a sink with {len(ins)} inputs')
        from .periph import via
        return via(cc, b, ins, 'snk')
    for k, net in enumerate(ins):
        name = b.prag.get('name', b.name) + (f'_{k}' if len(ins) > 1 else '')
        if b.id == 'blocks_null_sink':
            i = mk(cc, b, 'null', {}, ins=[(net, net.fmt.w)], kind='null', ovf=False, name=name)
            i.model = False
            continue
        pad = (b.id == 'pad_sink' or b.id in HW_SNK) and not (b.prag.get('axil') or b.prag.get('via') == 'axil')
        if b.prag.get('pad') or b.prag.get('via') == 'pad':
            pad = True
        if pad:
            label = cc.raw(b, 'label', b.name) if b.id == 'pad_sink' else b.name
            i = mk(cc, b, 'pad_out', {}, ins=[(net, net.fmt.w)], kind='pad_out', ovf=False, name=name)
            i.ep = dict(label=re_id((label or b.name) + (f'_{k}' if len(ins) > 1 else '')))
            i.model = False
            continue
        mode = b.prag.get('mode') or (cc.raw(b, 'mode', '').strip('"\' ') if b.id.startswith('grv_') else '') or None
        if b.id in PROBE_IDS or mode == 'probe':
            i = mk(cc, b, 'probe', {}, ins=[(net, net.fmt.w)], kind='probe', ovf=False, name=name)
            i.ep = dict(fmt=net.fmt)
            i.model = False
            continue
        cap = (b.id in CAP_IDS and mode != 'stream') or mode == 'capture'
        drop = b.id.startswith(('zeromq', 'network')) or mode == 'drop'
        depth = pow2(int(b.prag.get('depth', cc.ev(b, 'depth', 512) or 512)))
        capd, caplen = 0, 0
        if cap:
            n = None
            for key in ('size', 'fftsize', 'npoints', 'vlen'):
                if key in b.params and str(b.params[key]).strip():
                    try:
                        n = int(cc.ev(b, key))
                        break
                    except Exception:
                        pass
            caplen = int(b.prag.get('caplen', cc.ev(b, 'caplen', 0) or n or 1024))
            capd = pow2(caplen)
        f = net.fmt
        i = mk(cc, b, 'grv_ep_snk', dict(W=f.tw, CW=f.w, NC=f.nc, SIGNED=int(f.signed), FRAC=max(f.f, 0), DEPTH=depth,
                                         CAPD=capd, MODE0=1 if cap else 0, CAPLEN0=caplen),
               ins=[(net, f.w)], kind='snk', ovf=False, name=name)
        i.ep = dict(depth=depth, capd=capd, caplen=caplen, drop=drop, fmt=f, mode='capture' if cap else ('drop' if drop else 'stream'))
        i.model = False
        i.cost.update(bram=bram_for(depth * f.tw) + bram_for(capd * (f.tw + 1)), lut=550 + (450 if capd else 0))
    return []


# ------------------------------------------------------------------ math
def align(ins):
    wf = max(n.fmt.f for n in ins)
    return wf, [wf - n.fmt.f for n in ins]


@mapper('blocks_add_xx', 'blocks_sub_xx', 'blocks_add_ff', 'blocks_add_cc', 'blocks_sub_ff', 'blocks_sub_cc')
def m_add(cc, b, ins):
    t = gtype(cc, b)
    ni = len(ins)
    cplx = ins[0].fmt.cplx
    if t in INT_FMT:
        of = INT_FMT[t]
        wf, sh = 0, [0] * ni
        rng = sum(n.rng for n in ins)
    else:
        wf, sh = align(ins)
        rng = sum(n.rng for n in ins)
        of = out_fmt(cc, b, t, rng)
    iw = max(n.fmt.w + s for n, s in zip(ins, sh)) - max(sh) if False else max(n.fmt.w for n in ins)
    p = rs(cc, b, dict(NI=ni, IW=iw, CPLX=int(cplx), OW=of.w, SHIFT_IN=(6 * ni, sum(s << (6 * k) for k, s in enumerate(sh))),
                       SUB=int('sub' in b.id), SHIFT=wf - of.f))
    if t in INT_FMT:
        p['SAT'] = 0
    i = mk(cc, b, 'grv_add', p, ins=[(n, iw) for n in ins], outs=[(of, rng)])
    i.meta.update(latency=3)
    i.cost.update(lut=(iw + 2) * ni * (2 if cplx else 1))
    return i.outs


@mapper('blocks_multiply_xx', 'blocks_multiply_conjugate_cc', 'blocks_multiply_ff', 'blocks_multiply_cc')
def m_mult(cc, b, ins):
    if len(ins) != 2:
        cc.diag.err('E102', f'{b.name}: multiply with {len(ins)} inputs (OpenGRV supports 2)')
    t = 'complex' if 'conjugate' in b.id else gtype(cc, b)
    cplx = ins[0].fmt.cplx
    rng = ins[0].rng * ins[1].rng * (2 if cplx else 1)
    of = INT_FMT[t] if t in INT_FMT else out_fmt(cc, b, t, rng)
    iw = max(n.fmt.w for n in ins)
    p = rs(cc, b, dict(IW=iw, CPLX=int(cplx), CONJ=int('conjugate' in b.id), OW=of.w, SHIFT=ins[0].fmt.f + ins[1].fmt.f - of.f))
    if t in INT_FMT:
        p['SAT'] = 0
    i = mk(cc, b, 'grv_multiply', p, ins=[(n, iw) for n in ins], outs=[(of, rng)])
    i.meta.update(latency=4)
    i.cost.update(mult=4 if cplx else 1, lut=4 * iw if cplx else 0)
    return i.outs


@mapper('blocks_multiply_const_xx', 'blocks_multiply_const_vxx', 'blocks_multiply_const_ff', 'blocks_multiply_const_cc')
def m_mconst(cc, b, ins):
    t = gtype(cc, b)
    x = ins[0]
    kv = cc.ev(b, 'const', 1)
    if isinstance(kv, (list, tuple)):
        if len(kv) != 1:
            cc.diag.err('E102', f'{b.name}: vector constant (vlen > 1) is not supported')
        b.params['const'] = f'({b.params["const"]})[0]'
        kv = kv[0]
    kc = isinstance(kv, complex) and t == 'complex' and abs(kv.imag) > 0
    kr = cc.range_of(b, 'const', 1.0)
    kmax = max(abs(v) for v in kr)
    kw = cc.prof['gain']
    kf = coef_q(None, kw, kmax * (1 if not kc else 1))
    rng = x.rng * kmax * (2 if kc and x.fmt.cplx else 1)
    of = INT_FMT[t] if t in INT_FMT else out_fmt(cc, b, t, rng)
    p = rs(cc, b, dict(IW=x.fmt.w, ICPLX=int(x.fmt.cplx), KW=kw, KCPLX=int(kc), OW=of.w, SHIFT=x.fmt.f + kf - of.f))
    if t in INT_FMT:
        p['SAT'] = 0
    i = mk(cc, b, 'grv_multiply_const', p, ins=[(x, x.fmt.w)], outs=[(of.with_(cplx=x.fmt.cplx or kc), rng)])

    def conv(v):
        v = complex(v[0] if isinstance(v, (list, tuple)) else v)
        r = round(v.real * 2 ** kf)
        if kc:
            return (to_u(round(v.imag * 2 ** kf), kw) << kw) | to_u(r, kw)
        return r
    c = cc.cfg(i, 'cfg_k', kw * (2 if kc else 1), b, 'const', conv, signed=not kc, desc=f'constant s{kw}.{kf}')
    c.model = (lambda u: (wrap_s(u & ((1 << kw) - 1), kw), wrap_s(u >> kw, kw))) if kc else None
    i.meta.update(latency=4)
    i.cost.update(mult=4 if (kc and x.fmt.cplx) else (2 if (kc or x.fmt.cplx) else 1))
    return i.outs


def wrap_s(v, w):
    v &= (1 << w) - 1
    return v - (1 << w) if v >> (w - 1) else v


@mapper('blocks_add_const_vxx', 'blocks_add_const_xx', 'blocks_add_const_ff', 'blocks_add_const_cc')
def m_aconst(cc, b, ins):
    t = gtype(cc, b)
    x = ins[0]
    kv = cc.ev(b, 'const', 0)
    if isinstance(kv, (list, tuple)):
        b.params['const'] = f'({b.params["const"]})[0]'
    kmax = max(abs(v) for v in cc.range_of(b, 'const', 0.0))
    kw = cc.prof['gain'] if t not in INT_FMT else x.fmt.w
    kf = coef_q(None, kw, kmax) if t not in INT_FMT else 0
    wf = max(x.fmt.f, kf)
    rng = x.rng + kmax
    of = INT_FMT[t] if t in INT_FMT else out_fmt(cc, b, t, rng)
    p = rs(cc, b, dict(IW=x.fmt.w, CPLX=int(x.fmt.cplx), KW=kw, XSH=wf - x.fmt.f, KSH=wf - kf, OW=of.w, SHIFT=wf - of.f))
    if t in INT_FMT:
        p['SAT'] = 0
    i = mk(cc, b, 'grv_add_const', p, ins=[(x, x.fmt.w)], outs=[(of, rng)])
    cplx = x.fmt.cplx

    def conv(v):
        v = complex(v[0] if isinstance(v, (list, tuple)) else v)
        r = round(v.real * 2 ** kf)
        if cplx:
            return (to_u(round(v.imag * 2 ** kf), kw) << kw) | to_u(r, kw)
        return r
    c = cc.cfg(i, 'cfg_k', kw * (2 if cplx else 1), b, 'const', conv, signed=not cplx, desc=f'constant s{kw}.{kf}')
    c.model = (lambda u: (wrap_s(u & ((1 << kw) - 1), kw), wrap_s(u >> kw, kw))) if cplx else None
    return i.outs


def elem(cc, b, ins, op, t_out, rng, of=None, shift=None):
    x = ins[0]
    of = of or out_fmt(cc, b, t_out, rng)
    p = rs(cc, b, dict(OP=op, IW=x.fmt.w, CPLX=int(x.fmt.cplx), OW=of.w, SHIFT=shift if shift is not None else x.fmt.f - of.f))
    i = mk(cc, b, 'grv_elem', p, ins=[(x, x.fmt.w)], outs=[(of, rng)])
    i.meta.update(latency=4)
    return i


@mapper('blocks_conjugate_cc')
def m_conj(cc, b, ins):
    x = ins[0]
    i = elem(cc, b, ins, 0, 'complex', x.rng, of=x.fmt, shift=0)
    i.params['SAT'] = 2
    return i.outs


@mapper('blocks_abs_xx', 'blocks_abs_ff')
def m_abs(cc, b, ins):
    x = ins[0]
    t = gtype(cc, b)
    i = elem(cc, b, ins, 1, t, x.rng, of=x.fmt, shift=0)
    return i.outs


@mapper('blocks_complex_to_mag_squared')
def m_mag2(cc, b, ins):
    x = ins[0]
    need_cplx(cc, b, x, True)
    rng = 2 * x.rng ** 2
    of = out_fmt(cc, b, 'float', rng)
    i = elem(cc, b, ins, 2, 'float', rng, of=of, shift=2 * x.fmt.f - of.f)
    i.cost.update(mult=2)
    return i.outs


def cordic_vec(cc, b, x, outsel, pre=False, gain=1.0, rng_arg=None):
    iw = x.fmt.w
    pw = iw + 2 if pre else iw
    psh = (2 * iw + 1 - pw) if pre else 0
    it = min(pw + 2, 24)
    kinv = int(round(2 ** 17 / cordic_gain(it)))
    zb, cw = 24, 20
    cmag = abs(gain * 2 * math.pi)
    cf = (cw - 2) - math.ceil(math.log2(cmag)) if cmag > 0 else cw - 2
    cconst = int(round(gain * 2 * math.pi * 2 ** cf))
    mag_rng = math.sqrt(2) * x.rng
    arg_rng = rng_arg if rng_arg is not None else abs(gain) * math.pi
    om = out_fmt(cc, b, 'float', mag_rng)
    oa = out_fmt(cc, b, 'float', arg_rng)
    ow = om.w
    p = rs(cc, b, dict(IW=iw, PRE=int(pre), PW=pw, PSH=psh, ITER=it, PIPE=1, OUTSEL=outsel, KW=18, KINV=kinv,
                       MSHIFT=x.fmt.f + 17 - om.f, ZB=zb, CW=cw, C=cconst, ASHIFT=zb + cf - oa.f, OW=ow))
    outs = []
    if outsel in (0, 2):
        outs.append((om, mag_rng))
    if outsel in (1, 2):
        outs.append((oa, arg_rng))
    i = mk(cc, b, 'grv_cordic_vec', p, ins=[(x, iw)], outs=outs)
    i.meta.update(latency=it + 5)
    i.cost.update(mult=2 + (4 if pre else 0), lut=3 * (pw + 3) * it)
    return i


@mapper('blocks_complex_to_mag')
def m_cmag(cc, b, ins):
    need_cplx(cc, b, ins[0], True)
    return cordic_vec(cc, b, ins[0], 0).outs


@mapper('blocks_complex_to_arg')
def m_carg(cc, b, ins):
    need_cplx(cc, b, ins[0], True)
    return cordic_vec(cc, b, ins[0], 1).outs


@mapper('blocks_complex_to_magphase')
def m_cmagph(cc, b, ins):
    need_cplx(cc, b, ins[0], True)
    return cordic_vec(cc, b, ins[0], 2).outs


@mapper('analog_quadrature_demod_cf')
def m_qdemod(cc, b, ins):
    x = ins[0]
    need_cplx(cc, b, x, True)
    g = float(cc.ev(b, 'gain', 1.0))
    if cc.deps(b, 'gain'):
        cc.diag.warn('W103', f'{b.name}: gain depends on a runtime variable; its default value is built in')
    r = b.prag.get('range')
    rng = float(evaluate(str(r), cc.env)) if r is not None else abs(g) * math.pi
    if r is None and abs(g) * math.pi > 4:
        cc.diag.warn('W301', f'{b.name}: worst-case range {abs(g) * math.pi:.1f} costs integer bits; consider @grv range')
    i = cordic_vec(cc, b, x, 1, pre=True, gain=g, rng_arg=rng)
    return i.outs


@finalize('grv_cordic_vec')
def f_cordic(cc, i):
    p = i.params
    # folded: one CORDIC stage, so a wide datapath is cheap; with PRE the conjugate product keeps
    # (almost) all its bits, which matters for the quadrature demodulator at low signal levels
    wide_pw = min(2 * p['IW'], 32) if p['PRE'] else p['PW']
    wide_it = min(wide_pw + 2, 24)
    need = wide_it + 6
    if cc.fold != 'off' and i.known_rate and i.budget_in >= need and not i.blk.prag.get('ii'):
        if p['PRE']:
            p['PW'], p['PSH'], p['ITER'] = wide_pw, 2 * p['IW'] + 1 - wide_pw, wide_it
            p['KINV'] = int(round(2 ** 17 / cordic_gain(wide_it)))
        i.params['PIPE'] = 0
        i.meta['ii'] = need
        i.cost['lut'] = 35 * (i.params['PW'] + 3) + 150
    else:
        i.params['PIPE'] = 1


@mapper('blocks_max_xx', 'blocks_min_xx', 'blocks_max_ff', 'blocks_min_ff')
def m_minmax(cc, b, ins):
    ins = unify(cc, b, ins)
    if int(cc.ev(b, 'vlen', 1) or 1) > 1:
        cc.diag.err('E102', f'{b.name}: vlen > 1 (reduction over a vector) is not supported')
    x = ins[0]
    i = mk(cc, b, 'grv_minmax', dict(NI=len(ins), IW=x.fmt.w, MAX=int('max' in b.id), OREG=0 if cc.slices == 'none' else 1),
           ins=[(n, x.fmt.w) for n in ins], outs=[(x.fmt, max(n.rng for n in ins))], ovf=False)
    return i.outs


@mapper('blocks_and_xx', 'blocks_or_xx', 'blocks_xor_xx', 'blocks_not_xx', 'blocks_and_const_xx')
def m_logic(cc, b, ins):
    op = {'blocks_and_xx': 0, 'blocks_or_xx': 1, 'blocks_xor_xx': 2, 'blocks_not_xx': 3, 'blocks_and_const_xx': 4}[b.id]
    w = max(n.fmt.w for n in ins)
    i = mk(cc, b, 'grv_logic', dict(NI=len(ins), W=w, OP=op, OREG=0 if cc.slices == 'none' else 1),
           ins=[(n, w) for n in ins], outs=[(ins[0].fmt, ins[0].rng)], ovf=False)
    cc.cfg(i, 'cfg_k', w, b, 'const' if op == 4 else '__none__', lambda v: int(v) & ((1 << w) - 1), signed=False,
           env_expr=None if op == 4 else '0')
    return i.outs


@mapper('blocks_threshold_ff')
def m_thr(cc, b, ins):
    x = ins[0]
    of = out_fmt(cc, b, 'float', 1.0)
    i = mk(cc, b, 'grv_threshold', dict(IW=x.fmt.w, OW=of.w, ONE=1 << of.f, INIT=int(bool(cc.ev(b, 'init', 0))),
                                        OREG=0 if cc.slices == 'none' else 1),
           ins=[(x, x.fmt.w)], outs=[(of, 1.0)], ovf=False)
    q = lambda v: max(-(1 << (x.fmt.w - 1)), min((1 << (x.fmt.w - 1)) - 1, round(float(v) * 2 ** x.fmt.f)))
    cc.cfg(i, 'cfg_lo', x.fmt.w, b, 'low', q, desc=f'low threshold {x.fmt}')
    cc.cfg(i, 'cfg_hi', x.fmt.w, b, 'high', q, desc=f'high threshold {x.fmt}')
    return i.outs


# ------------------------------------------------------------------ type conversion
@mapper('blocks_complex_to_real', 'blocks_complex_to_imag', 'blocks_complex_to_float')
def m_csplit(cc, b, ins):
    x = ins[0]
    need_cplx(cc, b, x, True)
    mode = {'blocks_complex_to_real': 0, 'blocks_complex_to_imag': 1, 'blocks_complex_to_float': 2}[b.id]
    f = x.fmt.with_(cplx=False)
    outs = [(f, x.rng)] * (2 if mode == 2 else 1)
    i = mk(cc, b, 'grv_complex_split', dict(IW=x.fmt.w, MODE=mode, OREG=0 if cc.slices == 'none' else 1),
           ins=[(x, x.fmt.w)], outs=outs, ovf=False)
    return i.outs


@mapper('blocks_float_to_complex')
def m_f2c(cc, b, ins):
    wf, sh = align(ins)
    rng = max(n.rng for n in ins)
    of = out_fmt(cc, b, 'complex', rng)
    iw = max(n.fmt.w for n in ins)
    p = rs(cc, b, dict(NI=len(ins), IW=iw, SH0=sh[0], SH1=sh[1] if len(ins) > 1 else 0, OW=of.w, SHIFT=wf - of.f))
    i = mk(cc, b, 'grv_float_to_complex', p, ins=[(n, iw) for n in ins], outs=[(of, rng)])
    return i.outs


CONV_OUT = {'blocks_float_to_short': Fmt(16, 0), 'blocks_float_to_char': Fmt(8, 0), 'blocks_float_to_int': Fmt(32, 0),
            'blocks_float_to_uchar': Fmt(8, 0, False, False)}
CONV_IN = {'blocks_short_to_float': 16, 'blocks_char_to_float': 8, 'blocks_int_to_float': 32, 'blocks_uchar_to_float': 8}


def is_pow2(v):
    return v > 0 and abs(math.log2(v) - round(math.log2(v))) < 1e-12


@mapper(*CONV_OUT, *CONV_IN, 'blocks_short_to_char', 'blocks_char_to_short', 'grv_quantize')
def m_conv(cc, b, ins):
    x = ins[0]
    scale = float(cc.ev(b, 'scale', 1.0) or 1.0)
    p = dict(IW=x.fmt.w, CPLX=int(x.fmt.cplx), ISIGNED=int(x.fmt.signed), MULK=0, KW=18, K=1, ROUND=3, SAT=1)
    if b.id in CONV_OUT:
        of = CONV_OUT[b.id]
        if is_pow2(scale):
            p['SHIFT'] = x.fmt.f - int(round(math.log2(scale)))
        else:
            kf = coef_q(None, 18, scale)
            p.update(MULK=1, K=int(round(scale * 2 ** kf)), SHIFT=x.fmt.f + kf)
        rng = float(2 ** (of.w - 1))
    elif b.id in CONV_IN:
        uns = b.id == 'blocks_uchar_to_float'
        rng = (2 ** (x.fmt.w - (0 if uns else 1))) / scale
        of = out_fmt(cc, b, 'float', rng)
        if is_pow2(scale):
            p['SHIFT'] = x.fmt.f + int(round(math.log2(scale))) - of.f
        else:
            kf = coef_q(None, 18, 1 / scale)
            p.update(MULK=1, K=int(round(2 ** kf / scale)), SHIFT=x.fmt.f + kf - of.f)
        p['ROUND'] = 1
    elif b.id == 'blocks_short_to_char':
        of, rng = Fmt(8, 0), 128.0
        p.update(SHIFT=8, ROUND=0, SAT=0)
    elif b.id == 'blocks_char_to_short':
        of, rng = Fmt(16, 0), 32768.0
        p.update(SHIFT=-8, ROUND=0, SAT=0)
    else:                                   # grv_quantize
        of = cc.fmt_for('complex' if x.fmt.cplx else 'float', x.rng, b.prag).with_(cplx=x.fmt.cplx)
        rng = min(x.rng, of.maxval())
        p.update(SHIFT=x.fmt.f - of.f, ROUND=1)
    p.update(OW=of.w, OSIGNED=int(of.signed), OREG=0 if cc.slices == 'none' else 1)
    p['ROUND'] = int(b.prag.get('round', p['ROUND']))
    i = mk(cc, b, 'grv_convert', p, ins=[(x, x.fmt.w)], outs=[(of.with_(cplx=x.fmt.cplx), rng)])
    return i.outs


@mapper('blocks_complex_to_interleaved_short', 'blocks_complex_to_interleaved_char')
def m_iiq(cc, b, ins):
    x = ins[0]
    scale = float(cc.ev(b, 'scale_factor', 1.0) or 1.0)
    if not is_pow2(scale):
        cc.diag.err('E102', f'{b.name}: scale factor must be a power of two')
    of = Fmt(16 if 'short' in b.id else 8, 0)
    vec = bool(cc.ev(b, 'vector', False))
    i = mk(cc, b, 'grv_interleave_iq', dict(IW=x.fmt.w, OW=of.w, SHIFT=x.fmt.f - int(round(math.log2(scale))), ROUND=3, SAT=1,
                                             VEC=int(vec), OREG=0 if cc.slices == 'none' else 1),
           ins=[(x, x.fmt.w)], outs=[(of, 2.0 ** (of.w - 1), 2, 2 if vec else 1)])
    return i.outs


@mapper('blocks_interleaved_short_to_complex', 'blocks_interleaved_char_to_complex')
def m_diq(cc, b, ins):
    x = ins[0]
    scale = float(cc.ev(b, 'scale_factor', 1.0) or 1.0)
    if not is_pow2(scale):
        cc.diag.err('E102', f'{b.name}: scale factor must be a power of two')
    rng = 2.0 ** (x.fmt.w - 1) / scale
    of = out_fmt(cc, b, 'complex', rng)
    i = mk(cc, b, 'grv_deinterleave_iq', rs(cc, b, dict(IW=x.fmt.w, OW=of.w, SWAP=int(bool(cc.ev(b, 'swap', False))),
                                                        SHIFT=x.fmt.f + int(round(math.log2(scale))) - of.f)),
           ins=[(x, x.fmt.w)], outs=[(of, rng, Fraction(1, 2))])
    return i.outs


# ------------------------------------------------------------------ stream operations
def oreg(cc):
    return 0 if cc.slices == 'none' else 1


@mapper('blocks_delay')
def m_delay(cc, b, ins):
    x = ins[0]
    if cc.deps(b, 'delay'):
        cc.diag.err('E401', f'{b.name}: runtime delay is not supported yet')
    d = int(cc.ev(b, 'delay', 0))
    i = mk(cc, b, 'grv_delay', dict(W=x.fmt.tw, DELAY=d, OREG=oreg(cc)), ins=[(x, x.fmt.tw)], outs=[(x.fmt, x.rng)], ovf=False)
    i.raw_in = True
    i.cost.update(bram=bram_for(d * (x.fmt.tw + 1)) if d > 64 else 0, lut=40)
    i.meta.update(cap=d + 2)
    return i.outs


def sel_stream(cc, b, ins, mode, ratio, **kw):
    x = ins[0]
    p = dict(W=x.fmt.tw, MODE=mode, OREG=oreg(cc))
    p.update(kw)
    i = mk(cc, b, 'grv_select_stream', p, ins=[(x, x.fmt.tw)], outs=[(x.fmt, x.rng, ratio)], ovf=False)
    i.raw_in = True
    return i


@mapper('blocks_head')
def m_head(cc, b, ins):
    i = sel_stream(cc, b, ins, 0, 1, N=int(cc.ev(b, 'num_items', 1024)))
    i.extra.update(cfg_n="32'd0", cfg_en="1'b1")
    return i.outs


@mapper('blocks_skiphead')
def m_skiphead(cc, b, ins):
    i = sel_stream(cc, b, ins, 1, 1, N=int(cc.ev(b, 'num_items', 0)))
    i.extra.update(cfg_n="32'd0", cfg_en="1'b1")
    return i.outs


@mapper('blocks_keep_one_in_n')
def m_k1n(cc, b, ins):
    n = int(cc.ev(b, 'n', 1))
    i = sel_stream(cc, b, ins, 2, Fraction(1, n))
    cc.cfg(i, 'cfg_n', 32, b, 'n', lambda v: int(v), signed=False, desc='n')
    i.extra['cfg_en'] = "1'b1"
    i.meta.update(fill=n)
    return i.outs


@mapper('blocks_keep_m_in_n')
def m_kmn(cc, b, ins):
    m, n, off = int(cc.ev(b, 'm', 1)), int(cc.ev(b, 'n', 2)), int(cc.ev(b, 'offset', 0))
    i = sel_stream(cc, b, ins, 3, Fraction(m, n), M=m, N=n, OFFSET=off)
    i.extra.update(cfg_n="32'd0", cfg_en="1'b1")
    i.meta.update(fill=n)
    return i.outs


@mapper('blocks_copy')
def m_copy(cc, b, ins):
    i = sel_stream(cc, b, ins, 4, 1)
    cc.cfg(i, 'cfg_en', 1, b, 'enabled', lambda v: int(bool(v)), signed=False, desc='enabled')
    i.extra['cfg_n'] = "32'd0"
    return i.outs


@mapper('blocks_repeat')
def m_repeat(cc, b, ins):
    x = ins[0]
    n = int(cc.ev(b, 'interp', 2))
    i = mk(cc, b, 'grv_repeat', dict(W=x.fmt.tw, N=n, OREG=oreg(cc)), ins=[(x, x.fmt.tw)], outs=[(x.fmt, x.rng, n)], ovf=False)
    i.raw_in = True
    return i.outs


@mapper('blocks_stream_mux', 'blocks_interleave')
def m_smux(cc, b, ins):
    ins = unify(cc, b, ins)
    x = ins[0]
    if b.id == 'blocks_interleave':
        lens = [int(cc.ev(b, 'blocksize', 1))] * len(ins)
    else:
        lens = [int(v) for v in cc.ev(b, 'lengths', [1] * len(ins))]
    tot = sum(lens)
    i = mk(cc, b, 'grv_stream_mux', dict(NI=len(ins), W=x.fmt.tw, LENS=(32 * len(ins), sum(l << (32 * k) for k, l in enumerate(lens))),
                                         OREG=oreg(cc)),
           ins=[(n, x.fmt.tw) for n in ins], outs=[(x.fmt, max(n.rng for n in ins), Fraction(tot, max(lens[0], 1)))], ovf=False)
    i.raw_in = True
    i.meta['multirate'] = True
    i.outs[0].ratio = Fraction(1)
    return i.outs


@mapper('blocks_deinterleave')
def m_deint(cc, b, ins):
    x = ins[0]
    no = int(cc.ev(b, 'num_streams', 2))
    bs = int(cc.ev(b, 'blocksize', 1))
    i = mk(cc, b, 'grv_demux', dict(MODE=0, NI=1, NO=no, W=x.fmt.tw, BS=bs), ins=[(x, x.fmt.tw)],
           outs=[(x.fmt, x.rng, Fraction(1, no))] * no, ovf=False)
    i.raw_in = True
    i.extra.update(cfg_in="8'd0", cfg_out="8'd0", cfg_en="1'b1")
    return i.outs


@mapper('blocks_selector')
def m_selector(cc, b, ins):
    ins = unify(cc, b, ins)
    x = ins[0]
    no = int(cc.ev(b, 'num_outputs', 1))
    i = mk(cc, b, 'grv_demux', dict(MODE=1, NI=len(ins), NO=no, W=x.fmt.tw, BS=1), ins=[(n, x.fmt.tw) for n in ins],
           outs=[(x.fmt, x.rng)] * no, ovf=False)
    i.raw_in = True
    cc.cfg(i, 'cfg_in', 8, b, 'input_index', lambda v: int(v), signed=False, desc='input index')
    cc.cfg(i, 'cfg_out', 8, b, 'output_index', lambda v: int(v), signed=False, desc='output index')
    cc.cfg(i, 'cfg_en', 1, b, 'enabled', lambda v: int(bool(v)), signed=False, desc='enabled', default=1)
    return i.outs


@mapper('blocks_stream_to_vector', 'blocks_vector_to_stream')
def m_vmark(cc, b, ins):
    x = ins[0]
    n = int(cc.ev(b, 'num_items', 1))
    i = mk(cc, b, 'grv_vector_mark', dict(W=x.fmt.tw, MODE=0 if 'stream_to_vector' in b.id else 1, VLEN=n, OREG=oreg(cc)),
           ins=[(x, x.fmt.tw)], outs=[(x.fmt, x.rng, 1, n if 'stream_to_vector' in b.id else 1)], ovf=False)
    i.raw_in = True
    return i.outs


@mapper('blocks_throttle', 'blocks_throttle2')
def m_throttle(cc, b, ins):
    x = ins[0]
    sps = float(cc.ev(b, 'samples_per_second', 1e6))
    inc = min(int(round(sps / cc.clk * 2 ** 32)), 0xFFFFFFFF)
    i = mk(cc, b, 'grv_throttle', dict(W=x.fmt.tw, OREG=oreg(cc)), ins=[(x, x.fmt.tw)], outs=[(x.fmt, x.rng)], ovf=False)
    i.raw_in = True
    i.extra['cfg_inc'] = f"32'd{inc}"
    i.outs[0].rate = sps
    i.meta['anchor'] = sps
    return i.outs


@mapper('blocks_moving_average_xx', 'blocks_moving_average_ff', 'blocks_moving_average_cc')
def m_mavg(cc, b, ins):
    x = ins[0]
    t = gtype(cc, b)
    n = int(cc.ev(b, 'length', 16))
    sc = float(complex(cc.ev(b, 'scale', 1.0)).real)
    kw = 18
    kf = coef_q(None, kw, abs(sc))
    rng = x.rng * n * abs(sc)
    of = INT_FMT[t] if t in INT_FMT else out_fmt(cc, b, t, rng)
    p = rs(cc, b, dict(IW=x.fmt.w, CPLX=int(x.fmt.cplx), LEN=n, KW=kw, K=int(round(sc * 2 ** kf)), OW=of.w, SHIFT=x.fmt.f + kf - of.f))
    i = mk(cc, b, 'grv_moving_average', p, ins=[(x, x.fmt.w)], outs=[(of, rng)])
    i.cost.update(mult=2 if x.fmt.cplx else 1, bram=bram_for(n * x.fmt.tw))
    return i.outs


@mapper('blocks_integrate_xx', 'blocks_integrate_ff', 'blocks_integrate_cc')
def m_integ(cc, b, ins):
    x = ins[0]
    t = gtype(cc, b)
    d = int(cc.ev(b, 'decim', 1))
    rng = x.rng * d
    of = INT_FMT[t] if t in INT_FMT else out_fmt(cc, b, t, rng)
    p = rs(cc, b, dict(IW=x.fmt.w, CPLX=int(x.fmt.cplx), D=d, OW=of.w, SHIFT=x.fmt.f - of.f))
    i = mk(cc, b, 'grv_integrate', p, ins=[(x, x.fmt.w)], outs=[(of, rng, Fraction(1, d))])
    i.meta.update(fill=d)
    return i.outs


# ------------------------------------------------------------------ filters
def fir_types(code):
    """'ccf' -> (in complex, out complex, taps complex)"""
    return code[0] == 'c', code[1] == 'c', code[2] == 'c'


def design_resampler(interp, decim, fbw):
    if fbw <= 0 or fbw >= 0.5:
        fbw = 0.4
    beta, half = 7.0, 0.5
    rate = interp / decim
    if rate >= 1.0:
        tw = half - fbw
        mid = half - tw / 2.0
    else:
        tw = rate * (half - fbw)
        mid = rate * half - tw / 2.0
    from .firdes import firdes
    return firdes.low_pass(interp, interp, mid, tw, 4, beta)


def fir_taps(cc, b):
    """(taps, L, M, type code) of any FIR-like GRC block"""
    from .firdes import firdes
    bid = b.id
    if bid in ('fir_filter_xxx', 'interp_fir_filter_xxx', 'rational_resampler_xxx'):
        code = cc.raw(b, 'type', 'fff')
        if cc.deps(b, 'taps'):
            cc.diag.err('E401', f'{b.name}: taps depend on a runtime variable (reloadable taps are not supported yet)')
        taps = list(cc.ev(b, 'taps', [1.0]) or [])
        if bid == 'fir_filter_xxx':
            return taps, 1, int(cc.ev(b, 'decim', 1)), code
        if bid == 'interp_fir_filter_xxx':
            return taps, int(cc.ev(b, 'interp', 1)), 1, code
        L, M = int(cc.ev(b, 'interp', 1)), int(cc.ev(b, 'decim', 1))
        g = math.gcd(L, M)
        L, M = L // g, M // g
        if not taps:
            taps = design_resampler(L, M, float(cc.ev(b, 'fbw', 0.4) or 0.4))
        return taps, L, M, code
    t = cc.raw(b, 'type', 'fir_filter_fff')
    code = t[-3:]
    interp = t.startswith('interp')
    L = int(cc.ev(b, 'interp', 1)) if interp else 1
    M = 1 if interp else int(cc.ev(b, 'decim', 1))
    gain, fs = float(cc.ev(b, 'gain', 1)), float(cc.ev(b, 'samp_rate', 1))
    win, beta = int(cc.ev(b, 'win', 0)), float(cc.ev(b, 'beta', 6.76))
    for k in ('cutoff_freq', 'low_cutoff_freq', 'high_cutoff_freq', 'width', 'gain'):
        if k in b.params and cc.deps(b, k):
            cc.diag.err('E401', f'{b.name}: {k} depends on a runtime variable (reloadable taps are not supported yet)')
    if bid == 'low_pass_filter':
        taps = firdes.low_pass(gain, fs, float(cc.ev(b, 'cutoff_freq')), float(cc.ev(b, 'width')), win, beta)
    elif bid == 'high_pass_filter':
        taps = firdes.high_pass(gain, fs, float(cc.ev(b, 'cutoff_freq')), float(cc.ev(b, 'width')), win, beta)
    elif bid == 'band_pass_filter':
        f = firdes.complex_band_pass if code[2] == 'c' else firdes.band_pass
        taps = f(gain, fs, float(cc.ev(b, 'low_cutoff_freq')), float(cc.ev(b, 'high_cutoff_freq')), float(cc.ev(b, 'width')), win, beta)
    elif bid == 'band_reject_filter':
        taps = firdes.band_reject(gain, fs, float(cc.ev(b, 'low_cutoff_freq')), float(cc.ev(b, 'high_cutoff_freq')), float(cc.ev(b, 'width')), win, beta)
    else:
        taps = firdes.root_raised_cosine(gain, fs, float(cc.ev(b, 'sym_rate')), float(cc.ev(b, 'alpha')), int(cc.ev(b, 'ntaps')))
    return taps, L, M, code


def fir_inst(cc, b, x, taps, L, M, ocplx_want, module='grv_fir', extra=None, name=None):
    cw = int(b.prag.get('coef', cc.prof['coef']))
    q, cf, cc_, l1, sqnr = quant_taps(cc, b, taps, cw)
    n = len(q)
    sym = int(L == 1 and n > 1 and all(q[k] == q[n - 1 - k] for k in range(n // 2)))
    rng = x.rng * l1
    oc = x.fmt.cplx or cc_
    t = 'complex' if oc else 'float'
    of = out_fmt(cc, b, t, rng)
    p = dict(IW=x.fmt.w, ICPLX=int(x.fmt.cplx), CW=cw, CCPLX=int(cc_), NTAPS=n, COEFS=pack_taps(q, cw, cc_),
             L=L, M=M, LANES=0, SYM=sym, OW=of.w, SHIFT=x.fmt.f + cf - of.f)
    if extra:
        p.update(extra)
    rs(cc, b, p)
    i = mk(cc, b, module, p, ins=[(x, x.fmt.w)], outs=[(of, rng, Fraction(L, M))], name=name)
    i.taps = dict(n=n, cf=cf, cplx=cc_, l1=l1, sqnr=sqnr, sym=sym)
    i.meta.update(fill=max(1, M // max(L, 1)))
    return i


@mapper('fir_filter_xxx', 'interp_fir_filter_xxx', 'rational_resampler_xxx', 'low_pass_filter', 'high_pass_filter',
        'band_pass_filter', 'band_reject_filter', 'root_raised_cosine_filter')
def m_fir(cc, b, ins):
    taps, L, M, code = fir_taps(cc, b)
    x = ins[0]
    ic, oc, tc = fir_types(code)
    if x.fmt.cplx != ic:
        need_cplx(cc, b, x, ic)
    i = fir_inst(cc, b, x, taps, L, M, oc)
    return i.outs


@mapper('freq_xlating_fir_filter_xxx', 'freq_xlating_fir_filter_ccc', 'freq_xlating_fir_filter_ccf')
def m_xlate(cc, b, ins):
    x = ins[0]
    code = cc.raw(b, 'type', 'ccc')
    if cc.deps(b, 'taps'):
        cc.diag.err('E401', f'{b.name}: taps depend on a runtime variable')
    taps = list(cc.ev(b, 'taps', [1.0]))
    decim = int(cc.ev(b, 'decim', 1))
    fs = float(cc.ev(b, 'samp_rate', 1))
    mrng = x.rng * (math.sqrt(2) if x.fmt.cplx else 1.0)
    mf = for_range(mrng, cc.prof['w'], True)
    from .core import Net
    xm = Net(mf, mrng)
    xm.fmt = mf
    i = fir_inst(cc, b, xm, taps, 1, decim, True, module='grv_xlating_fir',
                 extra=dict(MW=mf.w, SHIFT_MIX=x.fmt.f + 17 - mf.f))
    # replace the internal input by the real input
    i.ins = [(x, x.fmt.w)]
    x.dst.append((i, 0))
    p = i.params
    p['IW'], p['ICPLX'], p['DECIM'] = x.fmt.w, int(x.fmt.cplx), decim
    for k in ('L', 'M'):
        p.pop(k)
    cc.cfg(i, 'cfg_freq', 32, b, 'center_freq', lambda v: wrap32(round(-float(v) / fs * 2 ** 32)),
           desc='NCO phase increment, -center_freq / samp_rate * 2^32')
    i.cost['mult'] = 4
    i.mix_fmt = mf
    return i.outs


@finalize('grv_fir', 'grv_xlating_fir')
def f_fir(cc, i):
    p = i.params
    L = p.get('L', 1)
    M = p.get('M', p.get('DECIM', 1))
    n = p['NTAPS']
    tpp = -(-n // L)
    nw = -(-n // 2) if p['SYM'] else tpp
    mpt = (2 if p['ICPLX'] else 1) * (2 if p['CCPLX'] else 1)
    if i.module == 'grv_xlating_fir':
        mpt = 2 * (2 if p['CCPLX'] else 1)
    # clocks available per output
    clocks = i.budget_out if i.known_rate else 1
    pr = i.blk.prag
    if 'lanes' in pr:
        p['LANES'] = int(pr['lanes'])
    elif cc.fold == 'off' or clocks <= 9:
        p['LANES'] = 0
    else:
        lanes = -(-nw // (clocks - 8))
        p['LANES'] = 0 if lanes * 2 >= nw else lanes
    if p['LANES'] == 0:
        mults = (-(-n // 2) if p['SYM'] else tpp) * mpt
        i.meta['ii'] = 1 if L == 1 else 1
        i.cost.update(mult=mults + (4 if i.module == 'grv_xlating_fir' else 0), lut=int(1.2 * p['OW'] * tpp) + 60, bram=0)
    else:
        P = -(-nw // p['LANES'])
        i.meta['ii'] = max(1, (P + 8) // max(1, M))
        dbits = (tpp + M + 3) * p['IW'] * (2 if p['ICPLX'] or i.module == 'grv_xlating_fir' else 1)
        i.cost.update(mult=p['LANES'] * mpt + (1 if i.module == 'grv_xlating_fir' else 0), lut=350 + 100 * p['LANES'] * mpt + (250 if i.module == 'grv_xlating_fir' else 0),
                      bram=p['LANES'] * (2 if p['SYM'] else 1) * bram_for(dbits) + p['LANES'] * bram_for(L * tpp * p['CW']))
        if i.module == 'grv_xlating_fir':
            i.cost['bram'] += 1
    i.meta['latency'] = 4 if p['LANES'] == 0 else -(-nw // max(p['LANES'], 1)) + 8


@mapper('single_pole_iir_filter_xx', 'single_pole_iir_filter_ff', 'single_pole_iir_filter_cc')
def m_iir1(cc, b, ins):
    x = ins[0]
    amax = max(cc.range_of(b, 'alpha', 1.0))
    amin = min(v for v in cc.range_of(b, 'alpha', 1.0) if v > 0) if amax > 0 else 1.0
    aw = 18
    af = min(40, aw - 1 - max(0, math.ceil(math.log2(amax + 1e-12))) if amax >= 1 else 16 - math.floor(math.log2(amax)))
    while round(amax * 2 ** af) > (1 << aw) - 1:
        af -= 1
    g = int(b.prag.get('guard', max(4, min(16, int(-math.log2(amin)) + 2))))
    of = out_fmt(cc, b, 'complex' if x.fmt.cplx else 'float', x.rng)
    p = rs(cc, b, dict(IW=x.fmt.w, CPLX=int(x.fmt.cplx), G=g, AW=aw, AF=af, OW=of.w, SHIFT=x.fmt.f + g - of.f))
    i = mk(cc, b, 'grv_iir1', p, ins=[(x, x.fmt.w)], outs=[(of, x.rng)])
    cc.cfg(i, 'cfg_alpha', aw, b, 'alpha', lambda v: round(float(v) * 2 ** af), signed=False, desc=f'alpha u{aw}.{af}')
    i.meta.update(ii=4)
    i.cost.update(mult=2 if x.fmt.cplx else 1, lut=120)
    return i.outs


@mapper('dc_blocker_xx', 'dc_blocker_ff', 'dc_blocker_cc')
def m_dc(cc, b, ins):
    x = ins[0]
    d = int(cc.ev(b, 'length', 32))
    if bool(cc.ev(b, 'long_form', True)):
        cc.diag.warn('W104', f'{b.name}: long form is implemented as the short form (two moving averages)')
    if d < 2:
        cc.diag.err('E102', f'{b.name}: length must be at least 2')
    rng = 2 * x.rng
    of = out_fmt(cc, b, 'complex' if x.fmt.cplx else 'float', rng)
    if d & (d - 1) == 0:
        k, kf = 1, 2 * int(math.log2(d))
    else:
        kf = coef_q(None, 18, 1.0 / (d * d))
        k = int(round(2 ** kf / (d * d)))
    p = rs(cc, b, dict(IW=x.fmt.w, CPLX=int(x.fmt.cplx), D=d, KW=18, K=k, OW=of.w, SHIFT=x.fmt.f + kf - of.f))
    i = mk(cc, b, 'grv_dc_blocker', p, ins=[(x, x.fmt.w)], outs=[(of, rng)])
    i.cost.update(mult=2 if x.fmt.cplx else 1, bram=3 * bram_for(d * (x.fmt.w + 8)), lut=200)
    return i.outs


@mapper('grv_cic_decim', 'grv_cic_interp')
def m_cic(cc, b, ins):
    x = ins[0]
    dec = b.id == 'grv_cic_decim'
    n, r, md = int(cc.ev(b, 'stages', 3)), int(cc.ev(b, 'ratio', 8)), int(cc.ev(b, 'diff_delay', 1))
    gain = (r * md) ** n / (1 if dec else r)
    lg = math.ceil(math.log2(gain)) if gain > 1 else 0
    gw = x.fmt.w + math.ceil(n * math.log2(r * md)) + 1
    of = out_fmt(cc, b, 'complex' if x.fmt.cplx else 'float', x.rng)
    p = rs(cc, b, dict(DECIM=int(dec), IW=x.fmt.w, CPLX=int(x.fmt.cplx), N=n, R=r, MD=md, GW=gw, OW=of.w, SHIFT=x.fmt.f + lg - of.f))
    i = mk(cc, b, 'grv_cic', p, ins=[(x, x.fmt.w)], outs=[(of, x.rng, Fraction(1, r) if dec else r)])
    i.meta.update(fill=r if dec else 1)
    i.cost.update(lut=2 * n * gw * (2 if x.fmt.cplx else 1))
    return i.outs


# ------------------------------------------------------------------ modulation and synchronisation
@mapper('blocks_rotator_cc')
def m_rot(cc, b, ins):
    x = ins[0]
    rng = x.rng * math.sqrt(2)
    of = out_fmt(cc, b, 'complex', rng)
    p = rs(cc, b, dict(IW=x.fmt.w, ICPLX=int(x.fmt.cplx), OW=of.w, SHIFT=x.fmt.f + 17 - of.f))
    i = mk(cc, b, 'grv_mixer', p, ins=[(x, x.fmt.w)], outs=[(of, rng)])
    cc.cfg(i, 'cfg_freq', 32, b, 'phase_inc', lambda v: wrap32(round(float(v) / (2 * math.pi) * 2 ** 32)), desc='phase increment')
    i.cost.update(mult=4, bram=1)
    return i.outs


def fm_k(sens, f, kw=24):
    kreal = sens / (2 * math.pi) * 2 ** (32 - f)
    ksh = max(0, kw - 2 - math.floor(math.log2(abs(kreal)))) if kreal else 0
    return int(round(kreal * 2 ** ksh)), ksh


@mapper('analog_frequency_modulator_fc', 'analog_phase_modulator_fc')
def m_fm(cc, b, ins):
    x = ins[0]
    pm = 'phase' in b.id
    sens = float(cc.ev(b, 'sensitivity', 1.0))
    k, ksh = fm_k(sens, x.fmt.f)
    of = out_fmt(cc, b, 'complex', 1.0)
    p = rs(cc, b, dict(IW=x.fmt.w, KW=24, KSH=ksh, PM=int(pm), OW=of.w, SHIFT=17 - of.f))
    i = mk(cc, b, 'grv_fm_mod', p, ins=[(x, x.fmt.w)], outs=[(of, 1.0)])
    cc.cfg(i, 'cfg_k', 24, b, 'sensitivity', lambda v: fm_k(float(v), x.fmt.f)[0] if fm_k(float(v), x.fmt.f)[1] == ksh
           else int(round(float(v) / (2 * math.pi) * 2 ** (32 - x.fmt.f + ksh))), desc='sensitivity')
    i.cost.update(mult=1, bram=1)
    return i.outs


@mapper('analog_agc_xx', 'analog_agc_cc', 'analog_agc_ff')
def m_agc(cc, b, ins):
    x = ins[0]
    ref = float(cc.ev(b, 'reference', 1.0))
    g0, gmax = float(cc.ev(b, 'gain', 1.0)), float(cc.ev(b, 'max_gain', 65536))
    rate = max(cc.range_of(b, 'rate', 1e-4))
    rng = 4 * ref
    of = out_fmt(cc, b, 'complex' if x.fmt.cplx else 'float', rng)
    gw = 32
    gf = gw - 1 - int_bits(max(gmax if gmax > 0 else 65536, g0, 1.0)) + 1
    rw = 18
    rf = 16 - math.floor(math.log2(rate)) if rate > 0 else 17
    p = rs(cc, b, dict(IW=x.fmt.w, CPLX=int(x.fmt.cplx), GW=gw, G0=int(round(g0 * 2 ** gf)), OW=of.w,
                       SHIFT=x.fmt.f + gf - of.f, RW=rw, RSH=of.f + rf - gf, MAXEN=int(gmax > 0)))
    i = mk(cc, b, 'grv_agc', p, ins=[(x, x.fmt.w)], outs=[(of, rng)])
    cc.cfg(i, 'cfg_rate', rw, b, 'rate', lambda v: round(float(v) * 2 ** rf), signed=False, desc=f'rate u{rw}.{rf}')
    cc.cfg(i, 'cfg_ref', of.w, b, 'reference', lambda v: round(float(v) * 2 ** of.f), desc=f'reference {of.with_(cplx=False)}')
    cc.cfg(i, 'cfg_max', gw, b, 'max_gain', lambda v: round(float(v) * 2 ** gf) if float(v) > 0 else (1 << (gw - 1)) - 1,
           desc=f'maximum gain s{gw}.{gf}')
    i.meta.update(ii=7)
    i.cost.update(mult=4 if x.fmt.cplx else 2, lut=250)
    i.status = dict(gain=(gw, gf))
    return i.outs


@mapper('analog_simple_squelch_cc', 'analog_pwr_squelch_xx', 'analog_pwr_squelch_cc', 'analog_pwr_squelch_ff')
def m_squelch(cc, b, ins):
    x = ins[0]
    if 'pwr' in b.id and int(cc.ev(b, 'ramp', 0) or 0) != 0:
        cc.diag.err('E102', f'{b.name}: ramp must be 0')
    gate = int(bool(cc.ev(b, 'gate', False))) if 'pwr' in b.id else 0
    alpha = max(cc.range_of(b, 'alpha', 1e-4))
    aw = 18
    af = 16 - math.floor(math.log2(alpha)) if alpha < 1 else 17
    g = 4
    tf = 2 * x.fmt.f + g
    p = dict(IW=x.fmt.w, CPLX=int(x.fmt.cplx), G=g, AW=aw, AF=af, GATE=gate, OREG=oreg(cc))
    i = mk(cc, b, 'grv_squelch', p, ins=[(x, x.fmt.w)], outs=[(x.fmt, x.rng, 1)], ovf=False)
    tw = 2 * x.fmt.w + g + 2
    cc.cfg(i, 'cfg_alpha', aw, b, 'alpha', lambda v: round(float(v) * 2 ** af), signed=False, desc=f'alpha u{aw}.{af}')
    cc.cfg(i, 'cfg_thr', tw, b, 'threshold', lambda v: min((1 << tw) - 1, round(10 ** (float(v) / 10) * 2 ** tf)), signed=False,
           desc=f'power threshold u{tw}.{tf}')
    i.meta.update(ii=6)
    i.cost.update(mult=3, lut=150)
    return i.outs


@mapper('digital_costas_loop_cc')
def m_costas(cc, b, ins):
    x = ins[0]
    order = int(cc.ev(b, 'order', 2))
    if order not in (2, 4):
        cc.diag.err('E102', f'{b.name}: order {order} (2 and 4 are supported)')
    bw = float(cc.ev(b, 'w', 0.0628))
    rng = x.rng * math.sqrt(2)
    of = out_fmt(cc, b, 'complex', rng)
    ew, ef, kw = 18, 15, 24
    d = 1 + 2 * (math.sqrt(2) / 2) * bw + bw * bw
    alpha, beta = 4 * (math.sqrt(2) / 2) * bw / d, 4 * bw * bw / d

    def kq(v):
        kreal = v / (2 * math.pi) * 2 ** (32 - ef)
        s = max(0, kw - 2 - math.floor(math.log2(kreal))) if kreal > 0 else 0
        return int(round(kreal * 2 ** s)), s
    ka, sa = kq(alpha)
    kb, sb = kq(beta)
    p = rs(cc, b, dict(IW=x.fmt.w, OW=of.w, SHIFT=x.fmt.f + 17 - of.f, ORDER=order, EW=ew, EF=ef,
                       SHE=(2 * of.f - ef) if order == 2 else (of.f - ef), KW=kw, SA=sa, SB=sb,
                       FMAX=int(2 ** 32 / (2 * math.pi))))
    i = mk(cc, b, 'grv_costas', p, ins=[(x, x.fmt.w)], outs=[(of, rng)])
    i.extra['cfg_ka'] = f"{kw}'d{ka}"
    i.extra['cfg_kb'] = f"{kw}'d{kb}"
    i.model_cfg = dict(ka=ka, kb=kb)
    i.meta.update(ii=9)
    i.cost.update(mult=6, bram=1, lut=300)
    i.status = dict(freq=(32, 0), phase=(32, 0))
    return i.outs


# ------------------------------------------------------------------ bits and symbols
def repack(cc, b, x, k, lo, msb, ratio):
    i = mk(cc, b, 'grv_repack', dict(K=k, LO=lo, MSB=int(msb), IW=x.fmt.w, OW=8, OREG=oreg(cc)), ins=[(x, x.fmt.w)],
           outs=[(Fmt(8, 0, False, False), 255.0, ratio)], ovf=False)
    i.raw_in = True
    return i.outs


@mapper('blocks_pack_k_bits_bb')
def m_pack(cc, b, ins):
    k = int(cc.ev(b, 'k', 8))
    return repack(cc, b, ins[0], 1, k, True, Fraction(1, k))


@mapper('blocks_unpack_k_bits_bb')
def m_unpack(cc, b, ins):
    k = int(cc.ev(b, 'k', 8))
    return repack(cc, b, ins[0], k, 1, True, k)


@mapper('blocks_packed_to_unpacked_xx', 'blocks_unpacked_to_packed_xx', 'blocks_repack_bits_bb')
def m_repack(cc, b, ins):
    if cc.raw(b, 'type', 'byte') not in ('byte', ''):
        cc.diag.err('E102', f'{b.name}: only byte streams are supported')
    msb = int(cc.ev(b, 'endianness', 1 if b.id == 'blocks_repack_bits_bb' else 0)) == 0
    if b.id == 'blocks_repack_bits_bb':
        k, lo = int(cc.ev(b, 'k', 2)), int(cc.ev(b, 'l', 8))
    else:
        bpc = int(cc.ev(b, 'bits_per_chunk', 1))
        k, lo = (8, bpc) if 'packed_to_unpacked' in b.id else (bpc, 8)
    return repack(cc, b, ins[0], k, lo, msb, Fraction(k, lo))


@mapper('digital_binary_slicer_fb')
def m_slicer(cc, b, ins):
    x = ins[0]
    i = mk(cc, b, 'grv_lut', dict(IW=x.fmt.w, SLICER=1, D=1, N=2, OW=8, OCPLX=0, TABLE=(16, 0), OREG=oreg(cc)),
           ins=[(x, x.fmt.w)], outs=[(Fmt(8, 0, False, False), 1.0)], ovf=False)
    return i.outs


@mapper('digital_chunks_to_symbols_xx', 'digital_map_bb')
def m_c2s(cc, b, ins):
    x = ins[0]
    from .fx import pack
    if b.id == 'digital_map_bb':
        tab = [int(v) for v in cc.ev(b, 'map', [0, 1])]
        of, d, rng = Fmt(8, 0, False, False), 1, 255.0
        ents = [v & 0xFF for v in tab]
    else:
        tab = [complex(v) for v in cc.ev(b, 'symbol_table', [-1, 1])]
        d = int(cc.ev(b, 'dimension', 1))
        oc = cc.raw(b, 'out_type', 'complex') == 'complex'
        rng = max(max(abs(t.real), abs(t.imag)) for t in tab)
        of = out_fmt(cc, b, 'complex' if oc else 'float', rng)
        ents = [pack((round(t.real * 2 ** of.f), round(t.imag * 2 ** of.f)) if of.cplx else round(t.real * 2 ** of.f), of.w, of.cplx)
                for t in tab]
    ew = of.tw
    p = dict(IW=x.fmt.w, SLICER=0, D=d, N=len(ents), OW=of.w, OCPLX=int(of.cplx),
             TABLE=(len(ents) * ew, sum(e << (k * ew) for k, e in enumerate(ents))), OREG=oreg(cc))
    i = mk(cc, b, 'grv_lut', p, ins=[(x, x.fmt.w)], outs=[(of, rng, d)], ovf=False)
    i.raw_in = True
    return i.outs


@mapper('digital_constellation_decoder_cb')
def m_cdec(cc, b, ins):
    x = ins[0]
    need_cplx(cc, b, x, True)
    con = cc.ev(b, 'constellation')
    if not isinstance(con, Constellation):
        cc.diag.err('E102', f'{b.name}: constellation must be a constellation object (variable_constellation or bpsk)')
    from .fx import pack
    f = x.fmt
    pts = [(max(-(1 << (f.w - 1)), min((1 << (f.w - 1)) - 1, round(p.real * 2 ** f.f))),
            max(-(1 << (f.w - 1)), min((1 << (f.w - 1)) - 1, round(p.imag * 2 ** f.f)))) for p in con.pts]
    if len(pts) > 64:
        cc.diag.err('E102', f'{b.name}: more than 64 constellation points')
    p = dict(IW=f.w, NP=len(pts), POINTS=(len(pts) * 2 * f.w, sum(pack(q, f.w, True) << (2 * f.w * k) for k, q in enumerate(pts))),
             SYMS=(len(pts) * 8, sum((int(s) & 0xFF) << (8 * k) for k, s in enumerate(con.syms))), OREG=oreg(cc))
    i = mk(cc, b, 'grv_const_decoder', p, ins=[(x, f.w)], outs=[(Fmt(8, 0, False, False), 255.0)], ovf=False)
    i.meta.update(ii=len(pts) + 4)
    i.cost.update(mult=2, lut=150)
    return i.outs


def bitop(cc, b, x, **p):
    p.setdefault('OREG', oreg(cc))
    i = mk(cc, b, 'grv_bitops', p, ins=[(x, 8)], outs=[(Fmt(8, 0, False, False), 255.0)], ovf=False)
    i.raw_in = True
    return i.outs


@mapper('digital_diff_encoder_bb', 'digital_diff_decoder_bb')
def m_diff(cc, b, ins):
    if int(cc.ev(b, 'coding', 0) or 0) != 0:
        cc.diag.err('E102', f'{b.name}: only differential coding is supported')
    return bitop(cc, b, ins[0], MODE=0 if 'encoder' in b.id else 1, MODULUS=int(cc.ev(b, 'modulus', 2)))


@mapper('digital_scrambler_bb', 'digital_descrambler_bb')
def m_scr(cc, b, ins):
    return bitop(cc, b, ins[0], MODE=2 if b.id == 'digital_scrambler_bb' else 3, MASK=int(cc.ev(b, 'mask', 0x8A)),
                 SEED=int(cc.ev(b, 'seed', 0x7F)), LEN=int(cc.ev(b, 'len', 7)))


@mapper('digital_additive_scrambler_bb')
def m_ascr(cc, b, ins):
    if int(cc.ev(b, 'bits_per_byte', 1)) != 1:
        cc.diag.err('E102', f'{b.name}: bits_per_byte must be 1')
    return bitop(cc, b, ins[0], MODE=4, MASK=int(cc.ev(b, 'mask', 0x8A)), SEED=int(cc.ev(b, 'seed', 0x7F)),
                 LEN=int(cc.ev(b, 'len', 7)), COUNT=int(cc.ev(b, 'count', 0)))


@mapper('digital_correlate_access_code_bb', 'digital_correlate_access_code_bb_ts')
def m_acode(cc, b, ins):
    code = str(cc.ev(b, 'access_code', '"0"'))
    code = code.strip('"\'')
    if not code or any(ch not in '01' for ch in code) or len(code) > 64:
        cc.diag.err('E102', f'{b.name}: access code must be up to 64 characters 0 / 1')
    return bitop(cc, b, ins[0], MODE=5, LEN=len(code), CODE=int(code, 2), THR=int(cc.ev(b, 'threshold', 0)))


# ------------------------------------------------------------------ FFT
@mapper('fft_vxx', 'fft_vcc', 'fft_vfc')
def m_fft(cc, b, ins):
    x = ins[0]
    n = int(cc.ev(b, 'fft_size', 1024))
    if n < 8 or n > 4096 or n & (n - 1):
        cc.diag.err('E102', f'{b.name}: fft_size {n} (powers of two 8 .. 4096)')
    wv = cc.ev(b, 'window', None)
    win = [] if wv is None else [float(v) for v in wv]
    lg = int(math.log2(n))
    dw = x.fmt.w + 1
    if win and len(win) != n:
        cc.diag.err('E102', f'{b.name}: window of {len(win)} values for fft_size {n}')
    wmax = max(abs(w) for w in win) if win else 1.0
    if wmax > 1.0:
        cc.diag.err('E102', f'{b.name}: window values above 1 are not supported')
    rng = x.rng * n * wmax * (math.sqrt(2) if x.fmt.cplx else 1)
    of = out_fmt(cc, b, 'complex', rng)
    hwf = x.fmt.f - lg
    wq = [to_u(int(round(w * 131071)), 18) for w in (win or [1.0] * n)]
    p = rs(cc, b, dict(N=n, IW=x.fmt.w, ICPLX=int(x.fmt.cplx), DW=dw, FWD=int(bool(cc.ev(b, 'forward', True))), WIN=int(bool(win)),
                       WW=18, WINDOW=(n * 18, sum(v << (18 * k) for k, v in enumerate(wq))), WSH=17,
                       SHIFTED=int(bool(cc.ev(b, 'shift', False))), OW=of.w, SHIFT=hwf - of.f))
    i = mk(cc, b, 'grv_fft', p, ins=[(x, x.fmt.w)], outs=[(of, rng, 1, n)])
    i.meta.update(fill=n, cap=2 * n, ii=max(1, (6 * (n // 2) * lg + 2 * n) // n))
    i.cost.update(mult=4 + (2 if win else 0), bram=bram_for(n * 2 * dw) + (bram_for(n * 18) if win else 0) + 1, lut=500)
    return i.outs


# ------------------------------------------------------------------ fork (inserted)
def mk_fork(cc, net):
    dst = list(net.dst)
    i = Inst(cc.uniq(f'fork_{net.name}'), 'grv_fork', dict(W=net.fmt.tw, N=len(dst)), 'fork', None)
    i.ins = [(net, net.fmt.tw)]
    i.raw_in = True
    net.dst = [(i, 0)]
    for k, (d, port) in enumerate(dst):
        n = cc.new_net(net.fmt, net.rng, net.vlen)
        n.rate, n.src = net.rate, (i, k)
        i.outs.append(n)
        n.dst = [(d, port)]
        old = d.ins[port]
        d.ins[port] = (n, old[1])
    i.meta.update(latency=0, cap=1)
    i.cost.update(lut=len(dst) * 2)
    cc.insts.append(i)
    return i


def mk_fifo(cc, inst, port, depth):
    """balancing FIFO before input port of inst"""
    net, w = inst.ins[port]
    i = Inst(cc.uniq(f'bal_{inst.name}_{port}'), 'grv_fifo', dict(W=net.fmt.tw, DEPTH=depth), 'fork', None)
    i.ins = [(net, net.fmt.tw)]
    i.raw_in = True
    net.dst = [(i, 0) if (d is inst and p == port) else (d, p) for d, p in net.dst]
    n = cc.new_net(net.fmt, net.rng, net.vlen)
    n.rate, n.src = net.rate, (i, 0)
    n.dst = [(inst, port)]
    i.outs.append(n)
    inst.ins[port] = (n, w)
    i.extra['level'] = ''
    i.meta.update(latency=1, cap=depth + 1, fill=1)
    i.cost.update(bram=bram_for(depth * net.fmt.tw), lut=30)
    cc.insts.append(i)
    return i


from . import periph  # noqa: E402,F401  (registers the mappers of the peripheral endpoints and DMA)
