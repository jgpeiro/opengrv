"""Tests of the handshake primitives and grv_convert (grv_resize)."""
from tbutil import test, check, rnd_sample


@test('grv_skid')
def t_skid(rng):
    w = rng.randint(1, 40)
    ins = [[rnd_sample(rng, w, False) for _ in range(300)]]
    check('grv_skid', {'W': w}, ins, w, False, w, False, vp=rng.choice([30, 70, 100]), rp=rng.choice([30, 70, 100]), rng=rng)


@test('grv_fifo')
def t_fifo(rng):
    w = rng.randint(1, 36)
    depth = rng.choice([2, 4, 16, 64, 512])
    ins = [[rnd_sample(rng, w, False) for _ in range(400)]]
    check('grv_fifo', {'W': w, 'DEPTH': depth}, ins, w, False, w, False, vp=rng.choice([30, 90]), rp=rng.choice([20, 90]), rng=rng)


@test('grv_fork')
def t_fork(rng):
    w, n = rng.randint(1, 32), rng.randint(1, 4)
    ins = [[rnd_sample(rng, w, False) for _ in range(300)]]
    check('grv_fork', {'W': w, 'N': n}, ins, w, False, w, False, rng=rng)


@test('grv_convert')
def t_convert(rng):
    iw = rng.randint(2, 32)
    ow = rng.randint(2, 32)
    c = rng.random() < 0.3
    isg = rng.random() < 0.8
    osg = rng.random() < 0.8
    p = {'IW': iw, 'CPLX': int(c), 'ISIGNED': int(isg), 'OW': ow, 'OSIGNED': int(osg),
         'SHIFT': rng.randint(-4, iw + 6), 'ROUND': rng.randint(0, 3), 'SAT': rng.randint(0, 2 if osg else 1),
         'OREG': rng.randint(0, 1)}
    if rng.random() < 0.4:
        kw = rng.randint(2, 18)
        p.update(MULK=1, KW=kw, K=rng.randint(-(1 << (kw - 1)), (1 << (kw - 1)) - 1))
    ins = [[rnd_sample(rng, iw, c, isg) for _ in range(300)]]
    check('grv_convert', p, ins, iw, c, ow, c, osigned=osg, rng=rng)
