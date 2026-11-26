"""Tests of the CORDIC vectoring blocks (magnitude, argument, quadrature demodulator)."""
import math
from tbutil import test, check, rnd_sample
from grv.fx import cordic_gain


@test('grv_cordic_vec')
def t_cv(rng):
    iw = rng.randint(4, 18)
    pre = rng.randint(0, 1)
    if pre:
        pw = rng.randint(iw, 2 * iw + 1)
        psh = 2 * iw + 1 - pw
    else:
        pw, psh = iw, 0
    it = rng.randint(4, min(pw + 2, 24))
    kw = 18
    p = {'IW': iw, 'PRE': pre, 'PW': pw, 'PSH': psh, 'ITER': it, 'PIPE': rng.randint(0, 1), 'OUTSEL': rng.randint(0, 2),
         'KW': kw, 'KINV': int(round(2 ** 17 / cordic_gain(it))), 'MSHIFT': rng.randint(10, 20 + pw),
         'ZB': rng.randint(8, 30), 'CW': 20, 'C': int(round(math.pi * 2 ** 17)), 'OW': rng.randint(4, 24),
         'ROUND': rng.randint(0, 3), 'SAT': rng.randint(0, 2), 'OREG': rng.randint(0, 1)}
    p['ASHIFT'] = p['ZB'] - 1 + 17 - (p['OW'] - 3)
    no = 2 if p['OUTSEL'] == 2 else 1
    ins = [[rnd_sample(rng, iw, True) for _ in range(200)]]
    check('grv_cordic_vec', p, ins, iw, True, p['OW'], False, rng=rng)
