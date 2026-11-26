"""Tests of the logic, conversion and stream operation blocks."""
from tbutil import test, check, rnd_sample
from grv.fx import pack


def rs(rng, p, iw):
    p.update(ROUND=rng.randint(0, 3), SAT=rng.randint(0, 2), OREG=rng.randint(0, 1))
    return p


@test('grv_minmax')
def t_minmax(rng):
    ni, iw = rng.randint(1, 4), rng.randint(2, 24)
    p = {'NI': ni, 'IW': iw, 'MAX': rng.randint(0, 1), 'OREG': rng.randint(0, 1)}
    check('grv_minmax', p, [[rnd_sample(rng, iw, False) for _ in range(200)] for _ in range(ni)], iw, False, iw, False, rng=rng)


@test('grv_logic')
def t_logic(rng):
    op = rng.randint(0, 4)
    ni = 1 if op in (3, 4) else rng.randint(1, 4)
    w = rng.randint(1, 32)
    k = rng.getrandbits(w)
    p = {'NI': ni, 'W': w, 'OP': op, 'OREG': rng.randint(0, 1)}
    ins = [[rnd_sample(rng, w, False, False) for _ in range(200)] for _ in range(ni)]
    check('grv_logic', p, ins, w, False, w, False, osigned=False, isigned=False, rng=rng, hwcfg={'cfg_k': (w, k)}, mcfg={'k': k})


@test('grv_threshold')
def t_thr(rng):
    iw, ow = rng.randint(4, 20), rng.randint(4, 20)
    lo = rng.randint(-(1 << (iw - 2)), 0)
    hi = rng.randint(0, 1 << (iw - 2))
    p = {'IW': iw, 'OW': ow, 'ONE': (1 << (ow - 2)), 'INIT': rng.randint(0, 1), 'OREG': rng.randint(0, 1)}
    check('grv_threshold', p, [[rnd_sample(rng, iw, False) for _ in range(300)]], iw, False, ow, False, rng=rng,
          hwcfg={'cfg_lo': (iw, lo), 'cfg_hi': (iw, hi)}, mcfg={'lo': lo, 'hi': hi})


@test('grv_complex_split')
def t_split(rng):
    iw, mode = rng.randint(2, 24), rng.randint(0, 2)
    check('grv_complex_split', {'IW': iw, 'MODE': mode, 'OREG': rng.randint(0, 1)},
          [[rnd_sample(rng, iw, True) for _ in range(300)]], iw, True, iw, False, rng=rng)


@test('grv_float_to_complex')
def t_f2c(rng):
    ni, iw = rng.randint(1, 2), rng.randint(2, 20)
    p = rs(rng, {'NI': ni, 'IW': iw, 'SH0': rng.randint(0, 5), 'SH1': rng.randint(0, 5), 'OW': rng.randint(2, 24),
                 'SHIFT': rng.randint(-2, 8)}, iw)
    check('grv_float_to_complex', p, [[rnd_sample(rng, iw, False) for _ in range(250)] for _ in range(ni)], iw, False, p['OW'], True, rng=rng)


@test('grv_interleave_iq')
def t_iiq(rng):
    iw = rng.randint(2, 24)
    p = rs(rng, {'IW': iw, 'OW': rng.randint(2, 24), 'SHIFT': rng.randint(-2, 10), 'VEC': rng.randint(0, 1)}, iw)
    check('grv_interleave_iq', p, [[rnd_sample(rng, iw, True) for _ in range(200)]], iw, True, p['OW'], False, rng=rng)


@test('grv_deinterleave_iq')
def t_diq(rng):
    iw = rng.randint(2, 24)
    p = rs(rng, {'IW': iw, 'OW': rng.randint(2, 24), 'SHIFT': rng.randint(-2, 10), 'SWAP': rng.randint(0, 1)}, iw)
    check('grv_deinterleave_iq', p, [[rnd_sample(rng, iw, False) for _ in range(300)]], iw, False, p['OW'], True, rng=rng)


@test('grv_delay')
def t_delay(rng):
    w = rng.randint(1, 32)
    d = rng.choice([0, 1, 2, 3, 7, 64, 100, 300])
    check('grv_delay', {'W': w, 'DELAY': d, 'OREG': rng.randint(0, 1)}, [[rnd_sample(rng, w, False) for _ in range(400)]],
          w, False, w, False, rng=rng)


@test('grv_select_stream')
def t_sel(rng):
    w, mode = rng.randint(1, 32), rng.randint(0, 4)
    n = rng.randint(1, 9)
    p = {'W': w, 'MODE': mode, 'N': n if mode != 3 else rng.randint(2, 9), 'OREG': rng.randint(0, 1)}
    if mode == 3:
        p['M'] = rng.randint(1, p['N'])
        p['OFFSET'] = rng.randint(0, p['N'] - 1)
    en = rng.randint(0, 1)
    check('grv_select_stream', p, [[rnd_sample(rng, w, False) for _ in range(300)]], w, False, w, False, rng=rng,
          hwcfg={'cfg_n': (32, n), 'cfg_en': (1, en)}, mcfg={'n': n, 'en': en}, extra='')


@test('grv_repeat')
def t_rep(rng):
    w, n = rng.randint(1, 32), rng.randint(1, 6)
    check('grv_repeat', {'W': w, 'N': n, 'OREG': rng.randint(0, 1)}, [[rnd_sample(rng, w, False) for _ in range(150)]], w, False, w, False, rng=rng)


@test('grv_vector_mark')
def t_vm(rng):
    w = rng.randint(1, 32)
    check('grv_vector_mark', {'W': w, 'MODE': rng.randint(0, 1), 'VLEN': rng.randint(1, 9), 'OREG': rng.randint(0, 1)},
          [[rnd_sample(rng, w, False) for _ in range(200)]], w, False, w, False, rng=rng)


@test('grv_stream_mux')
def t_smux(rng):
    ni, w = rng.randint(1, 4), rng.randint(1, 24)
    lens = [rng.randint(0, 5) for _ in range(ni)]
    if not any(lens):
        lens[0] = 1
    p = {'NI': ni, 'W': w, 'LENS': (32 * ni, sum(l << (32 * k) for k, l in enumerate(lens))), 'OREG': rng.randint(0, 1)}
    ins = [[rnd_sample(rng, w, False) for _ in range(40 * max(lens[k], 1))] for k in range(ni)]
    from grv.models import MODELS
    want, _ = MODELS['grv_stream_mux'](p, ins, [[0] * len(x) for x in ins], {})
    check('grv_stream_mux', p, ins, w, False, w, False, nout=[len(want[0])], rng=rng)


@test('grv_demux')
def t_demux(rng):
    mode, w = rng.randint(0, 1), rng.randint(1, 24)
    if mode == 0:
        p = {'MODE': 0, 'NI': 1, 'NO': rng.randint(1, 4), 'W': w, 'BS': rng.randint(1, 4)}
        ins = [[rnd_sample(rng, w, False) for _ in range(240)]]
        cfg = {'in': 0, 'out': 0, 'en': 1}
    else:
        p = {'MODE': 1, 'NI': rng.randint(1, 3), 'NO': rng.randint(1, 3), 'W': w, 'BS': 1}
        ins = [[rnd_sample(rng, w, False) for _ in range(150)] for _ in range(p['NI'])]
        cfg = {'in': rng.randint(0, p['NI'] - 1), 'out': rng.randint(0, p['NO'] - 1), 'en': 1}
    from grv.models import MODELS
    want, _ = MODELS['grv_demux'](p, ins, [[0] * len(x) for x in ins], cfg)
    check('grv_demux', p, ins, w, False, w, False, nout=[len(x) for x in want], rng=rng,
          hwcfg={'cfg_in': (8, cfg['in']), 'cfg_out': (8, cfg['out']), 'cfg_en': (1, cfg['en'])}, mcfg=cfg)


@test('grv_throttle')
def t_thr2(rng):
    w = rng.randint(1, 24)
    check('grv_throttle', {'W': w, 'OREG': rng.randint(0, 1)}, [[rnd_sample(rng, w, False) for _ in range(100)]], w, False, w, False,
          rng=rng, hwcfg={'cfg_inc': (32, rng.randint(1 << 28, 1 << 31))})


@test('grv_moving_average')
def t_ma(rng):
    iw, c = rng.randint(2, 20), rng.random() < 0.4
    n = rng.choice([1, 2, 5, 16, 33, 100])
    kw = rng.randint(2, 18)
    p = rs(rng, {'IW': iw, 'CPLX': int(c), 'LEN': n, 'KW': kw, 'K': rng.randint(1, (1 << (kw - 1)) - 1),
                 'OW': rng.randint(2, 24), 'SHIFT': rng.randint(0, 30)}, iw)
    check('grv_moving_average', p, [[rnd_sample(rng, iw, c) for _ in range(300)]], iw, c, p['OW'], c, rng=rng)


@test('grv_integrate')
def t_integ(rng):
    iw, c = rng.randint(2, 20), rng.random() < 0.4
    p = rs(rng, {'IW': iw, 'CPLX': int(c), 'D': rng.randint(1, 9), 'OW': rng.randint(2, 24), 'SHIFT': rng.randint(-1, 8)}, iw)
    check('grv_integrate', p, [[rnd_sample(rng, iw, c) for _ in range(300)]], iw, c, p['OW'], c, rng=rng)
