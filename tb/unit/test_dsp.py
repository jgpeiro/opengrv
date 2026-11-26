"""Tests of the mixer, frequency-translating FIR, single-pole IIR and CIC filters."""
import math
from tbutil import test, check, rnd_sample
from grv.models import pack_taps


@test('grv_mixer')
def t_mixer(rng):
    iw, ic = rng.randint(4, 18), rng.random() < 0.7
    p = {'IW': iw, 'ICPLX': int(ic), 'OW': rng.randint(4, 24), 'SHIFT': rng.randint(8, 22), 'ROUND': rng.randint(0, 3),
         'SAT': rng.randint(0, 2), 'OREG': rng.randint(0, 1)}
    f = rng.getrandbits(32)
    check('grv_mixer', p, [[rnd_sample(rng, iw, ic) for _ in range(300)]], iw, ic, p['OW'], True, rng=rng,
          hwcfg={'cfg_freq': (32, f)}, mcfg={'freq': f})


@test('grv_xlating_fir')
def t_xlate(rng):
    iw, ic, cc = rng.randint(4, 16), rng.random() < 0.8, rng.random() < 0.3
    n, cw = rng.randint(1, 30), rng.randint(6, 18)
    taps = [rnd_sample(rng, cw, cc) for _ in range(n)]
    sym = int(rng.random() < 0.5)
    if sym:
        for k in range(n // 2):
            taps[n - 1 - k] = taps[k]
    p = {'IW': iw, 'ICPLX': int(ic), 'MW': rng.randint(6, 18), 'SHIFT_MIX': rng.randint(14, 20), 'CW': cw, 'CCPLX': int(cc),
         'NTAPS': n, 'COEFS': pack_taps(taps, cw, cc), 'DECIM': rng.randint(1, 4), 'LANES': rng.randint(0, 2), 'SYM': sym,
         'OW': rng.randint(6, 20), 'SHIFT': rng.randint(cw - 3, cw + 6), 'ROUND': rng.randint(0, 3), 'SAT': rng.randint(1, 2), 'OREG': 1}
    f = rng.getrandbits(32)
    check('grv_xlating_fir', p, [[rnd_sample(rng, iw, ic) for _ in range(200)]], iw, ic, p['OW'], True, rng=rng,
          hwcfg={'cfg_freq': (32, f)}, mcfg={'freq': f})


@test('grv_iir1')
def t_iir1(rng):
    iw, c = rng.randint(4, 18), rng.random() < 0.4
    aw = rng.randint(4, 18)
    p = {'IW': iw, 'CPLX': int(c), 'G': rng.randint(0, 10), 'AW': aw, 'AF': aw - 1, 'OW': rng.randint(4, 20),
         'ROUND': rng.randint(0, 3), 'SAT': rng.randint(0, 2), 'OREG': rng.randint(0, 1)}
    p['SHIFT'] = rng.randint(0, p['G'] + 4)
    a = rng.randint(0, 1 << (aw - 1))
    check('grv_iir1', p, [[rnd_sample(rng, iw, c) for _ in range(200)]], iw, c, p['OW'], c, rng=rng,
          hwcfg={'cfg_alpha': (aw, a)}, mcfg={'alpha': a})


@test('grv_cic')
def t_cic(rng):
    dec, iw, c = rng.randint(0, 1), rng.randint(4, 16), rng.random() < 0.4
    n, r, md = rng.randint(1, 5), rng.randint(1, 8), rng.randint(1, 2)
    gw = iw + math.ceil(n * math.log2(r * md)) + 2
    p = {'DECIM': dec, 'IW': iw, 'CPLX': int(c), 'N': n, 'R': r, 'MD': md, 'GW': gw, 'OW': rng.randint(4, 24),
         'ROUND': rng.randint(0, 3), 'SAT': rng.randint(0, 2), 'OREG': rng.randint(0, 1)}
    p['SHIFT'] = rng.randint(0, gw - iw)
    check('grv_cic', p, [[rnd_sample(rng, iw, c) for _ in range(160 if not dec else 300)]], iw, c, p['OW'], c, rng=rng)
