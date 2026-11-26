"""grvgen core: the graph, the GRC loader, variables, and the compiler passes."""
import os, re, math, json, zlib, yaml
from fractions import Fraction
from .expr import evaluate, names, GrvError, Constellation
from .fmt import Fmt, for_range, int_bits

PROFILES = {
    'q15': dict(w=16, coef=18, gain=18),
    'q17': dict(w=18, coef=18, gain=18),
    'q11': dict(w=12, coef=12, gain=12),
    'q7':  dict(w=8, coef=9, gain=9),
}
INT_FMT = {'int': Fmt(32, 0), 'short': Fmt(16, 0), 'byte': Fmt(8, 0)}
RUNTIME_VAR_IDS = {'variable_qtgui_range', 'variable_qtgui_chooser', 'variable_qtgui_check_box',
                   'variable_qtgui_entry', 'variable_qtgui_push_button', 'variable_qtgui_toggle_button_msg'}
VAR_IDS = {'variable', 'parameter', 'import', 'options', 'note', 'variable_constellation',
           'variable_function_probe', 'snippet'} | RUNTIME_VAR_IDS


# ------------------------------------------------------------------ data structures
class Block:
    def __init__(self, name, bid, params, state, comment):
        self.name, self.id, self.params, self.state = name, bid, params, state
        self.comment = comment or ''
        self.prag = parse_pragmas(self.comment)


class Net:
    _n = 0

    def __init__(self, fmt, rng, name=None, vlen=1):
        Net._n += 1
        self.id = Net._n
        self.name = name or f'n{Net._n}'
        self.fmt, self.rng, self.vlen = fmt, float(rng), vlen
        self.rate = None             # samples per second (None: unknown)
        self.ratio = Fraction(1)     # output rate / input rate of the producing instance
        self.src = None              # (inst, port)
        self.dst = []                # [(inst, port)]
        self.grc = None              # ('block', port) of the GRC graph


class Cfg:
    """value of a cfg_* input: constant, runtime parameter word(s), or chooser multiplexer"""
    def __init__(self, port, width, signed=True, const=None):
        self.port, self.width, self.signed = port, width, signed
        self.const = const
        self.param = None            # Param when runtime
        self.mux = None              # (Param of the chooser index, [values])


class Param:
    def __init__(self, inst, cfg, var, conv_desc):
        self.inst, self.cfg, self.var = inst, cfg, var
        self.desc = conv_desc
        self.words = (cfg.width + 31) // 32
        self.index = None            # first word
        self.init = 0
        self.affine = None           # (A, B): hw = A * v + B
        self.name = None


class Inst:
    def __init__(self, name, module, params, kind='block', blk=None):
        self.name, self.module, self.params, self.kind, self.blk = name, module, params, kind, blk
        self.ins = []                # [(Net, width per component)]
        self.outs = []               # [Net or None]
        self.cfg = []                # [Cfg]
        self.extra = {}              # port -> verilog expression
        self.ovf = False
        self.meta = dict(latency=1, fill=1, cap=2, ii=1)
        self.cost = dict(lut=0, ff=0, mult=0, bram=0)
        self.model = True            # has a bit-exact model
        self.ep = None               # endpoint info dict
        self.ni_port = None          # module parameter giving the number of inputs (multi-port)
        self.notes = []
        self.ovf_index = None
        self.grc_id = blk.id if blk else ''


def parse_pragmas(c):
    out = {}
    for m in re.finditer(r'@grv\s+([^@\n]*)', c or ''):
        for tok in m.group(1).split():
            if '=' in tok:
                k, v = tok.split('=', 1)
                out[k.strip()] = v.strip()
            else:
                out[tok.strip()] = True
    return out


# ------------------------------------------------------------------ diagnostics
class Diag:
    def __init__(self, strict=False):
        self.items, self.strict = [], strict

    def err(self, code, msg):
        self.items.append(('error', code, msg))
        raise GrvError(f'{code}: {msg}')

    def warn(self, code, msg):
        self.items.append(('warning', code, msg))
        if self.strict:
            raise GrvError(f'{code} (strict): {msg}')

    def note(self, msg):
        self.items.append(('note', '', msg))


# ------------------------------------------------------------------ loading
def load_grc(path):
    txt = open(path).read()
    if txt.lstrip().startswith('<'):
        raise GrvError('E001: XML flowgraph (GNU Radio 3.7): open and save it in GNU Radio Companion 3.8 or newer')
    d = yaml.safe_load(txt)
    opts = d.get('options', {}).get('parameters', {})
    blocks = {}
    for b in d.get('blocks', []):
        params = {k: ('' if v is None else str(v)) for k, v in (b.get('parameters') or {}).items()}
        st = (b.get('states') or {}).get('state', 'enabled')
        if st is True:
            st = 'enabled'
        blocks[b['name']] = Block(b['name'], b['id'], params, str(st), params.get('comment', ''))
    conns = []
    for c in d.get('connections', []):
        conns.append((str(c[0]), str(c[1]), str(c[2]), str(c[3])))
    return opts, blocks, conns, txt


# ------------------------------------------------------------------ compiler context
class Compiler:
    def __init__(self, path, clk=54e6, profile='q15', base=0x60000000, top=None, rate=None, strict=False,
                 fold='auto', slices='all', defines=None, range_mode='worst'):
        self.path = path
        self.clk = float(clk)
        self.prof = PROFILES[profile] if isinstance(profile, str) else profile
        self.base = base
        self.diag = Diag(strict)
        self.fold = fold
        self.slices = slices
        self.range_mode = range_mode
        self.opts, self.blocks, self.conns, self.text = load_grc(path)
        self.top = top or (self.opts.get('id') or os.path.splitext(os.path.basename(path))[0]) + '_top'
        self.defines = defines or {}
        self.rate_over = rate or {}
        self.env = {}                 # variable values (defaults)
        self.rvars = {}               # runtime variables: name -> dict(kind, default, lo, hi, options, step)
        self.insts = []
        self.nets = []
        self.params = []              # runtime Param list
        self.hash = zlib.crc32(self.text.encode()) & 0xFFFFFFFF
        self.inst_names = set()

    # ---------------- helpers
    def uniq(self, base):
        n = re.sub(r'[^A-Za-z0-9_]', '_', base)
        if n[0].isdigit():
            n = 'u' + n
        k, c = n, 1
        while k in self.inst_names:
            c += 1
            k = f'{n}_{c}'
        self.inst_names.add(k)
        return k

    def ev(self, blk, key, default=None, env=None):
        v = blk.params.get(key)
        if v is None or str(v).strip() == '':
            return default
        return evaluate(v, env if env is not None else self.env)

    def raw(self, blk, key, default=''):
        v = blk.params.get(key)
        return default if v is None else str(v)

    def deps(self, blk, key):
        return {n for n in names(blk.params.get(key, '')) if n in self.rvars}

    def all_deps(self, expr):
        """runtime variables an expression depends on, through other variables"""
        seen, todo, out = set(), list(names(expr)), set()
        while todo:
            n = todo.pop()
            if n in seen:
                continue
            seen.add(n)
            if n in self.rvars:
                out.add(n)
            elif n in self.var_exprs:
                todo += list(names(self.var_exprs[n]))
        return out

    def range_of(self, blk, key, default=0.0):
        """(min, max) of a parameter over the values of the runtime variables it depends on"""
        src = blk.params.get(key, '')
        if str(src).strip() == '':
            return (default, default)
        vals = []
        for env in self.var_corners(self.all_deps(src)):
            v = evaluate(src, env)
            vals.append(v)
        flat = []
        for v in vals:
            if isinstance(v, (list, tuple)):
                flat += [abs(complex(x)) for x in v]
            elif isinstance(v, complex):
                flat.append(abs(v))
            else:
                flat.append(float(v))
        return (min(flat), max(flat))

    def var_corners(self, deps):
        """environments at the extreme values of the runtime variables"""
        envs = [dict(self.env)]
        for d in deps:
            rv = self.rvars[d]
            vals = rv['options'] if rv['kind'] == 'chooser' else [rv['lo'], rv['hi'], rv['default']]
            new = []
            for e in envs:
                for v in vals:
                    e2 = dict(e)
                    e2[d] = v
                    new.append(self.reeval(e2))
            envs = new
        return envs

    def reeval(self, env):
        """recompute dependent variables after changing runtime variables"""
        e = dict(env)
        for n in self.var_order:
            if n in self.rvars:
                continue
            try:
                e[n] = evaluate(self.var_exprs[n], e)
            except GrvError:
                pass
        return e

    def fmt_for(self, gtype, rng, pr=None):
        """format of a port of GRC type gtype with range bound rng (pragmas may override)"""
        pr = pr or {}
        if 'fmt' in pr:
            from .fmt import parse
            f = parse(pr['fmt'])
            return f.with_(cplx=(gtype == 'complex'))
        if gtype in INT_FMT:
            return INT_FMT[gtype]
        w = int(pr.get('width', self.prof['w']))
        if 'range' in pr:
            rng = float(evaluate(str(pr['range']), self.env))
        return for_range(max(rng, 2.0 ** -(w - 2)), w, gtype == 'complex')

    def new_net(self, fmt, rng, vlen=1):
        n = Net(fmt, rng, vlen=vlen)
        self.nets.append(n)
        return n

    # ---------------- runtime parameters
    def cfg(self, inst, port, width, blk, key, conv, signed=True, desc='', default=0, env_expr=None):
        """cfg_<port> of inst from the GRC parameter key; conv(value) -> hardware integer"""
        c = Cfg(port, width, signed)
        src = env_expr if env_expr is not None else blk.params.get(key, '')
        deps = self.all_deps(src) if str(src).strip() else set()
        if str(blk.prag.get('static', '')) or not deps:
            v = evaluate(src, self.env) if str(src).strip() else default
            c.const = int(conv(v))
        else:
            if len(deps) > 1:
                self.diag.err('E402', f'{blk.name}.{key} depends on several runtime variables {sorted(deps)}')
            var = deps.pop()
            rv = self.rvars[var]
            if rv['kind'] == 'chooser':
                opts = rv['options']
                vals = [int(conv(evaluate(src, self.reeval(dict(self.env, **{var: o}))))) for o in opts]
                pidx = self.chooser_param(var)
                c.mux = (pidx, vals, opts)
            else:
                p = Param(inst, c, var, desc)
                p.init = int(conv(evaluate(src, self.env)))
                # affine check over three points
                lo, hi = rv['lo'], rv['hi']
                pts = [lo, (lo + hi) / 2.0, hi] if hi != lo else [lo, lo + 1, lo + 2]
                hv = [conv(evaluate(src, self.reeval(dict(self.env, **{var: x})))) for x in pts]
                a = (hv[2] - hv[0]) / (pts[2] - pts[0]) if pts[2] != pts[0] else 0.0
                b = hv[0] - a * pts[0]
                lin = abs(a * pts[1] + b - hv[1]) <= max(2.0, abs(hv[1]) * 1e-6)
                if not lin:
                    self.diag.err('E401', f'{blk.name}.{key} depends nonlinearly on runtime variable {var}; '
                                          f'use a chooser, a constant or @grv static')
                a = float(f'{a:.12g}')
                b = 0.0 if abs(b) < 1e-6 else float(f'{b:.12g}')
                p.affine = (a, b)
                p.name = f'{inst.name}_{port[4:] if port.startswith("cfg_") else port}'
                c.param = p
                self.params.append(p)
        inst.cfg.append(c)
        return c

    def chooser_param(self, var):
        for p in self.params:
            if p.var == var and p.cfg.port == '_chooser':
                return p
        rv = self.rvars[var]
        c = Cfg('_chooser', 8, False)
        p = Param(None, c, var, 'chooser index')
        p.init = rv['options'].index(rv['default']) if rv['default'] in rv['options'] else 0
        p.name = f'{var}_index'
        p.affine = None
        c.param = p
        self.params.append(p)
        return p

    # ---------------- pass 1: variables
    def variables(self):
        self.var_exprs, self.var_order = {}, []
        consts = {}
        for b in self.blocks.values():
            if b.state == 'disabled':
                continue
            if b.id == 'import':
                for ln in self.raw(b, 'imports').splitlines():
                    ln = ln.strip()
                    if ln and not re.match(r'^(import|from)\s+(math|numpy|cmath|gnuradio\b.*|pmt|time|osmosdr|sip|sys)', ln):
                        self.diag.err('E103', f'import block {b.name}: {ln!r} is not supported')
                continue
            if b.id in ('variable', 'parameter') or b.id in RUNTIME_VAR_IDS:
                key = 'value'
                if b.id == 'variable_qtgui_check_box':
                    key = 'value'
                self.var_exprs[b.name] = self.raw(b, key, '0')
            if b.id == 'variable_constellation':
                pts, sm = self.raw(b, 'const_points'), self.raw(b, 'sym_map')
                self.var_exprs[b.name] = f'digital.constellation_calcdist({pts}, {sm})'
        for k, v in self.defines.items():
            self.var_exprs[k] = v
        # evaluate in dependency order
        left = dict(self.var_exprs)
        env = {}
        for _ in range(len(left) + 1):
            progress = False
            for n, e in list(left.items()):
                deps = names(e) & set(left)
                deps.discard(n)
                if deps:
                    continue
                env[n] = evaluate(e, env)
                self.var_order.append(n)
                del left[n]
                progress = True
            if not left or not progress:
                break
        if left:
            self.diag.err('E104', f'cannot evaluate variables {sorted(left)} (cycle or unknown name)')
        self.env = env
        # runtime variables
        for b in self.blocks.values():
            if b.state == 'disabled':
                continue
            if b.id in RUNTIME_VAR_IDS or (b.id == 'variable' and b.prag.get('reg')):
                d = env[b.name]
                if b.id == 'variable_qtgui_range' or (b.id == 'variable' and b.prag.get('reg')):
                    lo = self.ev(b, 'start', d)
                    hi = self.ev(b, 'stop', d)
                    if b.id == 'variable':
                        lo = float(evaluate(str(b.prag.get('min', d)), env))
                        hi = float(evaluate(str(b.prag.get('max', d)), env))
                    self.rvars[b.name] = dict(kind='range', default=d, lo=float(min(lo, hi)), hi=float(max(lo, hi)),
                                              step=self.ev(b, 'step', 1), block=b.name)
                elif b.id == 'variable_qtgui_chooser':
                    n = int(self.ev(b, 'num_opts', 3) or 0)
                    if n == 0:
                        opts = list(self.ev(b, 'options', [d]))
                    else:
                        opts = [self.ev(b, f'option{i}', 0) for i in range(n)]
                    self.rvars[b.name] = dict(kind='chooser', default=d, options=opts, block=b.name)
                elif b.id == 'variable_qtgui_check_box':
                    t, f = self.ev(b, 'true', 1), self.ev(b, 'false', 0)
                    self.rvars[b.name] = dict(kind='chooser', default=d, options=[f, t], block=b.name)
                else:
                    self.rvars[b.name] = dict(kind='range', default=d, lo=float(d), hi=float(d), step=1, block=b.name)
                    if isinstance(d, (int, float)):
                        lo = float(evaluate(str(b.prag.get('min', d)), env))
                        hi = float(evaluate(str(b.prag.get('max', d)), env))
                        self.rvars[b.name].update(lo=lo, hi=hi)

    # ---------------- pass 2: flatten
    def flatten(self):
        blocks = {n: b for n, b in self.blocks.items() if b.state != 'disabled' and b.id not in VAR_IDS}
        conns = [c for c in self.conns if c[0] in blocks and c[2] in blocks]
        # virtual sinks / sources
        vs = {self.raw(b, 'stream_id'): n for n, b in blocks.items() if b.id == 'virtual_sink'}
        out = []
        for c in conns:
            if blocks[c[0]].id == 'virtual_source':
                sid = self.raw(blocks[c[0]], 'stream_id')
                if sid not in vs:
                    self.diag.err('E105', f'virtual source {c[0]}: no virtual sink {sid!r}')
                ups = [d for d in conns if d[2] == vs[sid]]
                for u in ups:
                    out.append((u[0], u[1], c[2], c[3]))
            elif blocks[c[2]].id == 'virtual_sink':
                continue
            else:
                out.append(c)
        conns = out
        blocks = {n: b for n, b in blocks.items() if b.id not in ('virtual_source', 'virtual_sink')}
        # bypassed blocks become wires
        for n, b in list(blocks.items()):
            if b.state == 'bypassed':
                ins = [c for c in conns if c[2] == n]
                outs = [c for c in conns if c[0] == n]
                if len(ins) != 1:
                    self.diag.err('E106', f'bypassed block {n} must have one input')
                conns = [c for c in conns if c[0] != n and c[2] != n]
                for o in outs:
                    conns.append((ins[0][0], ins[0][1], o[2], o[3]))
                del blocks[n]
        # removed blocks
        for n, b in list(blocks.items()):
            if b.id in ('blocks_tag_debug', 'blocks_message_debug', 'blocks_tag_gate', 'blocks_tags_strobe'):
                self.diag.warn('W102', f'{n} ({b.id}) removed: stream tags and messages are not carried')
                conns = [c for c in conns if c[0] != n and c[2] != n]
                del blocks[n]
        # message connections
        for c in conns:
            if not (c[1].isdigit() and c[3].isdigit()):
                self.diag.err('E107', f'message connection {c[0]}:{c[1]} -> {c[2]}:{c[3]} is not supported')
        self.fblocks, self.fconns = blocks, conns

    # ---------------- pass 3: map
    def topo(self):
        indeg = {n: 0 for n in self.fblocks}
        for c in self.fconns:
            indeg[c[2]] += 1
        order, ready = [], sorted(n for n, d in indeg.items() if d == 0)
        while ready:
            n = ready.pop(0)
            order.append(n)
            for c in self.fconns:
                if c[0] == n:
                    indeg[c[2]] -= 1
                    if indeg[c[2]] == 0:
                        ready.append(c[2])
                        ready.sort()
        if len(order) != len(self.fblocks):
            self.diag.err('E108', 'the flowgraph has a cycle')
        return order

    def map(self):
        from .blocks import MAPPERS
        self.outnet = {}               # (block, port) -> Net
        for n in self.topo():
            b = self.fblocks[n]
            if b.id not in MAPPERS:
                self.diag.err('E101', f'{n}: block id {b.id} is not supported by OpenGRV')
            ins = []
            nin = 1 + max([int(c[3]) for c in self.fconns if c[2] == n] or [-1])
            for k in range(nin):
                src = [c for c in self.fconns if c[2] == n and int(c[3]) == k]
                if not src:
                    self.diag.err('E109', f'{n}: input {k} is not connected')
                ins.append(self.outnet[(src[0][0], int(src[0][1]))])
            outs = MAPPERS[b.id](self, b, ins)
            for k, net in enumerate(outs or []):
                if net is not None:
                    net.grc = (n, k)
                    self.outnet[(n, k)] = net
        # unused outputs
        used = {(c[0], int(c[1])) for c in self.fconns}
        for key, net in self.outnet.items():
            if key not in used:
                net.unused = True

    # ---------------- pass 4: rates and folding
    def rates(self):
        changed = True
        it = 0
        while changed and it < 100:
            changed, it = False, it + 1
            for inst in self.insts:
                rin = [n.rate for n, _ in inst.ins if n.rate is not None]
                if inst.ins and rin:
                    if len(set(round(r, 6) for r in rin)) > 1 and not inst.meta.get('multirate'):
                        self.diag.err('E301', f'{inst.name}: inputs at different rates {sorted(set(rin))}')
                    for o in inst.outs:
                        if o is not None:
                            nr = float(rin[0] * o.ratio) if not inst.meta.get('multirate') else float(sum(rin) * o.ratio)
                            if o.rate is None or abs(o.rate - nr) > 1e-6:
                                o.rate = nr
                                changed = True
        # relative rates: two inputs of a join that come from the same source must have equal ratios
        rel = {}
        for inst in self.insts:
            if not inst.ins:
                for o in inst.outs:
                    rel[id(o)] = (inst.name, Fraction(1))
                continue
            rs = [rel.get(id(n)) for n, _ in inst.ins]
            if inst.meta.get('multirate'):
                continue
            if len(rs) > 1:
                for a in rs:
                    for b in rs:
                        if a and b and a[0] == b[0] and a[1] != b[1]:
                            self.diag.err('E304', f'{inst.name}: its inputs come from {a[0]} at ratios {a[1]} and {b[1]}; '
                                                  f'the join would need unbounded buffering')
            base = next((r for r in rs if r), None)
            if base:
                for o in inst.outs:
                    rel[id(o)] = (base[0], base[1] * o.ratio)
        for n in self.nets:
            if n.rate is not None and n.rate > self.clk * 1.0001:
                self.diag.err('E302', f'output of {n.src[0].name}: {n.rate:.6g} samples/s needs more than one sample per clock')
        from .blocks import FINALIZE
        for inst in self.insts:
            rin = inst.ins[0][0].rate if inst.ins else (inst.outs[0].rate if inst.outs and inst.outs[0] else None)
            rout = inst.outs[0].rate if inst.outs and inst.outs[0] is not None else None
            inst.budget_in = int(self.clk // rin) if rin else 1
            inst.budget_out = int(self.clk // rout) if rout else 1
            inst.known_rate = rin is not None or rout is not None
            f = FINALIZE.get(inst.module)
            if f:
                f(self, inst)
            need = inst.meta.get('ii', 1)
            if inst.known_rate and need > inst.budget_in and inst.kind == 'block':
                self.diag.err('E303', f'{inst.name}: needs {need} clocks per sample, the rate allows {inst.budget_in}')
            elif not inst.known_rate and need > 1 and inst.kind == 'block':
                self.diag.warn('W301', f'{inst.name}: one sample per {need} clocks; the rate of this part of the graph is unknown')

    # ---------------- pass 5: structure (forks, unused outputs)
    def structure(self):
        from .blocks import mk_fork, mk_fifo
        for net in list(self.nets):
            if len(net.dst) > 1:
                mk_fork(self, net)
        self.balance(mk_fifo)
        # status outputs exposed as probes (@grv probe=NAME)
        from . import vports
        for inst in list(self.insts):
            if inst.kind != 'block' or not inst.blk or not inst.blk.prag.get('probe'):
                continue
            sts = [p for p in vports.info(inst.module).order if p.startswith('st_')]
            if not sts:
                self.diag.warn('W402', f'{inst.name}: @grv probe on a block without status outputs')
            base = inst.blk.prag['probe'] if isinstance(inst.blk.prag['probe'], str) else inst.name
            for p in sts:
                w, f = (getattr(inst, 'status', None) or {}).get(p[3:], (1, 0))
                pr = Inst(self.uniq(base if len(sts) == 1 else f'{base}_{p[3:]}'), 'status', {}, 'probe', None)
                pr.ep = dict(status=(inst, p), fmt=Fmt(w, f))
                pr.model = False
                self.insts.append(pr)
        self.ovf_list = []
        for inst in self.insts:
            if inst.ovf:
                inst.ovf_index = len(self.ovf_list)
                self.ovf_list.append(inst)
        if len(self.ovf_list) > 64:
            self.diag.warn('W401', 'more than 64 blocks with overflow flags: only the first 64 are reported')

    def balance(self, mk_fifo):
        """FIFOs on reconvergent paths (design document, reconvergent paths)"""
        def walk(net):
            """path from a join input back to the nearest fork: (fork, port, fill, cap) in samples at the fork"""
            fill, cap, scale = 0.0, 0.0, 1.0
            while True:
                src, port = net.src
                if src.kind == 'fork':
                    return src, port, fill, cap
                if len(src.ins) != 1:
                    return None
                r = float(net.ratio) if net.ratio else 1.0
                # samples at this instance's output -> samples at its input
                scale_in = scale / r if r else scale
                fill += src.meta.get('fill', 1) * scale_in
                cap += src.meta.get('cap', 2) * scale_in
                scale = scale_in
                net = src.ins[0][0]
        for inst in list(self.insts):
            if len(inst.ins) < 2 or inst.meta.get('multirate'):
                continue
            paths = [walk(n) for n, _ in inst.ins]
            groups = {}
            for k, pth in enumerate(paths):
                if pth:
                    groups.setdefault(id(pth[0]), []).append((k, pth))
            for g in groups.values():
                if len(g) < 2:
                    continue
                fmax = max(p[2] for _, p in g)
                for k, p in g:
                    need = fmax + 2 - p[3]
                    if p[2] < fmax and need > 0:
                        depth = 1 << max(1, math.ceil(math.log2(need)))
                        mk_fifo(self, inst, k, depth)
                        self.diag.note(f'balancing FIFO of {depth} samples before {inst.name} input {k}')

    # ---------------- pass 6: addresses
    def allocate(self):
        # parameter names: the variable when it drives one parameter, else instance_port
        byvar = {}
        for p in self.params:
            if p.inst is not None:
                byvar.setdefault(p.var, []).append(p)
        names_used = set()
        for p in self.params:
            if p.inst is None:
                p.name = p.var
            elif len(byvar[p.var]) == 1:
                p.name = p.var
            names_used.add(p.name)
        srcs = sorted([i for i in self.insts if i.kind == 'src'], key=lambda i: i.name)
        snks = sorted([i for i in self.insts if i.kind == 'snk'], key=lambda i: i.name)
        prbs = sorted([i for i in self.insts if i.kind == 'probe'], key=lambda i: i.name)
        if len(srcs) > 16 or len(snks) > 16:
            self.diag.err('E501', 'at most 16 source and 16 sink endpoints')
        caps = [s for s in snks if s.ep.get('capd', 0)]
        for k, s in enumerate(srcs):
            s.ep['index'], s.ep['addr'] = k, 0x1000 + 0x100 * k
        for k, s in enumerate(snks):
            s.ep['index'], s.ep['addr'] = k, 0x2000 + 0x100 * k
            if s.ep.get('capd', 0):
                if k > 3:
                    self.diag.err('E502', f'{s.name}: capture endpoints must be sink endpoints 0 .. 3; '
                                          f'rename the block so it sorts first')
                s.ep['window'] = 0x8000 + 0x2000 * k
        for k, s in enumerate(prbs):
            s.ep['index'], s.ep['addr'] = k, 0x3000 + 8 * k
        self.srcs, self.snks, self.prbs = srcs, snks, prbs
        # peripheral endpoints and DMA channels (revision 0.2)
        pes = sorted([i for i in self.insts if i.kind == 'pe'], key=lambda i: i.name)
        dmas = sorted([i for i in self.insts if i.kind == 'dma'], key=lambda i: i.name)
        if len(pes) > 16:
            self.diag.err('E603', f'{len(pes)} peripheral endpoints (at most 16)')
        if len(dmas) > 16:
            self.diag.err('E603', f'{len(dmas)} DMA channels (at most 16)')
        for k, s in enumerate(pes):
            s.ep['index'], s.ep['addr'] = k, 0x6000 + 0x100 * k
        for k, s in enumerate(dmas):
            s.ep['index'], s.ep['addr'] = k, 0x7000 + 0x100 * k
        self.pes, self.dmas = pes, dmas
        self.check_periph()
        w = 0
        for p in sorted(self.params, key=lambda p: p.name):
            p.index = w
            w += p.words
        self.npw = max(w, 1)
        if w > 960:
            self.diag.err('E503', 'more than 960 parameter words')

    def check_periph(self):
        """rates at paced outputs and UART lines (W601, W602), pin names (E604)"""
        for i in self.pes:
            if i.ep['dir'] != 'out':
                continue
            r = i.ins[0][0].rate
            if r is None:
                continue
            cap = i.ep.get('cap')
            if cap and r > cap * 1.0001:
                self.diag.warn('W601', f'{i.name}: the UART carries {cap / 1e3:.4g} kS/s, the stream {r / 1e3:.4g} kS/s: '
                                       f'the graph will be held back (or drop samples)')
            pace = i.ep.get('pace')
            if pace and abs(r - pace) > pace * 1e-3:
                self.diag.warn('W602', f'{i.name}: paced at {pace / 1e3:.4g} kS/s, the stream arrives at {r / 1e3:.4g} kS/s'
                                       + (': underflows expected' if r < pace else ': the graph will be held back'))
        fixed = {'clk', 'rst_n', 'irq'} | {f's_axil_{x}' for x in ('awaddr', 'awvalid', 'awready', 'wdata', 'wstrb', 'wvalid',
                                                                  'wready', 'bresp', 'bvalid', 'bready', 'araddr', 'arvalid',
                                                                  'arready', 'rdata', 'rresp', 'rvalid', 'rready')}
        if self.dmas:
            fixed |= {f'm_mem_{x}' for x in ('valid', 'addr', 'wdata', 'wstrb', 'ready', 'rdata')}
        owner = {p: 'a port of the top level' for p in fixed}
        for i in self.insts:
            if i.kind in ('pad_in', 'pad_out'):
                owner[i.ep['label']] = 'a pad of the same name'
                for x in ('tdata', 'tvalid', 'tready', 'tlast'):
                    owner[f'{i.ep["label"]}_{x}'] = f'pad {i.ep["label"]}'
        for i in self.pes:
            for pin in i.ep['pins']:
                n = f'{i.name}_{pin[0]}'
                if n in owner:
                    self.diag.err('E604', f'{i.name}: pin {n} collides with {owner[n]}')
                owner[n] = f'pin of {i.name}'

    # ---------------- run all
    def run(self):
        self.variables()
        self.flatten()
        self.map()
        self.rates()
        self.structure()
        self.allocate()
        return self
