"""Reads the parameter and port lists of the library modules from their Verilog headers."""
import os, re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
RTL_DIRS = ['rtl/prim', 'rtl/blocks', 'rtl/axil', 'rtl/periph', 'rtl/dma']
_cache = None


class ModInfo:
    def __init__(self, name, path):
        self.name, self.path = name, path
        self.params = {}            # name -> default text
        self.ports = {}             # name -> 'input' / 'output'
        self.order = []
        self.deps = set()           # library modules instantiated inside


def _parse_file(path, out, extra_dirs=()):
    txt = open(path).read()
    txt_nc = re.sub(r'//[^\n]*', '', txt)
    txt_nc = re.sub(r'/\*.*?\*/', '', txt_nc, flags=re.S)
    for m in re.finditer(r'\bmodule\s+(\w+)\s*(#\s*\((.*?)\)\s*)?\((.*?)\);(.*?)\bendmodule\b', txt_nc, re.S):
        mi = ModInfo(m.group(1), path)
        if m.group(3):
            for pm in re.finditer(r'parameter\s+(?:integer\s+|\[[^\]]*\]\s*)?(\w+)\s*=\s*([^,]+?)\s*(?=,\s*parameter|\s*$)',
                                  m.group(3).strip() + ' ', re.S):
                mi.params[pm.group(1)] = pm.group(2).strip()
        for pm in re.finditer(r'\b(input|output|inout)\s+(?:wire|reg)?\s*(?:signed\s*)?(\[[^\]]*\])?\s*(\w+)', m.group(4)):
            mi.ports[pm.group(3)] = pm.group(1)
            mi.order.append(pm.group(3))
        body = m.group(5)
        for im in re.finditer(r'^\s*(grv_\w+)\s*(?:#\s*\(|\w+\s*\()', body, re.M):
            mi.deps.add(im.group(1))
        out[mi.name] = mi


def modules(extra_dirs=()):
    global _cache
    if _cache is None or extra_dirs:
        res = {}
        for d in list(RTL_DIRS) + list(extra_dirs):
            dd = d if os.path.isabs(d) else os.path.join(ROOT, d)
            if not os.path.isdir(dd):
                continue
            for f in sorted(os.listdir(dd)):
                if f.endswith('.v'):
                    _parse_file(os.path.join(dd, f), res)
        _cache = res
    return _cache


def info(name):
    m = modules()
    if name not in m:
        raise KeyError(f'library module {name} not found')
    return m[name]


def closure(names):
    """library files needed by a set of modules, dependencies first"""
    m = modules()
    seen, order = set(), []

    def visit(n):
        if n in seen or n not in m:
            return
        seen.add(n)
        for d in sorted(m[n].deps):
            visit(d)
        if m[n].path not in order:
            order.append(m[n].path)
    for n in sorted(names):
        visit(n)
    return order
