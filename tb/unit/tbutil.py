"""Runs the unit tests of the OpenGRV modules: each test draws random parameters and samples,
simulates the module with random handshake timing and compares every output sample (and tlast)
with the bit-exact model in grvgen/grv/models.py.
"""
import os, sys, random

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'grvgen'))
sys.path.insert(0, HERE)
import harness
from grv.models import MODELS
from grv.fx import pack, unpack

TESTS = {}


def test(name):
    def deco(f):
        TESTS[name] = f
        return f
    return deco


def rnd_sample(rng, w, cplx, signed=True):
    lo, hi = (-(1 << (w - 1)), (1 << (w - 1)) - 1) if signed else (0, (1 << w) - 1)
    def one():
        r = rng.random()
        if r < 0.05:
            return lo
        if r < 0.1:
            return hi
        return rng.randint(lo, hi)
    return (one(), one()) if cplx else one()


def check(module, p, ins, iw, icplx, ow, ocplx, nout=None, lasts=None, cfg=None, hwcfg=None, src=False,
          osigned=True, isigned=True, rng=None, mcfg=None, vp=70, rp=70, extra=''):
    """simulate and compare. ins: list of sample lists (model values)."""
    rng = rng or random.Random(0)
    lasts = lasts or [[int(rng.random() < 0.1) for _ in x] for x in ins]
    mc = dict(mcfg or {})
    want, wl = MODELS[module](p, ins, lasts, mc)
    nout = nout or [len(w) for w in want]
    packed = [[pack(v, iw, icplx) for v in x] for x in ins]
    iwt = iw * (2 if icplx else 1)
    owt = ow * (2 if ocplx else 1)
    outs, louts = harness.run(module, p, packed, lasts, nout, iwt, owt, cfg=hwcfg, run_src=src,
                              vp=vp, rp=rp, seed=rng.randint(1, 1 << 30), extra_ports=extra,
                              ni=len(ins), no=len(nout))
    for k in range(len(nout)):
        got = [unpack(u, ow, ocplx, osigned) for u in outs[k]]
        exp = want[k][:nout[k]]
        if len(got) < len(exp):
            raise AssertionError(f'port {k}: {len(got)} of {len(exp)} samples')
        for i, (g, e) in enumerate(zip(got, exp)):
            if g != e:
                raise AssertionError(f'port {k} sample {i}: got {g} expected {e}  (params {p})')
        el = wl[k][:nout[k]]
        if louts[k][:len(el)] != el:
            i = next(i for i, (a, b) in enumerate(zip(louts[k], el)) if a != b)
            raise AssertionError(f'port {k} tlast {i}: got {louts[k][i]} expected {el[i]}')
    return True


