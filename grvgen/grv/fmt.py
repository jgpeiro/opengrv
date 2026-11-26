"""Fixed-point formats sW.F / uW.F, real or complex, and their choice from a range."""
import math


class Fmt:
    __slots__ = ('w', 'f', 'cplx', 'signed')

    def __init__(self, w, f=0, cplx=False, signed=True):
        self.w, self.f, self.cplx, self.signed = int(w), int(f), bool(cplx), bool(signed)

    @property
    def nc(self):
        return 2 if self.cplx else 1

    @property
    def tw(self):
        """tdata width"""
        return self.w * self.nc

    def maxval(self):
        """largest representable magnitude"""
        return ((1 << (self.w - (1 if self.signed else 0))) - 1) / 2.0 ** self.f

    def with_(self, **kw):
        d = {k: getattr(self, k) for k in self.__slots__}
        d.update(kw)
        return Fmt(**d)

    def __eq__(self, o):
        return isinstance(o, Fmt) and all(getattr(self, k) == getattr(o, k) for k in self.__slots__)

    def __hash__(self):
        return hash(tuple(getattr(self, k) for k in self.__slots__))

    def __repr__(self):
        return ('c' if self.cplx else '') + ('s' if self.signed else 'u') + f'{self.w}.{self.f}'

    def to_json(self):
        return {'w': self.w, 'f': self.f, 'cplx': self.cplx, 'signed': self.signed, 'str': repr(self)}


def int_bits(r, w=None):
    """integer bits (with sign) needed to hold [-r, r] in a signed format of width w"""
    if r <= 0:
        return 1
    m = max(1, math.ceil(math.log2(r)) + 1)
    if w is not None and r >= 2 ** (m - 1) - 2.0 ** -(w - m):
        m += 1
    return m


def for_range(r, w, cplx=False):
    m = int_bits(r, w)
    return Fmt(w, w - m, cplx)


def parse(s):
    """'cs16.15' -> Fmt"""
    s = s.strip()
    c = s.startswith('c')
    if c:
        s = s[1:]
    sg = s[0] == 's'
    w, f = s[1:].split('.')
    return Fmt(int(w), int(f), c, sg)
