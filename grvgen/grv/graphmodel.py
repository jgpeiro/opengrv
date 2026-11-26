"""Evaluates a generated graph with the bit-exact block models (used by <top>_model.py)."""
from .models import MODELS
from .fx import pack, unpack, wrap, to_u


def _norm(v, f):
    """value of a module port -> net representation (signed int / (i, q) tuple / unsigned int)"""
    if f['cplx']:
        if isinstance(v, tuple):
            return v
        return unpack(int(v), f['w'], True, f['signed'])
    if isinstance(v, tuple):
        v = v[0]
    return wrap(int(v), f['w'], f['signed'])


def _raw(v, f):
    if f['cplx']:
        return pack(v, f['w'], True)
    return to_u(int(v), f['w'])


def to_float(vals, f):
    s = 2.0 ** -f['f']
    if f['cplx']:
        return [complex(a * s, b * s) for a, b in vals]
    return [v * s for v in vals]


def _cfg_value(spec, params, raw_params):
    if 'const' in spec:
        u = spec['const']
    elif 'param' in spec:
        u = to_u(raw_params.get(spec['param'], params[spec['param']]['init']), spec['width'])
    else:
        idx = raw_params.get(spec['mux'], params[spec['mux']]['init'])
        u = spec['vals'][idx]
    if spec.get('split'):
        k = spec['split']
        return (wrap(u & ((1 << k) - 1), k), wrap(u >> k, k))
    if spec['width'] == 64:
        return u if isinstance(u, int) else int(u)
    return wrap(u, spec['width']) if spec['signed'] else to_u(u, spec['width'])


def run_graph(g, inputs, n, params, raw_params):
    nets, insts = g['nets'], g['insts']
    rp = dict(raw_params)
    # GRC-unit variable values -> hardware values of their parameter words
    for var, val in params.items():
        found = False
        for pn, p in g['params'].items():
            if p['var'] != var:
                continue
            found = True
            if p['affine'] is None:
                opts = g['rvars'][var]['options']
                rp[pn] = opts.index(repr(val)) if repr(val) in opts else int(val)
            else:
                a, b = p['affine']
                rp[pn] = int(round(a * val + b))
        if not found:
            raise KeyError(f'{var} is not a runtime variable of the graph')
    rates = [i['anchor'] for i in insts if i.get('anchor')]
    rmax = max(rates) if rates else None
    vals, lasts = {}, {}
    out = {}
    done = set()
    pending = list(insts)
    while pending:
        progress = False
        for i in list(pending):
            if any(x not in vals for x in i['ins']):
                continue
            pending.remove(i)
            progress = True
            kind = i['kind']
            if kind in ('pe', 'dma'):
                kind = 'snk' if i['ins'] else 'src'
            if kind in ('src', 'pad_in'):
                key = i['name'] if kind == 'src' else i['ep']['label']
                f = nets[i['outs'][0]]
                xs = [(_norm(v, f)) for v in inputs.get(key, [])]
                vl = f['vlen']
                vals[i['outs'][0]] = xs
                lasts[i['outs'][0]] = [int(vl > 1 and k % vl == vl - 1) for k in range(len(xs))]
                continue
            if kind in ('snk', 'pad_out', 'probe', 'null'):
                if kind == 'null' or not i['ins']:
                    continue
                key = i['name'] if kind != 'pad_out' else i['ep']['label']
                out[key] = vals[i['ins'][0]]
                out[key + '.last'] = lasts[i['ins'][0]]
                continue
            m = MODELS.get(i['module'])
            if m is None:
                raise NotImplementedError(f'no model for {i["module"]}')
            p = {k: (tuple(v) if isinstance(v, list) else v) for k, v in i['params'].items()}
            cfg = {k: _cfg_value(s, g['params'], rp) for k, s in i['cfg'].items()}
            if not i['ins']:
                cnt = n
                if rmax and i.get('anchor'):
                    cnt = max(1, int(round(n * i['anchor'] / rmax)))
                cfg['_n'] = cnt
            ins = []
            for x in i['ins']:
                f = nets[x]
                ins.append([_raw(v, f) for v in vals[x]] if i['raw'] else list(vals[x]))
            ls = [lasts[x] for x in i['ins']]
            o, ol = m(p, ins, ls, cfg)
            for k, name in enumerate(i['outs']):
                f = nets[name]
                vals[name] = [_norm(v, f) for v in o[k]]
                lasts[name] = list(ol[k])
        if not progress:
            raise RuntimeError('graph model: cycle or missing input')
    return out
