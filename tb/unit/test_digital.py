"""Tests of the bit, symbol and FFT blocks."""
import math, cmath
from tbutil import test, check, rnd_sample
from grv.fx import pack, to_u


@test('grv_repack')
def t_repack(rng):
    k, lo = rng.randint(1, 8), rng.randint(1, 8)
    p = {'K': k, 'LO': lo, 'MSB': rng.randint(0, 1), 'IW': 8, 'OW': 8, 'OREG': rng.randint(0, 1)}
    ins = [[rng.getrandbits(8) for _ in range(200)]]
    check('grv_repack', p, ins, 8, False, 8, False, osigned=False, isigned=False, rng=rng)


@test('grv_lut')
def t_lut(rng):
    slicer = rng.random() < 0.2
    iw = rng.randint(1, 8) if not slicer else rng.randint(2, 16)
    d, n = rng.randint(1, 4), rng.randint(1, 20)
    ow, oc = rng.randint(2, 18), rng.random() < 0.5
    tab = [rnd_sample(rng, ow, oc) for _ in range(n)]
    tv = sum(pack(t, ow, oc) << (i * ow * (2 if oc else 1)) for i, t in enumerate(tab))
    p = {'IW': iw, 'SLICER': int(slicer), 'D': 1 if slicer else d, 'N': n, 'OW': 8 if slicer else ow,
         'OCPLX': 0 if slicer else int(oc), 'TABLE': (n * ow * (2 if oc else 1), tv) if not slicer else (n * 8, 0),
         'OREG': rng.randint(0, 1)}
    ins = [[rnd_sample(rng, iw, False, not slicer and False) if not slicer else to_u(rnd_sample(rng, iw, False), iw) for _ in range(150)]]
    if slicer:
        check('grv_lut', p, ins, iw, False, 8, False, osigned=False, rng=rng)
    else:
        check('grv_lut', p, ins, iw, False, ow, oc, rng=rng)


@test('grv_const_decoder')
def t_cdec(rng):
    iw, np_ = rng.randint(4, 14), rng.randint(1, 16)
    pts = [rnd_sample(rng, iw, True) for _ in range(np_)]
    syms = [rng.getrandbits(8) for _ in range(np_)]
    p = {'IW': iw, 'NP': np_, 'POINTS': (np_ * 2 * iw, sum(pack(q, iw, True) << (2 * iw * k) for k, q in enumerate(pts))),
         'SYMS': (np_ * 8, sum(s << (8 * k) for k, s in enumerate(syms))), 'OREG': rng.randint(0, 1)}
    check('grv_const_decoder', p, [[rnd_sample(rng, iw, True) for _ in range(120)]], iw, True, 8, False, osigned=False, rng=rng)


@test('grv_bitops')
def t_bitops(rng):
    mode = rng.randint(0, 5)
    ln = rng.randint(2, 30)
    p = {'MODE': mode, 'MODULUS': rng.choice([2, 4, 8, 3, 5]), 'MASK': rng.getrandbits(ln + 1), 'SEED': rng.getrandbits(ln + 1),
         'LEN': ln, 'COUNT': rng.choice([0, 7, 32]), 'CODE': rng.getrandbits(ln), 'THR': rng.randint(0, 3), 'OREG': rng.randint(0, 1)}
    if mode in (0, 1):
        ins = [[rng.randint(0, p['MODULUS'] - 1) for _ in range(300)]]
    else:
        ins = [[rng.getrandbits(1) for _ in range(300)]]
        if mode == 5:   # plant the code a few times
            code = [(p['CODE'] >> (ln - 1 - i)) & 1 for i in range(ln)]
            for at in (20, 120, 200):
                ins[0][at:at + ln] = code
            ins[0] = ins[0][:300]
    check('grv_bitops', p, ins, 8, False, 8, False, osigned=False, isigned=False, rng=rng)


def hann(n, N):
    return 0.5 - 0.5 * math.cos(2 * math.pi * n / (N - 1))


@test('grv_fft')
def t_fft(rng):
    N = rng.choice([8, 16, 64, 256])
    iw, ic = rng.randint(8, 16), rng.random() < 0.8
    win = rng.randint(0, 1)
    ww = 18
    p = {'N': N, 'IW': iw, 'ICPLX': int(ic), 'DW': iw + 1, 'FWD': rng.randint(0, 1), 'WIN': win, 'WW': ww,
         'WINDOW': (N * ww, sum(to_u(int(round(hann(n, N) * 131071)), ww) << (n * ww) for n in range(N))),
         'WSH': 17, 'SHIFTED': rng.randint(0, 1), 'OW': rng.randint(10, 18), 'ROUND': rng.randint(0, 3), 'SAT': 1,
         'OREG': rng.randint(0, 1)}
    p['SHIFT'] = p['DW'] - p['OW']
    frames = 3
    # tones plus noise
    ins = []
    a = (1 << (iw - 2))
    f1, f2 = rng.randint(0, N - 1), rng.randint(0, N - 1)
    for n in range(N * frames):
        v = a * cmath.exp(2j * math.pi * f1 * n / N) + a * 0.5 * cmath.exp(2j * math.pi * f2 * n / N)
        s = (int(v.real) + rng.randint(-3, 3), int(v.imag) + rng.randint(-3, 3))
        ins.append(s if ic else s[0])
    check('grv_fft', p, [ins], iw, ic, p['OW'], True, rng=rng)
    # sanity: the model against a float DFT (scaled by 1/N), no window, forward
    from grv.models import MODELS
    q = dict(p, WIN=0, FWD=1, SHIFTED=0, OW=p['DW'], SHIFT=0)
    out, _ = MODELS['grv_fft'](q, [ins[:N]], [[0] * N], {})
    x = [complex(*(s if ic else (s, 0))) for s in ins[:N]]
    X = [sum(x[n] * cmath.exp(-2j * math.pi * k * n / N) for n in range(N)) / N for k in range(N)]
    err = max(abs(complex(*out[0][k]) - X[k]) for k in range(N))
    assert err < 2 + 0.6 * math.log2(N), f'FFT model error {err:.2f} LSB'
