"""Tests of the source blocks (raw packed outputs where the samples are not in a fixed format)."""
from tbutil import test, check, rnd_sample
from grv.fx import wrap


@test('grv_sig_source')
def t_sig(rng):
    c = rng.random() < 0.4
    wave = rng.choice([0, 1, 2]) if c else rng.randint(0, 5)
    ow, aw = rng.randint(4, 24), rng.randint(4, 18)
    ofw = rng.randint(2, 18)
    p = {'OW': ow, 'CPLX': int(c), 'WAVE': wave, 'AW': aw, 'OFW': ofw, 'OFSH': rng.randint(0, 20),
         'PHASE0': rng.getrandbits(32), 'SHIFT': rng.randint(10, 30), 'ROUND': rng.randint(0, 3),
         'SAT': rng.randint(0, 2), 'OREG': rng.randint(0, 1)}
    cfg = {'freq': rng.getrandbits(32) if rng.random() < 0.7 else rng.getrandbits(24),
           'amp': rng.randint(-(1 << (aw - 1)), (1 << (aw - 1)) - 1),
           'offset': rng.randint(-(1 << (ofw - 1)), (1 << (ofw - 1)) - 1),
           'offset_q': rng.randint(-(1 << (ofw - 1)), (1 << (ofw - 1)) - 1)}
    n = 400
    hw = {'cfg_freq': (32, cfg['freq']), 'cfg_amp': (aw, cfg['amp']), 'cfg_offset': (ofw, cfg['offset']),
          'cfg_offset_q': (ofw, cfg['offset_q'])}
    check('grv_sig_source', p, [], 0, False, ow, c, nout=[n], hwcfg=hw, src=True, mcfg=dict(cfg, _n=n), rng=rng)


@test('grv_noise_source')
def t_noise(rng):
    c = rng.random() < 0.5
    ow, aw = rng.randint(4, 24), rng.randint(4, 18)
    p = {'OW': ow, 'CPLX': int(c), 'TYPE': rng.randint(0, 1), 'SEED': rng.getrandbits(32), 'AW': aw,
         'SHIFT': rng.randint(10, 30), 'ROUND': rng.randint(0, 3), 'SAT': rng.randint(0, 2), 'OREG': rng.randint(0, 1)}
    amp = rng.randint(-(1 << (aw - 1)), (1 << (aw - 1)) - 1)
    n = 300
    check('grv_noise_source', p, [], 0, False, ow, c, nout=[n], hwcfg={'cfg_amp': (aw, amp)}, src=True,
          mcfg={'amp': amp, '_n': n}, rng=rng)


@test('grv_const_source')
def t_const(rng):
    c = rng.random() < 0.5
    ow = rng.randint(1, 32)
    val = rng.getrandbits(ow * (2 if c else 1))
    check('grv_const_source', {'OW': ow, 'CPLX': int(c), 'OREG': rng.randint(0, 1)}, [], 0, False, ow, c,
          nout=[50], hwcfg={'cfg_value': (ow * (2 if c else 1), val)}, src=True, mcfg={'value': val, '_n': 50}, rng=rng)


@test('grv_vector_rom')
def t_vrom(rng):
    sw, n = rng.randint(1, 36), rng.randint(1, 70)
    vec = rng.getrandbits(sw * n)
    rep = rng.randint(0, 1)
    tot = 200 if rep else n
    p = {'SW': sw, 'N': n, 'VEC': (sw * n, vec), 'REPEAT': rep, 'VLEN': rng.choice([0, 1, 3, 8]), 'OREG': rng.randint(0, 1)}
    check('grv_vector_rom', p, [], 0, False, sw, False, nout=[tot], src=True, mcfg={'_n': tot}, osigned=False, rng=rng)


@test('grv_glfsr')
def t_glfsr(rng):
    deg = rng.randint(3, 10)
    outf = rng.randint(0, 1)
    rep = rng.randint(0, 1)
    tot = 300 if rep else (1 << deg) - 1
    p = {'DEGREE': deg, 'MASK': rng.getrandbits(deg) | (1 << (deg - 1)), 'SEED': rng.getrandbits(deg) | 1, 'REPEAT': rep,
         'OUTF': outf, 'OW': 8 if not outf else 16, 'ONE': 1 if not outf else 16384, 'OREG': rng.randint(0, 1)}
    check('grv_glfsr', p, [], 0, False, p['OW'], False, nout=[tot], src=True, mcfg={'_n': tot}, osigned=bool(outf), rng=rng)
