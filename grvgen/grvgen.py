#!/usr/bin/env python3
"""grvgen - compiles a GNU Radio Companion flowgraph (.grc) into an OpenGRV top-level module,
its C header, address map, bit-exact model, Verilator testbench and report."""
import os, sys, json, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from grv.core import Compiler, PROFILES        # noqa: E402
from grv.expr import GrvError                  # noqa: E402
from grv import emit, emit_tb                  # noqa: E402

ALL = ['verilog', 'header', 'map', 'model', 'tb', 'report', 'pins']


def parse_args(argv):
    ap = argparse.ArgumentParser(prog='grvgen.py', description=__doc__)
    ap.add_argument('graph', help='GNU Radio Companion flowgraph (.grc, format 1)')
    ap.add_argument('-o', dest='out', default='build/grv', help='output directory')
    ap.add_argument('--top', help='name of the top-level module (default: GRC id + _top)')
    ap.add_argument('--clk', type=float, default=54e6, help='stream clock in Hz')
    ap.add_argument('--dsp-clk', type=float, help='separate stream clock (not implemented yet)')
    ap.add_argument('--profile', default='q15', help='width profile (q15, q17, q11, q7) or YAML file')
    ap.add_argument('--range', dest='range_mode', default='worst', choices=['worst', 'rms'])
    ap.add_argument('--rate', action='append', default=[], metavar='BLOCK=HZ', help='rate anchor')
    ap.add_argument('--fold', default='auto', choices=['auto', 'off'])
    ap.add_argument('--slices', default='all', choices=['all', 'auto', 'none'])
    ap.add_argument('--base', default='0x60000000', help='base address written into the header')
    ap.add_argument('--map-lock', help='keep the addresses of a previous _map.json')
    ap.add_argument('--budget', help='resource limits, e.g. lut=8000,mult=20,bram=16')
    ap.add_argument('--registry', action='append', default=[], help='additional block descriptors (not implemented yet)')
    ap.add_argument('-D', dest='defines', action='append', default=[], metavar='VAR=VALUE', help='override a GRC variable')
    ap.add_argument('--emit', default='all', help='comma list of ' + ','.join(ALL + ['gprj']))
    ap.add_argument('--pad-bytes', action='store_true', help='byte-align pad components (not implemented yet)')
    ap.add_argument('--dma-window', metavar='LO:HI', help='reset value of the DMA address window (default: everything)')
    ap.add_argument('--dump', help='write the graph after the last stage as JSON to this file')
    ap.add_argument('--strict', action='store_true', help='warnings are errors')
    ap.add_argument('-q', '--quiet', action='store_true')
    return ap.parse_args(argv)


def load_profile(p):
    if p in PROFILES:
        return p
    import yaml
    d = yaml.safe_load(open(p))
    return dict(w=int(d['w']), coef=int(d.get('coef', d['w'] + 2)), gain=int(d.get('gain', d['w'] + 2)))


def budget_check(cc, spec):
    lim = {}
    for kv in spec.split(','):
        k, v = kv.split('=')
        lim[k.strip()] = int(v)
    tot = {k: sum(i.cost.get(k, 0) for i in cc.insts) for k in ('lut', 'mult', 'bram')}
    for k, v in lim.items():
        if tot.get(k, 0) > v:
            cc.diag.warn('W501', f'estimated {k} {tot[k]} exceeds the budget {v}')


def map_lock(cc, path):
    old = json.load(open(path))
    pidx = {p['name']: p['index'] for p in old.get('params', [])}
    taken = set()
    for p in cc.params:
        if p.name in pidx:
            p.index = pidx[p.name]
            taken |= set(range(p.index, p.index + p.words))
    w = 0
    for p in sorted(cc.params, key=lambda p: p.name):
        if p.name in pidx:
            continue
        while any(x in taken for x in range(w, w + p.words)):
            w += 1
        p.index = w
        taken |= set(range(w, w + p.words))
    cc.npw = max([p.index + p.words for p in cc.params] or [1])
    for key, lst in (('sources', cc.srcs), ('sinks', cc.snks), ('probes', cc.prbs), ('periph', cc.pes), ('dma', cc.dmas)):
        names = [e['name'] for e in old.get(key, [])]
        keep = [i for n in names for i in lst if i.name == n]
        rest = [i for i in lst if i not in keep]
        lst[:] = keep + rest
    cc.diag.note(f'--map-lock {path}: parameter words kept; endpoint order kept for existing names')
    # re-run the address assignment with the locked order
    for k, s in enumerate(cc.srcs):
        s.ep['index'], s.ep['addr'] = k, 0x1000 + 0x100 * k
    for k, s in enumerate(cc.snks):
        s.ep['index'], s.ep['addr'] = k, 0x2000 + 0x100 * k
        if s.ep.get('capd'):
            s.ep['window'] = 0x8000 + 0x2000 * k
    for k, s in enumerate(cc.prbs):
        s.ep['index'], s.ep['addr'] = k, 0x3000 + 8 * k
    for k, s in enumerate(cc.pes):
        s.ep['index'], s.ep['addr'] = k, 0x6000 + 0x100 * k
    for k, s in enumerate(cc.dmas):
        s.ep['index'], s.ep['addr'] = k, 0x7000 + 0x100 * k


def dump(cc, path):
    g = dict(insts=[dict(name=i.name, module=i.module, kind=i.kind, params={k: (list(v) if isinstance(v, tuple) else v)
                                                                             for k, v in i.params.items()},
                         ins=[n.name for n, _ in i.ins], outs=[n.name for n in i.outs], meta=i.meta, cost=i.cost)
                    for i in cc.insts],
             nets=[dict(name=n.name, fmt=repr(n.fmt), rng=n.rng, rate=n.rate, ratio=str(n.ratio)) for n in cc.nets])
    json.dump(g, open(path, 'w'), indent=1, default=str)


def main(argv=None):
    a = parse_args(argv if argv is not None else sys.argv[1:])
    defines = {}
    for d in a.defines:
        k, v = d.split('=', 1)
        defines[k] = v
    try:
        cc = Compiler(a.graph, clk=a.clk, profile=load_profile(a.profile), base=int(a.base, 0), top=a.top,
                      strict=a.strict, fold=a.fold, slices=a.slices, defines=defines, range_mode=a.range_mode)
        if a.dsp_clk:
            cc.diag.warn('W001', '--dsp-clk is not implemented yet: the graph runs on --clk')
        if a.range_mode == 'rms':
            cc.diag.warn('W002', '--range rms is not implemented yet: worst-case ranges are used')
        if a.registry:
            cc.diag.warn('W003', '--registry is not implemented yet')
        if a.pad_bytes:
            cc.diag.warn('W004', '--pad-bytes is not implemented yet')
        for r in a.rate:
            b, hz = r.split('=', 1)
            if b not in cc.blocks:
                raise GrvError(f'E110: --rate: no block {b}')
            cc.blocks[b].prag['rate'] = hz
        if a.dma_window:
            lo, hi = a.dma_window.split(':')
            cc.dma_window = (int(lo, 0) & 0xFFFFFFFF, int(hi, 0) & 0xFFFFFFFF)
        cc.run()
        if a.map_lock:
            map_lock(cc, a.map_lock)
        if a.budget:
            budget_check(cc, a.budget)
        emit.prepare(cc)
        os.makedirs(a.out, exist_ok=True)
        what = ALL if a.emit == 'all' else [x.strip() for x in a.emit.split(',')]
        files = []
        if 'verilog' in what:
            files.append(emit.emit_verilog(cc, a.out))
            files.append(emit.emit_filelist(cc, a.out))
        if 'gprj' in what:
            if not getattr(cc, 'files', None):
                emit.emit_filelist(cc, a.out)
            files.append(emit.emit_gprj(cc, a.out))
        if 'header' in what:
            files.append(emit.emit_header(cc, a.out))
        if 'map' in what:
            files.append(emit.emit_map(cc, a.out))
        if 'model' in what or 'tb' in what:
            files.append(emit.emit_model(cc, a.out))
        if 'tb' in what:
            files += emit_tb.emit_tb(cc, a.out)
        if 'pins' in what and (cc.pes or a.emit != 'all'):
            files.append(emit.emit_pins(cc, a.out))
        if 'report' in what:
            files.append(emit.emit_report(cc, a.out))
        if a.dump:
            dump(cc, a.dump)
    except GrvError as e:
        print(f'grvgen: error {e}', file=sys.stderr)
        return 1
    for kind, code, msg in cc.diag.items:
        if kind != 'note' or not a.quiet:
            print(f'grvgen: {kind} {code + ": " if code else ""}{msg}', file=sys.stderr)
    if not a.quiet:
        tot = {k: sum(i.cost.get(k, 0) for i in cc.insts) for k in ('lut', 'mult', 'bram')}
        print(f'grvgen: {cc.top}: {len(cc.insts)} instances, {len(cc.srcs)} source / {len(cc.snks)} sink endpoints, '
              f'{len(cc.prbs)} probes, {len(cc.pes)} peripheral endpoints, {len(cc.dmas)} DMA channels, {len(cc.params)} parameters; estimate {tot["mult"]} multipliers, {tot["bram"]} BRAM')
        for f in files:
            print('  ' + f)
    return 0


if __name__ == '__main__':
    sys.exit(main())
