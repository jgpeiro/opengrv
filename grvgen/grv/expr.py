"""Restricted evaluation of the Python expressions in GRC parameters. Only literals, arithmetic,
comparisons, conditionals, displays, comprehensions, names and calls of whitelisted functions are
accepted; attribute names starting with '_' are refused."""
import ast, math, cmath
import numpy
from .firdes import firdes, window


class GrvError(Exception):
    pass


class _NS:
    def __init__(self, **kw):
        self.__dict__.update(kw)


analog = _NS(GR_CONST_WAVE=100, GR_SIN_WAVE=101, GR_COS_WAVE=102, GR_SQR_WAVE=103, GR_TRI_WAVE=104, GR_SAW_WAVE=105,
             GR_UNIFORM=200, GR_GAUSSIAN=201, GR_LAPLACIAN=202, GR_IMPULSE=203)
gr = _NS(GR_MSB_FIRST=0, GR_LSB_FIRST=1)


class Constellation:
    def __init__(self, points, symbols=None, name='calcdist'):
        self.pts = [complex(p) for p in points]
        self.syms = list(symbols) if symbols is not None else list(range(len(self.pts)))
        self.name = name

    def base(self):
        return self

    def points(self):
        return self.pts


def _calcdist(points, symbols, rot=4, dims=1, *a, **k):
    return Constellation(points, symbols)


digital = _NS(constellation_calcdist=_calcdist, constellation_rect=lambda pts, syms, *a, **k: Constellation(pts, syms),
              constellation_bpsk=lambda: Constellation([-1, 1], [0, 1], 'bpsk'),
              DIFF_DIFFERENTIAL=0, DIFF_PHASE=1)
fft_ns = _NS(window=window)

SAFE = {
    'True': True, 'False': False, 'None': None, 'pi': math.pi, 'e': math.e, 'j': 1j,
    'abs': abs, 'int': int, 'float': float, 'complex': complex, 'round': round, 'len': len, 'range': range,
    'list': list, 'tuple': tuple, 'min': min, 'max': max, 'sum': sum, 'bool': bool, 'str': str, 'pow': pow,
    'math': math, 'cmath': cmath, 'numpy': numpy, 'np': numpy, 'firdes': firdes, 'window': window,
    'analog': analog, 'digital': digital, 'gr': gr, 'fft': fft_ns, 'filter': _NS(firdes=firdes),
}
for _n in dir(math):
    if not _n.startswith('_'):
        SAFE.setdefault(_n, getattr(math, _n))

_OK = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp, ast.Call, ast.Attribute,
       ast.Name, ast.Constant, ast.List, ast.Tuple, ast.ListComp, ast.GeneratorExp, ast.comprehension,
       ast.Subscript, ast.Slice, ast.keyword, ast.Load, ast.Store, ast.operator, ast.unaryop, ast.boolop,
       ast.cmpop, ast.expr_context, ast.Dict, ast.Set)


def check(src):
    try:
        tree = ast.parse(src.strip(), mode='eval')
    except SyntaxError as e:
        raise GrvError(f'syntax error in expression {src!r}: {e.msg}')
    for node in ast.walk(tree):
        if not isinstance(node, _OK):
            raise GrvError(f'expression {src!r}: {type(node).__name__} is not allowed')
        if isinstance(node, ast.Attribute) and node.attr.startswith('_'):
            raise GrvError(f'expression {src!r}: attribute {node.attr} is not allowed')
    return tree


def names(src):
    """names referenced by an expression"""
    try:
        tree = ast.parse(str(src).strip(), mode='eval')
    except SyntaxError:
        return set()
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}


def evaluate(src, env):
    if not isinstance(src, str):
        return src
    s = src.strip()
    if s == '':
        return None
    tree = check(s)
    ns = dict(SAFE)
    ns.update(env)
    try:
        return eval(compile(tree, '<grc>', 'eval'), {'__builtins__': {}}, ns)
    except GrvError:
        raise
    except Exception as e:
        raise GrvError(f'cannot evaluate {s!r}: {e}')
