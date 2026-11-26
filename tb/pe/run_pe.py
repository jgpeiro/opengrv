#!/usr/bin/env python3
"""Unit tests of the peripheral endpoints and of the DMA engine (Icarus Verilog).
    python3 tb/pe/run_pe.py [-k NAME] [-j JOBS]"""
import os, sys, subprocess, itertools, argparse
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
RTL = os.path.join(HERE, '..', '..', 'rtl')
LIBS = ['-y', os.path.join(RTL, 'periph'), '-y', os.path.join(RTL, 'prim'), '-y', os.path.join(RTL, 'dma'),
        '-I', HERE, '-I', os.path.join(RTL, 'inc')]
CASES = []


def case(tb, **params):
    CASES.append((tb, params))


# ---------------------------------------------------------------- UART
for w, nc in ((8, 1), (16, 1), (12, 1), (32, 2), (24, 1)):
    for fmt in (0x0, 0x1, 0x6, 0x8, 0x0300, 0x0310, 0x22):
        for timing in (2560, 4864, 2688):
            if timing != 2560 and fmt not in (0x0, 0x0300):
                continue
            case('tb_uart', W=w, NC=nc, FORMAT=fmt, TIMING=timing, SEED=w + fmt + timing)
for w in (8, 16, 20):
    case('tb_uart', W=w, NC=1, FORMAT=0x40, TIMING=2560, N=40, SEED=w)
    case('tb_uart', W=w, NC=1, FORMAT=0x41, TIMING=2560, N=40, SEED=w + 1)

# ---------------------------------------------------------------- SPI
for db, fb, dpos in ((12, 16, 0), (12, 24, 4), (8, 8, 0), (16, 16, 0), (10, 32, 20)):
    for mode in range(4):
        for extra in (0, 1 << 18, 1 << 19):
            fmt = (fb - 1) | (dpos << 8) | (mode << 16) | extra
            for ncb in (1, 2):
                if ncb == 2 and (mode, extra) not in ((0, 0), (3, 1 << 18)):
                    continue
                case('tb_spi', DB=db, NCB=ncb, FORMAT=fmt, HALF=3 + (mode & 1) * 2, SEED=db + fmt + ncb)

# ---------------------------------------------------------------- GPIO
for test in range(5):
    for db, nc in ((8, 1), (4, 2), (12, 1), (1, 1), (6, 2)):
        if db == 1 and test in (3, 4):
            continue
        for ofs in (0, 1):
            if test == 4:
                for o1, div in ((0, 0), (1, 0), (0, 2)):
                    case('tb_gpio', TEST=test, DB=db, NC=nc, OFS=ofs, ORD1=o1, DIV=div, SEED=db + 7 * nc + ofs)
            else:
                case('tb_gpio', TEST=test, DB=db, NC=nc, OFS=ofs, SEED=db + 7 * nc + ofs + test)

# ---------------------------------------------------------------- I2S
for test in (0, 1):
    for just, slot, db in ((0, 16, 16), (0, 32, 24), (0, 32, 32), (1, 32, 24), (1, 16, 16), (2, 32, 20), (2, 24, 16)):
        for nc in (1, 2):
            case('tb_i2s', TEST=test, JUST=just, SLOT=slot, DB=db, NC=nc, SEED=slot + db + nc + test)
    for nc, mono_r, dup, wsinv, half in ((1, 1, 0, 0, 1280), (1, 0, 1, 0, 1152), (1, 1, 1, 1, 1408), (2, 0, 0, 1, 1088)):
        case('tb_i2s', TEST=test, JUST=0, SLOT=32, DB=24, NC=nc, MONO_R=mono_r, DUP=dup, WSINV=wsinv, HALF=half,
             SEED=7 + nc + mono_r + dup + test)

# ---------------------------------------------------------------- DMA
for cw, nc, cb in ((8, 1, 1), (16, 1, 2), (12, 1, 2), (16, 2, 2), (8, 2, 1), (24, 1, 4), (32, 1, 4), (20, 2, 4), (6, 2, 1)):
    for mode in range(6):
        for msba in (0, 1):
            if msba and mode not in (0, 1, 5):
                continue
            case('tb_dma', MODE=mode, CW=cw, NC=nc, CB=cb, MSBA=msba, LAT=1 + (cw % 5), SEED=cw + nc + mode)
for burst, gap, lat in ((3, 0, 1), (0, 4, 2), (15, 10, 3)):
    for mode in (0, 1, 2):
        case('tb_dma', MODE=mode, CW=16, NC=1, CB=2, BURST=burst, GAP=gap, LAT=lat, SEED=burst + gap)


def run(tb, params):
    name = tb + '_' + '_'.join(f'{k}{v:x}' if isinstance(v, int) else f'{k}{v}' for k, v in params.items())
    out = f'/tmp/pe_{name}.vvp'
    args = ['iverilog', '-g2005', '-o', out] + [f'-P{tb}.{k}={v}' for k, v in params.items()] + LIBS + \
           [os.path.join(HERE, tb + '.v')]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode:
        return name, False, r.stderr[-2000:]
    r = subprocess.run(['vvp', '-n', out], capture_output=True, text=True, cwd=HERE)
    os.remove(out)
    ok = 'PASS' in r.stdout and 'FAIL' not in r.stdout
    return name, ok, r.stdout[-1500:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-k', default='')
    ap.add_argument('-j', type=int, default=8)
    a = ap.parse_args()
    cs = [(t, p) for t, p in CASES if not a.k or any(k in t for k in a.k.split(','))]
    fails = 0
    with ThreadPoolExecutor(a.j) as ex:
        for name, ok, msg in ex.map(lambda c: run(*c), cs):
            if not ok:
                fails += 1
                print('FAIL', name, '\n   ', msg.replace('\n', '\n    '))
    print(f'{len(cs) - fails} passed, {fails} failed')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
