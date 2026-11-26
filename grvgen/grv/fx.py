"""Bit-exact integer helpers shared by the block models: resize, wrap, sine table, CORDIC, LFSRs.
Every function here mirrors one primitive of rtl/prim/ operation by operation."""
import math

# ------------------------------------------------------------------ integers
def wrap(v, w, signed=True):
    """two's complement wrap of v to w bits"""
    v &= (1 << w) - 1
    if signed and v >> (w - 1):
        v -= 1 << w
    return v


def to_u(v, w):
    return v & ((1 << w) - 1)


def clog2(n):
    return max(0, (n - 1).bit_length())


def resize(x, ow, shift, rnd=1, sat=1, osigned=True):
    """grv_resize: x is the exact integer value. Returns (y, ovf)."""
    if shift < 0:
        x <<= -shift
        s = 0
    else:
        s = shift
    if s > 0 and rnd:
        h = 1 << (s - 1)
        if rnd == 1:
            x += h
        elif rnd == 2:
            x += h - (1 if x < 0 else 0)
        else:
            x += h - 1 + ((x >> s) & 1)
    y = x >> s
    if osigned:
        hi = (1 << (ow - 1)) - 1
        lo = -hi if sat == 2 else -(1 << (ow - 1))
    else:
        hi, lo = (1 << ow) - 1, 0
    if sat:
        if y > hi:
            return hi, 1
        if y < lo:
            return lo, 1
        return y, 0
    return wrap(y, ow, osigned), 0


def rz(x, ow, shift, rnd=1, sat=1, osigned=True):
    return resize(x, ow, shift, rnd, sat, osigned)[0]


# ------------------------------------------------------------------ sine table (grv_sincos)
SIN_AMP = (1 << 17) - 1


def sin_tab():
    return [int(round(math.sin(i * math.pi / 2048.0) * SIN_AMP)) for i in range(1024)]


_TAB = sin_tab()


def sin12(p):
    """sine of a 12-bit phase (units of 2*pi/4096), s18.17"""
    p &= 4095
    q, i = p >> 10, p & 1023
    if q & 1:
        v = SIN_AMP if i == 0 else _TAB[(1024 - i) & 1023]
    else:
        v = _TAB[i]
    return -v if q & 2 else v


def cos12(p):
    return sin12(p + 1024)


# ------------------------------------------------------------------ CORDIC (grv_cordic)
ATAN = [int(round(math.atan(2.0 ** -i) / (2 * math.pi) * 2 ** 32)) for i in range(32)]


def cordic_gain(n):
    k = 1.0
    for i in range(n):
        k *= math.sqrt(1 + 2.0 ** (-2 * i))
    return k


def cordic_vec(x, y, n, xw):
    """vector mode: returns (x_final, z) ; z 32-bit unsigned phase of atan2(y, x)"""
    z = 0
    if x < 0:
        x, y, z = -x, -y, 1 << 31
    x, y = wrap(x, xw), wrap(y, xw)
    for i in range(n):
        if y < 0:
            x, y, z = x - (y >> i), y + (x >> i), z - ATAN[i]
        else:
            x, y, z = x + (y >> i), y - (x >> i), z + ATAN[i]
        x, y, z = wrap(x, xw), wrap(y, xw), z & 0xFFFFFFFF
    return x, z


def cordic_rot(x, y, z, n, xw):
    """rotate mode: rotate (x, y) by the 32-bit phase z; returns (x, y) with gain K"""
    z &= 0xFFFFFFFF
    if (z >> 30) in (1, 2):
        x, y, z = -x, -y, (z + (1 << 31)) & 0xFFFFFFFF
    x, y = wrap(x, xw), wrap(y, xw)
    zs = wrap(z, 32)
    for i in range(n):
        if zs >= 0:
            x, y, zs = x - (y >> i), y + (x >> i), zs - ATAN[i]
        else:
            x, y, zs = x + (y >> i), y - (x >> i), zs + ATAN[i]
        x, y, zs = wrap(x, xw), wrap(y, xw), wrap(zs, 32)
    return x, y


# ------------------------------------------------------------------ random numbers
def xorshift32(s):
    s ^= (s << 13) & 0xFFFFFFFF
    s ^= s >> 17
    s ^= (s << 5) & 0xFFFFFFFF
    return s & 0xFFFFFFFF


def seeds(seed, n):
    """seeds of the n generators of a noise source (grv_noise_source)"""
    out = []
    for k in range(n):
        s = (seed * 0x9E3779B1 + 0x6A09E667 * (k + 1)) & 0xFFFFFFFF
        out.append(s or 0x12345678)
    return out


# ------------------------------------------------------------------ packing
def pack(v, w, cplx):
    if cplx:
        i, q = v
        return (to_u(q, w) << w) | to_u(i, w)
    return to_u(v, w)


def unpack(u, w, cplx, signed=True):
    if cplx:
        return (wrap(u & ((1 << w) - 1), w, signed), wrap(u >> w, w, signed))
    return wrap(u, w, signed)
