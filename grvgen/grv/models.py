"""Bit-exact models of the OpenGRV modules, keyed by Verilog module name.

A model is f(p, ins, lasts, cfg) -> (outs, out_lasts):
  p      dict of Verilog parameters of the instance (as grvgen writes them)
  ins    list (per input port) of samples: int for real ports, (i, q) tuples for complex ports
  lasts  list (per input port) of tlast bits
  cfg    dict of runtime parameter values in hardware units (cfg_<name> without the prefix)
Models describe values, not timing. Sources take the number of samples to produce in cfg['_n'].
"""
from .fx import rz, resize, wrap, sin12, cos12, cordic_vec, cordic_rot, xorshift32, seeds, clog2

MODELS = {}


def model(name):
    def deco(f):
        MODELS[name] = f
        return f
    return deco


def cpx(p, key='CPLX'):
    return bool(p.get(key, 0))


def comp(v, c):
    """component c of a sample (c = 0 real / I, 1 Q)"""
    return v[c] if isinstance(v, tuple) else v


def mk(vals, cplx):
    return tuple(vals) if cplx else vals[0]


def rsz(p, x, ow=None, osig=None):
    return rz(x, ow or p['OW'], p.get('SHIFT', 0), p.get('ROUND', 1), p.get('SAT', 1),
              bool(p.get('OSIGNED', 1)) if osig is None else osig)


# ------------------------------------------------------------------ primitives as streams
@model('grv_skid')
def m_skid(p, ins, lasts, cfg):
    return [list(ins[0])], [list(lasts[0])]


@model('grv_fifo')
def m_fifo(p, ins, lasts, cfg):
    return [list(ins[0])], [list(lasts[0])]


@model('grv_fork')
def m_fork(p, ins, lasts, cfg):
    n = p.get('N', 2)
    return [list(ins[0]) for _ in range(n)], [list(lasts[0]) for _ in range(n)]


# ------------------------------------------------------------------ conversion
@model('grv_convert')
def m_convert(p, ins, lasts, cfg):
    c = cpx(p)
    out = []
    for v in ins[0]:
        r = []
        for k in range(2 if c else 1):
            x = comp(v, k)
            if not p.get('ISIGNED', 1):
                x &= (1 << p['IW']) - 1
            if p.get('MULK', 0):
                x *= p['K']
            r.append(rsz(p, x))
        out.append(mk(r, c))
    return [out], [list(lasts[0])]


# ------------------------------------------------------------------ sources
def _n(cfg):
    return cfg.get('_n', 64)


@model('grv_sig_source')
def m_sig_source(p, ins, lasts, cfg):
    c, wave = cpx(p), p.get('WAVE', 2)
    ph = p.get('PHASE0', 0) & 0xFFFFFFFF
    inc, amp = cfg.get('freq', 0) & 0xFFFFFFFF, cfg.get('amp', 0)
    oi, oq = cfg.get('offset', 0) << p.get('OFSH', 0), cfg.get('offset_q', 0) << p.get('OFSH', 0)
    out = []
    for _ in range(_n(cfg)):
        p12 = ph >> 20
        s, co = sin12(p12), cos12(p12)
        ps = wrap(ph >> 14, 18)
        wq = 0
        if wave == 0:
            wi = 131071
        elif wave in (1, 2):
            wi = co if (c or wave == 2) else s
            wq = s
        elif wave == 3:
            wi = 0 if ph >> 31 else 131071
        elif wave == 4:
            wi = min(ps + 131072 if ps < 0 else 131072 - ps, 131071)
        else:
            wi = (ps >> 1) + 65536
        r = [rsz(p, wi * amp + oi)]
        if c:
            r.append(rsz(p, wq * amp + oq))
        out.append(mk(r, c))
        ph = (ph + inc) & 0xFFFFFFFF
    return [out], [[0] * len(out)]


@model('grv_noise_source')
def m_noise_source(p, ins, lasts, cfg):
    c = cpx(p)
    ns = 4 if p.get('TYPE', 1) else 1
    st = seeds(p.get('SEED', 0), ns * (2 if c else 1))
    amp = cfg.get('amp', 0)
    out = []
    for _ in range(_n(cfg)):
        r = []
        for k in range(2 if c else 1):
            w = sum(wrap(st[k * ns + j] >> 14, 18) for j in range(ns))
            r.append(rsz(p, w * amp))
        out.append(mk(r, c))
        st = [xorshift32(s) for s in st]
    return [out], [[0] * len(out)]


@model('grv_const_source')
def m_const_source(p, ins, lasts, cfg):
    c = cpx(p)
    v = cfg.get('value', 0)
    from .fx import unpack
    s = unpack(v, p['OW'], c)
    return [[s] * _n(cfg)], [[0] * _n(cfg)]


@model('grv_vector_rom')
def m_vector_rom(p, ins, lasts, cfg):
    sw, n = p['SW'], p['N']
    vec = p['VEC'][1] if isinstance(p['VEC'], tuple) else p['VEC']
    vals = [(vec >> (i * sw)) & ((1 << sw) - 1) for i in range(n)]
    tot = _n(cfg) if p.get('REPEAT', 1) else min(_n(cfg), n)
    out = [vals[i % n] for i in range(tot)]
    vl = p.get('VLEN', 0)
    return [out], [[int(vl > 0 and i % vl == vl - 1) for i in range(tot)]]


@model('grv_glfsr')
def m_glfsr(p, ins, lasts, cfg):
    sr, mask = p.get('SEED', 1), p.get('MASK', 0x8E)
    per = (1 << p['DEGREE']) - 1
    tot = _n(cfg) if p.get('REPEAT', 1) else min(_n(cfg), per)
    out = []
    one = p.get('ONE', 1)
    for _ in range(tot):
        b = sr & 1
        out.append(b if not p.get('OUTF', 0) else (one if b else -one))
        sr = (sr >> 1) ^ mask if b else sr >> 1
    return [out], [[0] * tot]


# ------------------------------------------------------------------ math
def _join(ins):
    return list(zip(*ins))


@model('grv_add')
def m_add(p, ins, lasts, cfg):
    ni, c = p.get('NI', 2), cpx(p)
    shin = p.get('SHIFT_IN', 0)
    shin = shin[1] if isinstance(shin, tuple) else shin
    sh = [(shin >> (6 * k)) & 63 for k in range(ni)]
    out = []
    for t in _join(ins[:ni]):
        r = []
        for cc in range(2 if c else 1):
            acc = 0
            for k in range(ni):
                x = comp(t[k], cc) << sh[k]
                acc = acc - x if (p.get('SUB', 0) and k > 0) else acc + x
            r.append(rsz(p, acc))
        out.append(mk(r, c))
    return [out], [list(lasts[0][:len(out)])]


def cmul(a, b, conj=False):
    ar, ai = a
    br, bi = b
    if conj:
        return ar * br + ai * bi, ai * br - ar * bi
    return ar * br - ai * bi, ar * bi + ai * br


@model('grv_multiply')
def m_multiply(p, ins, lasts, cfg):
    c = cpx(p)
    out = []
    for a, b in _join(ins[:2]):
        if c:
            re, im = cmul(a, b, bool(p.get('CONJ', 0)))
            out.append((rsz(p, re), rsz(p, im)))
        else:
            out.append(rsz(p, a * b))
    return [out], [list(lasts[0][:len(out)])]


@model('grv_multiply_const')
def m_multiply_const(p, ins, lasts, cfg):
    ic, kc = cpx(p, 'ICPLX'), cpx(p, 'KCPLX')
    k = cfg.get('k', 0)
    kk = k if kc else (k, 0)
    out = []
    for x in ins[0]:
        xx = x if ic else (x, 0)
        re, im = cmul(xx, kk)
        out.append((rsz(p, re), rsz(p, im)) if (ic or kc) else rsz(p, re))
    return [out], [list(lasts[0])]


@model('grv_add_const')
def m_add_const(p, ins, lasts, cfg):
    c = cpx(p)
    k = cfg.get('k', 0)
    out = []
    for x in ins[0]:
        r = [rsz(p, (comp(x, j) << p.get('XSH', 0)) + (comp(k, j) << p.get('KSH', 0))) for j in range(2 if c else 1)]
        out.append(mk(r, c))
    return [out], [list(lasts[0])]


@model('grv_elem')
def m_elem(p, ins, lasts, cfg):
    op, c = p.get('OP', 1), cpx(p)
    out = []
    for x in ins[0]:
        xr, xi = comp(x, 0), comp(x, 1) if c else 0
        if op == 0:
            out.append((rz(xr, p['OW'], 0, p.get('ROUND', 1), 0), rsz(p, -xi, osig=True) if False else
                        rz(-xi, p['OW'], 0, p.get('ROUND', 1), p.get('SAT', 1))))
        elif op == 1:
            r = [rsz(p, abs(v)) for v in ([xr, xi] if c else [xr])]
            out.append(mk(r, c))
        elif op == 2:
            out.append(rsz(p, xr * xr + xi * xi))
        else:
            r = [rsz(p, -v) for v in ([xr, xi] if c else [xr])]
            out.append(mk(r, c))
    return [out], [list(lasts[0])]


@model('grv_cordic_vec')
def m_cordic_vec(p, ins, lasts, cfg):
    pw, it = p['PW'], p['ITER']
    prev = (0, 0)
    mags, args = [], []
    for x in ins[0]:
        if p.get('PRE', 0):
            re, im = cmul(x, prev, conj=True)
            sh = p.get('PSH', 0)
            v = (wrap(re >> sh, pw), wrap(im >> sh, pw))
            prev = x
        else:
            v = x
        xo, z = cordic_vec(v[0], v[1], it, pw + 3)
        zs = wrap(z, 32) >> (32 - p['ZB'])
        mags.append(rz(xo * p['KINV'], p['OW'], p['MSHIFT'], p.get('ROUND', 1), p.get('SAT', 1)))
        args.append(rz(zs * p['C'], p['OW'], p['ASHIFT'], p.get('ROUND', 1), p.get('SAT', 1)))
    o = p.get('OUTSEL', 0)
    l = list(lasts[0])
    if o == 0:
        return [mags], [l]
    if o == 1:
        return [args], [l]
    return [mags, args], [l, l]


# ------------------------------------------------------------------ logic, conversion
@model('grv_minmax')
def m_minmax(p, ins, lasts, cfg):
    f = max if p.get('MAX', 1) else min
    out = [f(t) for t in _join(ins[:p.get('NI', 2)])]
    return [out], [list(lasts[0][:len(out)])]


@model('grv_logic')
def m_logic(p, ins, lasts, cfg):
    op, w = p.get('OP', 0), p['W']
    m = (1 << w) - 1
    out = []
    for t in _join(ins[:p.get('NI', 2)]):
        r = t[0] & m
        for x in t[1:]:
            r = (r & x) if op == 0 else (r | x) if op == 1 else (r ^ x) if op == 2 else r
        if op == 3:
            r = ~t[0] & m
        if op == 4:
            r = t[0] & cfg.get('k', 0)
        out.append(r & m)
    return [out], [list(lasts[0][:len(out)])]


@model('grv_threshold')
def m_threshold(p, ins, lasts, cfg):
    st, out = bool(p.get('INIT', 0)), []
    for x in ins[0]:
        if x > cfg['hi']:
            st = True
        elif x < cfg['lo']:
            st = False
        out.append(p['ONE'] if st else 0)
    return [out], [list(lasts[0])]


@model('grv_complex_split')
def m_complex_split(p, ins, lasts, cfg):
    mode = p.get('MODE', 2)
    re = [x[0] for x in ins[0]]
    im = [x[1] for x in ins[0]]
    l = list(lasts[0])
    return ([re], [l]) if mode == 0 else ([im], [l]) if mode == 1 else ([re, im], [l, l])


@model('grv_float_to_complex')
def m_f2c(p, ins, lasts, cfg):
    ni = p.get('NI', 2)
    out = []
    for t in _join(ins[:ni]):
        a = rsz(p, t[0] << p.get('SH0', 0))
        b = rsz(p, t[1] << p.get('SH1', 0)) if ni > 1 else rsz(p, 0)
        out.append((a, b))
    return [out], [list(lasts[0][:len(out)])]


@model('grv_interleave_iq')
def m_iiq(p, ins, lasts, cfg):
    out, ol = [], []
    for x, l in zip(ins[0], lasts[0]):
        out += [rsz(p, x[0]), rsz(p, x[1])]
        ol += [0, int(bool(p.get('VEC', 0)) or bool(l))]
    return [out], [ol]


@model('grv_deinterleave_iq')
def m_diq(p, ins, lasts, cfg):
    x, out, ol = ins[0], [], []
    for k in range(0, len(x) - 1, 2):
        a, b = (x[k + 1], x[k]) if p.get('SWAP', 0) else (x[k], x[k + 1])
        out.append((rsz(p, a), rsz(p, b)))
        ol.append(lasts[0][k + 1])
    return [out], [ol]


# ------------------------------------------------------------------ stream operations
@model('grv_delay')
def m_delay(p, ins, lasts, cfg):
    d = p.get('DELAY', 1)
    x, l = list(ins[0]), list(lasts[0])
    zero = 0
    return [[zero] * min(d, len(x)) + x[:max(0, len(x) - d)]], [[0] * min(d, len(x)) + l[:max(0, len(x) - d)]]


@model('grv_select_stream')
def m_select_stream(p, ins, lasts, cfg):
    mode, n, m, off = p.get('MODE', 2), p.get('N', 1), p.get('M', 1), p.get('OFFSET', 0)
    out, ol = [], []
    for i, (x, l) in enumerate(zip(ins[0], lasts[0])):
        if mode == 0:
            keep = i < n
        elif mode == 1:
            keep = i >= n
        elif mode == 2:
            keep = i % cfg['n'] == cfg['n'] - 1
        elif mode == 3:
            keep = (i % n - off) % n < m
        else:
            keep = bool(cfg.get('en', 1))
        if keep:
            out.append(x)
            ol.append(l)
    return [out], [ol]


@model('grv_repeat')
def m_repeat(p, ins, lasts, cfg):
    n = p.get('N', 2)
    out, ol = [], []
    for x, l in zip(ins[0], lasts[0]):
        out += [x] * n
        ol += [0] * (n - 1) + [l]
    return [out], [ol]


@model('grv_vector_mark')
def m_vector_mark(p, ins, lasts, cfg):
    vl = p.get('VLEN', 4)
    n = len(ins[0])
    ol = [int(i % vl == vl - 1) for i in range(n)] if p.get('MODE', 0) == 0 else [0] * n
    return [list(ins[0])], [ol]


@model('grv_stream_mux')
def m_stream_mux(p, ins, lasts, cfg):
    ni = p.get('NI', 2)
    lens = p['LENS'][1] if isinstance(p['LENS'], tuple) else p['LENS']
    lens = [(lens >> (32 * k)) & 0xFFFFFFFF for k in range(ni)]
    idx = [0] * ni
    out, ol = [], []
    while True:
        for k in range(ni):
            for _ in range(lens[k]):
                if idx[k] >= len(ins[k]):
                    return [out], [ol]
                out.append(ins[k][idx[k]])
                ol.append(lasts[k][idx[k]])
                idx[k] += 1


@model('grv_demux')
def m_demux(p, ins, lasts, cfg):
    no = p.get('NO', 2)
    outs, ols = [[] for _ in range(no)], [[] for _ in range(no)]
    if p.get('MODE', 0) == 0:
        bs = p.get('BS', 1)
        for i, (x, l) in enumerate(zip(ins[0], lasts[0])):
            k = (i // bs) % no
            outs[k].append(x)
            ols[k].append(l)
    else:
        ni = p.get('NI', 1)
        n = min(len(x) for x in ins[:ni])
        ci, co, en = cfg.get('in', 0), cfg.get('out', 0), cfg.get('en', 1)
        if en and co < no and ci < ni:
            outs[co] = list(ins[ci][:n])
            ols[co] = list(lasts[ci][:n])
    return outs, ols


@model('grv_throttle')
def m_throttle(p, ins, lasts, cfg):
    return [list(ins[0])], [list(lasts[0])]


@model('grv_moving_average')
def m_moving_average(p, ins, lasts, cfg):
    c, n = cpx(p), p.get('LEN', 16)
    out, hist = [], []
    for x in ins[0]:
        hist.append(x)
        win = hist[-n:]
        r = [rsz(p, sum(comp(v, j) for v in win) * p.get('K', 1)) for j in range(2 if c else 1)]
        out.append(mk(r, c))
    return [out], [list(lasts[0])]


@model('grv_integrate')
def m_integrate(p, ins, lasts, cfg):
    c, d = cpx(p), p.get('D', 4)
    x, out, ol = ins[0], [], []
    for k in range(0, len(x) - d + 1, d):
        r = [rsz(p, sum(comp(v, j) for v in x[k:k + d])) for j in range(2 if c else 1)]
        out.append(mk(r, c))
        ol.append(lasts[0][k + d - 1])
    return [out], [ol]


# ------------------------------------------------------------------ filters
def unpack_taps(p):
    n, cw, cc = p['NTAPS'], p['CW'], cpx(p, 'CCPLX')
    v = p['COEFS'][1] if isinstance(p['COEFS'], tuple) else p['COEFS']
    nc = 2 if cc else 1
    out = []
    for k in range(n):
        r = wrap((v >> ((k * nc) * cw)) & ((1 << cw) - 1), cw)
        if cc:
            i = wrap((v >> ((k * nc + 1) * cw)) & ((1 << cw) - 1), cw)
            out.append((r, i))
        else:
            out.append(r)
    return out


def pack_taps(taps, cw, cc):
    from .fx import to_u
    v, nc = 0, 2 if cc else 1
    for k, h in enumerate(taps):
        if cc:
            v |= to_u(h[0], cw) << ((k * nc) * cw)
            v |= to_u(h[1], cw) << ((k * nc + 1) * cw)
        else:
            v |= to_u(h, cw) << (k * cw)
    return (len(taps) * cw * nc, v)


def fir_mac(x, h, ic, cc):
    """exact product of a sample and a tap, as a complex pair"""
    if ic and cc:
        return cmul(x, h)
    if ic:
        return x[0] * h, x[1] * h
    if cc:
        return x * h[0], x * h[1]
    return x * h, 0


def fir_rational(p, xs, ls):
    n_t, L, M = p['NTAPS'], p.get('L', 1), p.get('M', 1)
    ic, cc = cpx(p, 'ICPLX'), cpx(p, 'CCPLX')
    h = unpack_taps(p)
    tpp = (n_t + L - 1) // L
    out, ol = [], []
    ph, n = 0, 0
    while n < len(xs):
        ar = ai = 0
        for j in range(tpp):
            k = ph + j * L
            if k < n_t and n - j >= 0:
                a, b = fir_mac(xs[n - j], h[k], ic, cc)
                ar += a
                ai += b
        out.append((rsz(p, ar), rsz(p, ai)) if (ic or cc) else rsz(p, ar))
        ol.append(ls[n])
        ph += M
        while ph >= L:
            ph -= L
            n += 1
    return out, ol


@model('grv_fir')
def m_fir(p, ins, lasts, cfg):
    out, ol = fir_rational(p, ins[0], lasts[0])
    return [out], [ol]


@model('grv_mixer')
def m_mixer(p, ins, lasts, cfg):
    ic = cpx(p, 'ICPLX')
    inc, ph, out = cfg.get('freq', 0) & 0xFFFFFFFF, 0, []
    for x in ins[0]:
        c, s = cos12(ph >> 20), sin12(ph >> 20)
        xr, xi = (x if ic else (x, 0))
        out.append((rsz(p, xr * c - xi * s), rsz(p, xr * s + xi * c)))
        ph = (ph + inc) & 0xFFFFFFFF
    return [out], [list(lasts[0])]


@model('grv_xlating_fir')
def m_xlating_fir(p, ins, lasts, cfg):
    mp = {'OW': p['MW'], 'SHIFT': p['SHIFT_MIX'], 'ROUND': p.get('ROUND', 1), 'SAT': p.get('SAT', 1), 'ICPLX': p.get('ICPLX', 1)}
    (mixed,), (ml,) = m_mixer(mp, ins, lasts, cfg)
    fp = dict(p, IW=p['MW'], ICPLX=1, L=1, M=p.get('DECIM', 1))
    out, ol = fir_rational(fp, mixed, ml)
    return [out], [ol]


@model('grv_iir1')
def m_iir1(p, ins, lasts, cfg):
    c, g, af, a = cpx(p), p.get('G', 8), p.get('AF', 17), cfg.get('alpha', 0)
    st = [0, 0]
    out = []
    for x in ins[0]:
        r = []
        for j in range(2 if c else 1):
            d = (comp(x, j) << g) - st[j]
            st[j] += (d * a) >> af
            r.append(rsz(p, st[j]))
        out.append(mk(r, c))
    return [out], [list(lasts[0])]


@model('grv_cic')
def m_cic(p, ins, lasts, cfg):
    c, n, r_, md = cpx(p), p['N'], p['R'], p.get('MD', 1)
    ncomp = 2 if c else 1
    out, ol = [], []
    if p.get('DECIM', 1):
        I = [[0] * (n + 1) for _ in range(ncomp)]
        D = [[[0] * md for _ in range(n)] for _ in range(ncomp)]
        for idx, (x, l) in enumerate(zip(ins[0], lasts[0])):
            vals = []
            for j in range(ncomp):
                old = I[j][:]
                I[j][0] = comp(x, j)
                for k in range(1, n + 1):
                    I[j][k] = old[k] + (I[j][0] if k == 1 else old[k - 1])
                if idx % r_ == r_ - 1:
                    v = I[j][n]
                    for k in range(n):
                        y = v - D[j][k][-1]
                        D[j][k] = [v] + D[j][k][:-1]
                        v = y
                    vals.append(rsz(p, v))
            if vals:
                out.append(mk(vals, c))
                ol.append(l)
    else:
        I = [[0] * (n + 1) for _ in range(ncomp)]
        D = [[[0] * md for _ in range(n)] for _ in range(ncomp)]
        for x, l in zip(ins[0], lasts[0]):
            cv = []
            for j in range(ncomp):
                v = comp(x, j)
                for k in range(n):
                    y = v - D[j][k][-1]
                    D[j][k] = [v] + D[j][k][:-1]
                    v = y
                cv.append(v)
            for ph in range(r_):
                vals = []
                for j in range(ncomp):
                    old = I[j][:]
                    u = cv[j] if ph == 0 else 0
                    I[j][1] = old[1] + u
                    for k in range(2, n + 1):
                        I[j][k] = old[k] + old[k - 1]
                    vals.append(rsz(p, I[j][n]))
                out.append(mk(vals, c))
                ol.append(int(l and ph == r_ - 1))
    return [out], [ol]


# ------------------------------------------------------------------ modulation, synchronisation
@model('grv_fm_mod')
def m_fm_mod(p, ins, lasts, cfg):
    k, ksh, pm = cfg.get('k', 0), p.get('KSH', 0), p.get('PM', 0)
    ph, out = 0, []
    for x in ins[0]:
        inc = ((x * k) >> ksh) & 0xFFFFFFFF
        ph = inc if pm else (ph + inc) & 0xFFFFFFFF
        out.append((rsz(p, cos12(ph >> 20)), rsz(p, sin12(ph >> 20))))
    return [out], [list(lasts[0])]


def mag_approx(a, b):
    a, b = abs(a), abs(b)
    mx, mn = max(a, b), min(a, b)
    return (30 * mx + 15 * mn) >> 5


@model('grv_agc')
def m_agc(p, ins, lasts, cfg):
    c = cpx(p)
    g, gw = p.get('G0', 65536), p['GW']
    rate, ref, gmax = cfg['rate'], cfg['ref'], cfg['max']
    out = []
    for x in ins[0]:
        if c:
            y = (rsz(p, x[0] * g), rsz(p, x[1] * g))
            m = mag_approx(*y)
        else:
            y = rsz(p, x * g)
            m = abs(y)
        out.append(y)
        e = (ref - m) * rate
        gn = g + (e >> p['RSH'])
        g = gmax if (p.get('MAXEN', 1) and gn > gmax) else wrap(gn, gw)
    return [out], [list(lasts[0])]


@model('grv_squelch')
def m_squelch(p, ins, lasts, cfg):
    c, g, af = cpx(p), p.get('G', 4), p.get('AF', 17)
    a, thr = cfg['alpha'], cfg['thr']
    s, out, ol = 0, [], []
    for x, l in zip(ins[0], lasts[0]):
        pw = x[0] * x[0] + x[1] * x[1] if c else x * x
        d = (pw << g) - s
        s += (d * a) >> af
        if s >= thr:
            out.append(x)
            ol.append(l)
        elif not p.get('GATE', 0):
            out.append((0, 0) if c else 0)
            ol.append(l)
    return [out], [ol]


@model('grv_costas')
def m_costas(p, ins, lasts, cfg):
    ph, fr = 0, 0
    ka, kb = cfg['ka'], cfg['kb']
    ew, ef = p['EW'], p['EF']
    fmax = p.get('FMAX', 683565276)
    out = []
    for xr, xi in ins[0]:
        c, s = cos12(ph >> 20), sin12(ph >> 20)
        yr, yi = rsz(p, xr * c + xi * s), rsz(p, xi * c - xr * s)
        out.append((yr, yi))
        if p.get('ORDER', 2) == 2:
            e = yr * yi
        else:
            e = (yi if yr > 0 else -yi) - (yr if yi > 0 else -yr)
        e = rz(e, ew, p['SHE'], 0, 1)
        one = 1 << ef
        e = max(-one, min(one, e))
        fn = wrap(fr + ((e * kb) >> p['SB']), 32)
        ph = (ph + fn + ((e * ka) >> p['SA'])) & 0xFFFFFFFF
        fr = max(-fmax, min(fmax, fn))
    return [out], [list(lasts[0])]


@model('grv_dc_blocker')
def m_dc_blocker(p, ins, lasts, cfg):
    c, d, k = cpx(p), p['D'], p.get('K', 1)
    xs = ins[0]
    out = []
    s1h = [[], []]
    for n, x in enumerate(xs):
        r = []
        for j in range(2 if c else 1):
            s1 = sum(comp(v, j) for v in xs[max(0, n - d + 1):n + 1])
            s1h[j].append(s1)
            s2 = sum(s1h[j][max(0, n - d + 1):n + 1])
            xd = comp(xs[n - d + 1], j) if n - d + 1 >= 0 else 0
            r.append(rsz(p, (xd * d * d - s2) * k))
        out.append(mk(r, c))
    return [out], [list(lasts[0])]


# ------------------------------------------------------------------ bits and symbols
@model('grv_repack')
def m_repack(p, ins, lasts, cfg):
    k, lo, msb = p['K'], p['LO'], p.get('MSB', 1)
    bits, out = [], []
    for v in ins[0]:
        b = [(v >> i) & 1 for i in range(k)]
        bits += b[::-1] if msb else b
        while len(bits) >= lo:
            grp, bits = bits[:lo], bits[lo:]
            o = 0
            for i, bb in enumerate(grp):
                o |= bb << ((lo - 1 - i) if msb else i)
            out.append(o)
    return [out], [[0] * len(out)]


@model('grv_lut')
def m_lut(p, ins, lasts, cfg):
    d, n, ow = p.get('D', 1), p['N'], p['OW']
    oc = cpx(p, 'OCPLX')
    ew = ow * (2 if oc else 1)
    tab = p['TABLE'][1] if isinstance(p['TABLE'], tuple) else p['TABLE']
    from .fx import unpack
    ent = [unpack((tab >> (i * ew)) & ((1 << ew) - 1), ow, oc) for i in range(n)]
    out, ol = [], []
    for v, l in zip(ins[0], lasts[0]):
        if p.get('SLICER', 0):
            out.append(0 if wrap(v, p['IW']) < 0 else 1)
            ol.append(l)
            continue
        u = v & ((1 << p['IW']) - 1)
        for k in range(d):
            out.append(ent[(u * d + k) % n])
            ol.append(int(bool(l) and k == d - 1))
    return [out], [ol]


@model('grv_const_decoder')
def m_const_decoder(p, ins, lasts, cfg):
    iw, np_ = p['IW'], p['NP']
    pts = p['POINTS'][1] if isinstance(p['POINTS'], tuple) else p['POINTS']
    sy = p['SYMS'][1] if isinstance(p['SYMS'], tuple) else p['SYMS']
    P = [(wrap((pts >> (2 * k * iw)) & ((1 << iw) - 1), iw), wrap((pts >> ((2 * k + 1) * iw)) & ((1 << iw) - 1), iw)) for k in range(np_)]
    S = [(sy >> (8 * k)) & 0xFF for k in range(np_)]
    out = []
    for xr, xi in ins[0]:
        best, bs = None, 0
        for k, (pr, pi) in enumerate(P):
            dd = (xr - pr) ** 2 + (xi - pi) ** 2
            if best is None or dd < best:
                best, bs = dd, S[k]
        out.append(bs)
    return [out], [list(lasts[0])]


def parity(v):
    return bin(v).count('1') & 1


@model('grv_bitops')
def m_bitops(p, ins, lasts, cfg):
    mode, M = p.get('MODE', 0), p.get('MODULUS', 2)
    mask, seed, ln = p.get('MASK', 0), p.get('SEED', 0), p.get('LEN', 7)
    last, sr, cnt = 0, (0 if mode == 5 else seed), 0
    out = []
    for v in ins[0]:
        b = v & 1
        if mode == 0:
            o = (v + last) % M
            last = o
        elif mode == 1:
            o = ((v % M) + M - (last % M)) % M
            last = v
        elif mode == 2:
            o = sr & 1
            sr = (sr >> 1) | ((parity(sr & mask) ^ b) << ln)
        elif mode == 3:
            o = parity(sr & mask) ^ b
            sr = (sr >> 1) | (b << ln)
        elif mode == 4:
            o = b ^ (sr & 1)
            if p.get('COUNT', 0) and cnt == p['COUNT'] - 1:
                sr, cnt = seed, 0
            else:
                sr = (sr >> 1) | (parity(sr & mask) << ln)
                cnt += 1
        else:
            am = (1 << ln) - 1
            nw = bin((sr ^ p.get('CODE', 0)) & am).count('1')
            o = b | (int(cnt >= ln and nw <= p.get('THR', 0)) << 1)
            sr = ((sr << 1) | b) & ((1 << 64) - 1)
            cnt = min(cnt + 1, ln)
        out.append(o & 0xFF)
    return [out], [list(lasts[0])]


# ------------------------------------------------------------------ FFT
def bitrev(a, n):
    r = 0
    for i in range(n):
        r |= ((a >> i) & 1) << (n - 1 - i)
    return r


@model('grv_fft')
def m_fft(p, ins, lasts, cfg):
    N, dw = p['N'], p['DW']
    lg = N.bit_length() - 1
    ts = 12 - lg
    rnd, sat = p.get('ROUND', 1), p.get('SAT', 1)
    ic = cpx(p, 'ICPLX')
    win = None
    if p.get('WIN', 0):
        wv = p['WINDOW'][1] if isinstance(p['WINDOW'], tuple) else p['WINDOW']
        ww = p.get('WW', 18)
        win = [wrap((wv >> (i * ww)) & ((1 << ww) - 1), ww) for i in range(N)]
    out, ol = [], []
    xs = ins[0]
    for f0 in range(0, len(xs) - N + 1, N):
        X = []
        for n in range(N):
            x = xs[f0 + n]
            xr, xi = (x if ic else (x, 0))
            if win:
                X.append((rz(xr * win[n], dw, p['WSH'], rnd, sat), rz(xi * win[n], dw, p['WSH'], rnd, sat)))
            else:
                X.append((xr, xi))
        for s in range(lg):
            half = N >> (s + 1)
            for g in range(N // 2):
                j = g & (half - 1)
                ia = ((g >> (lg - 1 - s)) << (lg - s)) | j
                ib = ia | half
                (ar, ai), (br, bi) = X[ia], X[ib]
                X[ia] = ((ar + br) >> 1, (ai + bi) >> 1)
                dr, di = (ar - br) >> 1, (ai - bi) >> 1
                ph = (j << s) << ts
                c, sn = cos12(ph), sin12(ph)
                if p.get('FWD', 1):
                    rr, ri = dr * c + di * sn, di * c - dr * sn
                else:
                    rr, ri = dr * c - di * sn, di * c + dr * sn
                X[ib] = (rz(rr, dw, 17, rnd, sat), rz(ri, dw, 17, rnd, sat))
        for m in range(N):
            mm = m ^ (N // 2) if p.get('SHIFTED', 0) else m
            v = X[bitrev(mm, lg)]
            out.append((rsz(p, v[0]), rsz(p, v[1])))
            ol.append(int(m == N - 1))
    return [out], [ol]
