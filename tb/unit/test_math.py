"""Tests of the arithmetic blocks."""
from tbutil import test, check, rnd_sample


def common(rng, p, iw):
    p.update(SHIFT=rng.randint(-2, 2 * iw + 2), ROUND=rng.randint(0, 3), SAT=rng.randint(0, 2), OREG=rng.randint(0, 1))
    return p


@test('grv_add')
def t_add(rng):
    ni, iw, c = rng.randint(1, 4), rng.randint(2, 24), rng.random() < 0.4
    sh = [rng.randint(0, 6) for _ in range(ni)]
    p = common(rng, {'NI': ni, 'IW': iw, 'CPLX': int(c), 'OW': rng.randint(2, 28),
                     'SHIFT_IN': (6 * ni, sum(s << (6 * k) for k, s in enumerate(sh))), 'SUB': rng.randint(0, 1)}, iw)
    p['SHIFT'] = rng.randint(-2, iw + 6)
    ins = [[rnd_sample(rng, iw, c) for _ in range(250)] for _ in range(ni)]
    check('grv_add', p, ins, iw, c, p['OW'], c, rng=rng)


@test('grv_multiply')
def t_mult(rng):
    iw, c = rng.randint(2, 18), rng.random() < 0.5
    p = common(rng, {'IW': iw, 'CPLX': int(c), 'CONJ': rng.randint(0, 1) if c else 0, 'OW': rng.randint(2, 30)}, iw)
    ins = [[rnd_sample(rng, iw, c) for _ in range(250)] for _ in range(2)]
    check('grv_multiply', p, ins, iw, c, p['OW'], c, rng=rng)


@test('grv_multiply_const')
def t_mconst(rng):
    iw, kw = rng.randint(2, 18), rng.randint(2, 18)
    ic, kc = rng.random() < 0.5, rng.random() < 0.5
    p = common(rng, {'IW': iw, 'ICPLX': int(ic), 'KW': kw, 'KCPLX': int(kc), 'OW': rng.randint(2, 30)}, iw)
    k = rnd_sample(rng, kw, kc)
    from grv.fx import pack
    ins = [[rnd_sample(rng, iw, ic) for _ in range(250)]]
    check('grv_multiply_const', p, ins, iw, ic, p['OW'], ic or kc, rng=rng,
          hwcfg={'cfg_k': (kw * (2 if kc else 1), pack(k, kw, kc))}, mcfg={'k': k})


@test('grv_add_const')
def t_aconst(rng):
    iw, kw, c = rng.randint(2, 24), rng.randint(2, 24), rng.random() < 0.4
    p = common(rng, {'IW': iw, 'CPLX': int(c), 'KW': kw, 'XSH': rng.randint(0, 8), 'KSH': rng.randint(0, 8),
                     'OW': rng.randint(2, 30)}, iw)
    p['SHIFT'] = rng.randint(-2, iw + 8)
    k = rnd_sample(rng, kw, c)
    from grv.fx import pack
    ins = [[rnd_sample(rng, iw, c) for _ in range(250)]]
    check('grv_add_const', p, ins, iw, c, p['OW'], c, rng=rng, hwcfg={'cfg_k': (kw * (2 if c else 1), pack(k, kw, c))}, mcfg={'k': k})


@test('grv_elem')
def t_elem(rng):
    op = rng.randint(0, 3)
    iw = rng.randint(2, 20)
    c = True if op in (0, 2) else rng.random() < 0.5
    p = common(rng, {'OP': op, 'IW': iw, 'CPLX': int(c), 'OW': rng.randint(2, 30)}, iw)
    if op == 0:
        p['OW'] = iw
    oc = op == 0 or (op in (1, 3) and c)
    ins = [[rnd_sample(rng, iw, c) for _ in range(250)]]
    check('grv_elem', p, ins, iw, c, p['OW'], oc, rng=rng)
