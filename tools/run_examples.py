#!/usr/bin/env python3
"""Generates and simulates the examples of examples/examples.json against their graph models, and
copies the generated top level, header, report and pin template into examples/<name>/generated.
    python3 tools/run_examples.py [-k NAME] [-j JOBS] [--no-copy]"""
import os, sys, json, shutil, subprocess, argparse, time
from concurrent.futures import ThreadPoolExecutor
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(name, meta, copy):
    t0 = time.time()
    out = os.path.join(ROOT, 'build', 'ex', name)
    shutil.rmtree(out, ignore_errors=True)
    grc = os.path.join(ROOT, 'examples', name, name + '.grc')
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'grvgen', 'grvgen.py'), grc, '-o', out, '-q'],
                       capture_output=True, text=True)
    if r.returncode:
        return name, False, r.stderr[-1500:], 0
    top = name + '_top'
    args = [os.path.join(out, top + '_sim.sh'), '-n', str(meta['n'])]
    for k, v in meta['params'].items():
        args += ['--param', f'{k}={v}']
    r = subprocess.run(args + meta['args'], capture_output=True, text=True, cwd=out)
    lines = [l for l in r.stdout.splitlines() if 'samples,' in l or 'sdm ' in l or 'MISMATCH' in l or 'ERROR' in l]
    ok = r.returncode == 0 and r.stdout.rstrip().endswith('PASS')
    if ok and copy:
        g = os.path.join(ROOT, 'examples', name, 'generated')
        shutil.rmtree(g, ignore_errors=True)
        os.makedirs(g)
        for f in (top + '.v', top + '_regs.h', top + '_report.md', top + '_pins.cst'):
            if os.path.exists(os.path.join(out, f)):
                shutil.copy(os.path.join(out, f), g)
    return name, ok, '\n'.join(lines[-12:]) if lines else r.stdout[-1500:] + r.stderr[-800:], time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-k', default='')
    ap.add_argument('-j', type=int, default=4)
    ap.add_argument('--no-copy', action='store_true')
    a = ap.parse_args()
    meta = json.load(open(os.path.join(ROOT, 'examples', 'examples.json')))
    names = [n for n in meta if not a.k or any(k in n for k in a.k.split(','))]
    with ThreadPoolExecutor(a.j) as ex:
        res = list(ex.map(lambda n: run(n, meta[n], not a.no_copy), names))
    npass = 0
    for name, ok, txt, dt in res:
        print(f'{"PASS" if ok else "FAIL"} {name}: {dt:.0f} s')
        print('    ' + txt.replace('\n', '\n    '))
        npass += ok
    print(f'{npass} / {len(res)} examples passed')
    sys.exit(0 if npass == len(res) else 1)


if __name__ == '__main__':
    main()
