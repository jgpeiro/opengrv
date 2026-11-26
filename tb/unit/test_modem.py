"""Tests of the modulation and synchronisation blocks."""
import math
from tbutil import test, check, rnd_sample


@test('grv_fm_mod')
def t_fm(rng):
    iw, kw = rng.randint(4, 18), rng.randint(4, 24)
    p = {'IW': iw, 'KW': kw, 'KSH': rng.randint(0, 10), 'PM': rng.randint(0, 1), 'OW': rng.randint(4, 18),
         'ROUND': rng.randint(0, 3), 'SAT': rng.randint(0, 2), 'OREG': rng.randint(0, 1)}
    p['SHIFT'] = 18 - p['OW'] + rng.randint(0, 2)
    k = rng.randint(-(1 << (kw - 1)), (1 << (kw - 1)) - 1)
    check('grv_fm_mod', p, [[rnd_sample(rng, iw, False) for _ in range(300)]], iw, False, p['OW'], True, rng=rng,
          hwcfg={'cfg_k': (kw, k)}, mcfg={'k': k})


@test('grv_agc')
def t_agc(rng):
    iw, c = rng.randint(6, 16), rng.random() < 0.6
    gw, ow, rw = 24, rng.randint(8, 16), rng.randint(8, 18)
    p = {'IW': iw, 'CPLX': int(c), 'GW': gw, 'G0': 1 << 16, 'OW': ow, 'SHIFT': 16 + iw - ow, 'RW': rw,
         'RSH': rng.randint(4, 16), 'MAXEN': rng.randint(0, 1), 'ROUND': rng.randint(0, 3), 'SAT': rng.randint(1, 2), 'OREG': rng.randint(0, 1)}
    cfg = {'rate': rng.randint(0, (1 << rw) - 1) >> rng.randint(0, 6), 'ref': rng.randint(1, (1 << (ow - 1)) - 1),
           'max': rng.randint(1 << 16, (1 << (gw - 1)) - 1)}
    check('grv_agc', p, [[rnd_sample(rng, iw, c) for _ in range(250)]], iw, c, ow, c, rng=rng,
          hwcfg={'cfg_rate': (rw, cfg['rate']), 'cfg_ref': (ow, cfg['ref']), 'cfg_max': (gw, cfg['max'])}, mcfg=cfg)


@test('grv_squelch')
def t_sq(rng):
    iw, c = rng.randint(4, 14), rng.random() < 0.7
    g, aw = rng.randint(0, 6), rng.randint(4, 18)
    p = {'IW': iw, 'CPLX': int(c), 'G': g, 'AW': aw, 'AF': aw - 1, 'GATE': rng.randint(0, 1), 'OREG': rng.randint(0, 1)}
    a = rng.randint(1, 1 << (aw - 1))
    thr = rng.randint(0, 1 << (2 * iw - 2 + g))
    # bursts of strong and weak samples so the squelch opens and closes
    ins = []
    for b in range(10):
        amp = iw if b % 2 else max(2, iw // 3)
        ins += [rnd_sample(rng, amp, c) for _ in range(30)]
    from grv.models import MODELS
    want, _ = MODELS['grv_squelch'](p, [ins], [[0] * len(ins)], {'alpha': a, 'thr': thr})
    check('grv_squelch', p, [ins], iw, c, iw, c, nout=[len(want[0])], rng=rng,
          hwcfg={'cfg_alpha': (aw, a), 'cfg_thr': (2 * iw + g + 2, thr)}, mcfg={'alpha': a, 'thr': thr})


@test('grv_costas')
def t_costas(rng):
    iw, ow = rng.randint(8, 16), rng.randint(8, 16)
    order = rng.choice([2, 4])
    ew, ef = 18, 15
    p = {'IW': iw, 'OW': ow, 'SHIFT': 17 + iw - ow, 'ORDER': order, 'EW': ew, 'EF': ef,
         'SHE': (2 * (ow - 1) - ef) if order == 2 else (ow - 1 - ef), 'KW': 24, 'SA': 15, 'SB': 15,
         'FMAX': 683565276, 'ROUND': rng.randint(0, 3), 'SAT': rng.randint(1, 2), 'OREG': rng.randint(0, 1)}
    bw = rng.uniform(0.005, 0.1)
    d = 1 + 2 * 0.7071 * bw + bw * bw
    alpha, beta = 4 * 0.7071 * bw / d, 4 * bw * bw / d
    ka = int(round(alpha / (2 * math.pi) * 2 ** (32 + 15 - ef)))
    kb = int(round(beta / (2 * math.pi) * 2 ** (32 + 15 - ef)))
    ka, kb = min(ka, (1 << 23) - 1), min(kb, (1 << 23) - 1)
    # a BPSK / QPSK signal with a frequency offset
    f = rng.uniform(-0.05, 0.05)
    ins = []
    a = (1 << (iw - 1)) * 0.7
    for n in range(200):
        s = rng.choice([1, -1]) + (1j * rng.choice([1, -1]) if order == 4 else 0)
        v = s * a / (abs(s)) * complex(math.cos(f * n), math.sin(f * n))
        ins.append((int(v.real), int(v.imag)))
    check('grv_costas', p, [ins], iw, True, ow, True, rng=rng,
          hwcfg={'cfg_ka': (24, ka), 'cfg_kb': (24, kb)}, mcfg={'ka': ka, 'kb': kb})


@test('grv_dc_blocker')
def t_dc(rng):
    iw, c = rng.randint(4, 16), rng.random() < 0.4
    d = rng.choice([2, 3, 4, 8, 16, 32])
    lg = math.ceil(math.log2(d * d))
    p = {'IW': iw, 'CPLX': int(c), 'D': d, 'KW': 18, 'K': (1 if (d & (d - 1)) == 0 else int(round(2 ** 17 / (d * d)))),
         'OW': rng.randint(4, 20), 'ROUND': rng.randint(0, 3), 'SAT': rng.randint(0, 2), 'OREG': rng.randint(0, 1)}
    p['SHIFT'] = (2 * int(math.log2(d)) if p['K'] == 1 else 17) + rng.randint(-2, 2)
    check('grv_dc_blocker', p, [[rnd_sample(rng, iw, c) for _ in range(300)]], iw, c, p['OW'], c, rng=rng)
