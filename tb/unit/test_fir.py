"""Tests of grv_fir: parallel and folded engines, symmetric taps, decimation, interpolation,
rational resampling, real and complex data and taps."""
from tbutil import test, check, rnd_sample
from grv.models import pack_taps


def fir_params(rng, par):
    ic, cc = rng.random() < 0.5, rng.random() < 0.3
    iw, cw = rng.randint(4, 18), rng.randint(4, 18)
    n = rng.randint(1, 24 if par else 70)
    L = rng.choice([1, 1, 1, 2, 3, 4])
    M = rng.choice([1, 1, 2, 3, 5])
    sym = int(L == 1 and rng.random() < 0.5)
    taps = [rnd_sample(rng, cw, cc) for _ in range(n)]
    if sym:
        for k in range(n // 2):
            taps[n - 1 - k] = taps[k]
    p = {'IW': iw, 'ICPLX': int(ic), 'CW': cw, 'CCPLX': int(cc), 'NTAPS': n, 'COEFS': pack_taps(taps, cw, cc),
         'L': L, 'M': M, 'LANES': 0 if par else rng.randint(1, 3), 'SYM': sym, 'OW': rng.randint(4, 24),
         'ROUND': rng.randint(0, 3), 'SAT': rng.randint(0, 2), 'OREG': rng.randint(0, 1)}
    p['SHIFT'] = rng.randint(cw - 4, iw + cw)
    return p, iw, ic, ic or cc


@test('grv_fir_par')
def t_fir_par(rng):
    p, iw, ic, oc = fir_params(rng, True)
    check('grv_fir', p, [[rnd_sample(rng, iw, ic) for _ in range(160)]], iw, ic, p['OW'], oc, rng=rng)


@test('grv_fir_fold')
def t_fir_fold(rng):
    p, iw, ic, oc = fir_params(rng, False)
    check('grv_fir', p, [[rnd_sample(rng, iw, ic) for _ in range(120)]], iw, ic, p['OW'], oc, rng=rng)
