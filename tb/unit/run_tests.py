#!/usr/bin/env python3
"""Runs the unit tests of the OpenGRV modules (tb/unit/test_*.py): each test draws random
parameters and samples, simulates the module with random handshake timing and compares every
output sample and tlast with the bit-exact model.
usage: run_tests.py [-k PATTERN] [-n ITERATIONS] [-j JOBS]"""
import os, sys, random, argparse, traceback, time, importlib, glob
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from tbutil import TESTS
for f in sorted(glob.glob(os.path.join(HERE, 'test_*.py'))):
    importlib.import_module(os.path.basename(f)[:-3])


def one(args):
    name, it = args
    rng = random.Random((sum(map(ord, name)) * 7919 + it * 104729) & 0xFFFFFFFF)
    t0 = time.time()
    try:
        TESTS[name](rng)
        return name, it, None, time.time() - t0
    except Exception as e:
        return name, it, ''.join(traceback.format_exception_only(type(e), e)).strip()[:3000], time.time() - t0


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('-k', default='')
    ap.add_argument('-n', type=int, default=4)
    ap.add_argument('-j', type=int, default=os.cpu_count())
    a = ap.parse_args()
    names = [n for n in TESTS if any(k in n for k in a.k.split(','))]
    jobs = [(n, i) for n in names for i in range(a.n)]
    fails = 0
    with ProcessPoolExecutor(a.j) as ex:
        for name, it, err, dt in ex.map(one, jobs):
            if err:
                fails += 1
                print(f'FAIL {name}[{it}] {dt:.1f}s\n  {err}')
            else:
                print(f'ok   {name}[{it}] {dt:.1f}s')
    print(f'{len(jobs) - fails} passed, {fails} failed')
    sys.exit(1 if fails else 0)
