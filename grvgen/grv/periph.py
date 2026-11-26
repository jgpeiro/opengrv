"""Mappers of the peripheral endpoints (UART, SPI, GPIO) and of the DMA channels (revision 0.2)."""
import math
from .core import Inst, INT_FMT
from .fmt import Fmt
from .expr import evaluate
from .blocks import mapper, mk, gtype, pow2, bram_for, re_id


# ------------------------------------------------------------------ parameter access
VIA_KEYS = ('type', 'vlen', 'samp_rate')


def pp(cc, b, key, default=None):
    """setting of an endpoint: pragma first, then the GRC parameter (for a standard block mapped with
    @grv via=..., only its type, vlen and samp_rate: its other parameters mean something else)"""
    if getattr(b, 'via', False) and key not in VIA_KEYS and key not in b.prag:
        return default
    if key in b.prag:
        v = b.prag[key]
        if v is True:
            return True
        try:
            return evaluate(str(v), cc.env)
        except Exception:
            return str(v)
    if key in b.params and str(b.params[key]).strip() != '':
        try:
            return cc.ev(b, key)
        except Exception:
            return str(b.params[key]).strip().strip('"\'')
    return default


def pstr(cc, b, key, default):
    v = pp(cc, b, key, default)
    return str(v).strip().strip('"\'').lower()


def pbool(cc, b, key, default=False):
    v = pp(cc, b, key, default)
    if isinstance(v, str):
        return v.lower() in ('true', '1', 'yes')
    return bool(v)


def ctrl0(en=True, drop=False, repeat=False):
    return int(en) | (int(drop) << 3) | (int(repeat) << 4)


def timing(cc, hz):
    """24.8 fixed-point clocks"""
    if not hz:
        return 0
    return int(round(cc.clk / float(hz) * 256))


def field_fmt(t, dbits, cplx):
    """stream format of an SPI or GPIO endpoint: the field of DBITS bits per component"""
    if t in ('float', 'complex'):
        return Fmt(dbits, dbits - 1, cplx, True)
    if t == 'byte':
        return Fmt(dbits, 0, cplx, False)
    return Fmt(dbits, 0, cplx, True)


def to_fmt(cc, b, net, tgt, name):
    """convert a stream to the format an output endpoint needs (rounding, saturation)"""
    if net.fmt == tgt:
        return net
    f = net.fmt
    if f.cplx != tgt.cplx:
        cc.diag.err('E201', f'{b.name}: {"complex" if f.cplx else "real"} stream into a '
                            f'{"complex" if tgt.cplx else "real"} endpoint')
    p = dict(IW=f.w, CPLX=int(f.cplx), ISIGNED=int(f.signed), OW=tgt.w, OSIGNED=int(tgt.signed), MULK=0, KW=18, K=1,
             SHIFT=f.f - tgt.f, ROUND=1, SAT=1, OREG=0 if cc.slices == 'none' else 1)
    i = mk(cc, b, 'grv_convert', p, ins=[(net, f.w)], outs=[(tgt, min(net.rng, tgt.maxval()))], name=name)
    i.meta.update(latency=2)
    for o in i.outs:
        o.rate = net.rate
    cc.diag.note(f'{b.name}: stream converted from {f} to {tgt} for the endpoint')
    return i.outs[0]


def info_common(of):
    return dict(CW=of.w, NC=of.nc, SIGNED=int(of.signed), FRAC=max(of.f, 0))


def pe_inst(cc, b, module, params, ins, outs, direction, kind, pins, ties, anchor=None, **ep):
    i = mk(cc, b, module, params, ins=ins, outs=outs, kind='pe', ovf=False)
    i.ep = dict(dir=direction, pkind=kind, pins=pins, ties=ties, **ep)
    i.model = False
    i.extra['run'] = 'run'
    if anchor:
        for o in i.outs:
            o.rate = anchor
        i.meta['anchor'] = anchor
    return i


# ------------------------------------------------------------------ UART
def uart_format(cc, b, sink):
    par = {'none': 0, 'even': 1, 'odd': 2, '0': 0, '1': 1, '2': 2}.get(pstr(cc, b, 'parity', 'none'), 0)
    stop2 = int(float(pp(cc, b, 'stop_bits', 1) or 1)) == 2
    fmt = par | (int(stop2) << 2) | (int(pbool(cc, b, 'msb_first')) << 3) | (int(pbool(cc, b, 'flow')) << 4) \
        | (int(pbool(cc, b, 'invert')) << 5) | (int(sink and pbool(cc, b, 'text')) << 6) \
        | ((int(pp(cc, b, 'gap', 0) or 0) & 0xFF) << 8)
    if not sink:
        fmt |= (int(pp(cc, b, 'frame', 0) or 0) & 0xFFFF) << 16
    bits = 10 + (par != 0) + stop2
    return fmt, bits


def uart_baud(cc, b):
    baud = float(pp(cc, b, 'baud', 115200))
    tm = timing(cc, baud)
    if tm < 8 * 256:
        cc.diag.err('E605', f'{b.name}: {baud:g} Bd needs at least 8 clocks per bit ({cc.clk / 8:g} Bd at most)')
    return baud, tm


@mapper('grv_uart_source')
def m_uart_src(cc, b, ins):
    t = gtype(cc, b, 'byte')
    of = cc.fmt_for(t, 1.0, b.prag)
    rng = of.maxval() if t not in INT_FMT else float(2 ** (of.w - 1))
    baud, tm = uart_baud(cc, b)
    fmt, bits = uart_format(cc, b, False)
    nb = (of.tw + 7) // 8
    depth = pow2(int(pp(cc, b, 'depth', 64) or 64))
    p = dict(W=of.tw, DEPTH=depth, CTRL0=ctrl0(), TIMING0=tm, FORMAT0=fmt, THRESH0=1, **info_common(of))
    pins = [('rxd', 'in', 1, 'rxd')] + ([('rts_n', 'out', 1, 'rts_n')] if fmt & 0x10 else [])
    i = pe_inst(cc, b, 'grv_pe_uart_rx', p, [], [(of, rng)], 'in', 'uart', pins, {}, anchor=baud / (bits * nb),
                baud=baud, fmt=of, depth=depth, bits=bits, nb=nb, fmtw=fmt)
    i.cost.update(lut=130 + 30 * nb, bram=bram_for(depth * (of.tw + 1)))
    return i.outs


@mapper('grv_uart_sink')
def m_uart_snk(cc, b, ins):
    x = ins[0]
    baud, tm = uart_baud(cc, b)
    fmt, bits = uart_format(cc, b, True)
    depth = pow2(int(pp(cc, b, 'depth', 64) or 64))
    f = x.fmt
    nb = (f.tw + 7) // 8
    chars = ((f.tw + 3) // 4 + 1) if fmt & 0x40 else nb
    p = dict(W=f.tw, DEPTH=depth, VEC=int(x.vlen > 1), CTRL0=ctrl0(drop=pbool(cc, b, 'drop')), TIMING0=tm, FORMAT0=fmt,
             THRESH0=0, **info_common(f))
    pins = [('txd', 'out', 1, 'txd')] + ([('cts_n', 'in', 1, 'cts_n')] if fmt & 0x10 else [])
    ties = {} if fmt & 0x10 else {'cts_n': "1'b0"}
    i = pe_inst(cc, b, 'grv_pe_uart_tx', p, [(x, f.w)], [], 'out', 'uart', pins, ties, baud=baud, fmt=f, depth=depth,
                cap=baud / (bits * chars), bits=bits, nb=nb, text=bool(fmt & 0x40), fmtw=fmt)
    i.cost.update(lut=110 + 30 * nb + (60 if fmt & 0x40 else 0), bram=bram_for(depth * (f.tw + 1)))
    return []


# ------------------------------------------------------------------ SPI
def spi_settings(cc, b):
    role = pstr(cc, b, 'role', 'master')
    slave = role in ('slave', '1')
    fb = int(pp(cc, b, 'frame_bits', 16))
    dpos = int(pp(cc, b, 'data_pos', 0) or 0)
    db = int(pp(cc, b, 'data_bits', 12))
    if not 1 <= fb <= 32 or not 1 <= db <= 32 or dpos + db > fb:
        cc.diag.err('E606', f'{b.name}: field of {db} bits at {dpos} does not fit a frame of {fb} bits (1 .. 32)')
    mode = int(pp(cc, b, 'mode', 0) or 0) & 3
    fmt = (fb - 1) | (dpos << 8) | ((mode & 1) << 16) | ((mode >> 1) << 17) | (int(pbool(cc, b, 'lsb_first')) << 18) \
        | (int(pbool(cc, b, 'offset_binary')) << 19) | ((int(pp(cc, b, 'sample_delay', 0) or 0) & 3) << 20)
    sclk = float(pp(cc, b, 'sclk', cc.clk / 4) or cc.clk / 4)
    half = max(0, min(255, int(math.ceil(cc.clk / (2 * sclk))) - 1))
    if slave and sclk > cc.clk / 8:
        cc.diag.warn('W603', f'{b.name}: SPI slave clock {sclk:g} Hz above clk / 8')
    cst = (int(pp(cc, b, 'cs_setup', 1) or 1) & 0xFF) | ((int(pp(cc, b, 'cs_hold', 1) or 1) & 0xFF) << 8) \
        | ((int(pp(cc, b, 'cs_gap', 1) or 1) & 0xFF) << 16)
    cmd = int(pp(cc, b, 'cmd', 0) or 0) & 0xFFFFFFFF
    cmdq = int(pp(cc, b, 'cmd_q', 0) or 0) & 0xFFFFFFFF
    sr = pp(cc, b, 'samp_rate', None)
    sr = float(sr) if sr else None
    return slave, fb, db, fmt, half, cst, cmd, cmdq, sr


def spi_check(cc, b, fb, half, cst, nc, sr, slave):
    if slave or not sr:
        return
    per = cc.clk / sr
    need = nc * ((cst & 0xFF or 1) + 2 * fb * (half + 1) + ((cst >> 8) & 0xFF or 1) + ((cst >> 16) & 0xFF or 1) + 6)
    if need > per:
        cc.diag.err('E602', f'{b.name}: SPI transfer of {need} clocks is longer than the sample period of {per:.0f} clocks')


@mapper('grv_spi_source')
def m_spi_src(cc, b, ins):
    t = gtype(cc, b, 'float')
    slave, fb, db, fmt, half, cst, cmd, cmdq, sr = spi_settings(cc, b)
    cplx = t == 'complex'
    of = field_fmt(t, db, cplx)
    if not slave and not sr:
        cc.diag.err('E607', f'{b.name}: an SPI master input needs samp_rate')
    spi_check(cc, b, fb, half, cst, of.nc, sr, slave)
    depth = pow2(int(pp(cc, b, 'depth', 32) or 32))
    p = dict(DBITS=db, NC=of.nc, SIGNED=int(of.signed), FRAC=max(of.f, 0), DEPTH=depth, ROLE=int(slave), CTRL0=ctrl0(),
             TIMING0=0 if slave else timing(cc, sr), FORMAT0=fmt, THRESH0=1, SCLK0=half, CMD0=cmd, CMDQ0=cmdq, CST0=cst)
    if slave:
        pins = [('sclk', 'in', 1, 'sclk_i'), ('cs_n', 'in', 1, 'cs_n_i'), ('mosi', 'in', 1, 'mosi_i')]
        ties = {'miso_i': "1'b0"}
    else:
        pins = [('sclk', 'out', 1, 'sclk_o'), ('cs_n', 'out', 1, 'cs_n_o'), ('mosi', 'out', 1, 'mosi_o'), ('miso', 'in', 1, 'miso_i')]
        ties = {'sclk_i': "1'b0", 'cs_n_i': "1'b1", 'mosi_i': "1'b0"}
    rng = of.maxval() if t not in INT_FMT else float(2 ** (db - 1))
    i = pe_inst(cc, b, 'grv_pe_spi_rx', p, [], [(of, rng)], 'in', 'spi_slave' if slave else 'spi_master', pins, ties,
                anchor=sr, fmt=of, depth=depth, fb=fb, dpos=(fmt >> 8) & 31, cmd=cmd, cmdq=cmdq, half=half,
                mode=(fmt >> 16) & 3, lsbf=bool(fmt & (1 << 18)), ofs=bool(fmt & (1 << 19)), db=db, cst=cst)
    i.cost.update(lut=190 if not slave else 160, bram=bram_for(depth * (of.tw + 1)))
    return i.outs


@mapper('grv_spi_sink')
def m_spi_snk(cc, b, ins):
    x = ins[0]
    slave, fb, db, fmt, half, cst, cmd, cmdq, sr = spi_settings(cc, b)
    tgt = field_fmt(gtype(cc, b, 'float') if not x.fmt.cplx else 'complex', db, x.fmt.cplx)
    x = to_fmt(cc, b, x, tgt, f'{b.name}_q')
    spi_check(cc, b, fb, half, cst, tgt.nc, sr, slave)
    depth = pow2(int(pp(cc, b, 'depth', 32) or 32))
    p = dict(DBITS=db, NC=tgt.nc, SIGNED=int(tgt.signed), FRAC=max(tgt.f, 0), DEPTH=depth, ROLE=int(slave),
             CTRL0=ctrl0(drop=pbool(cc, b, 'drop'), repeat=pbool(cc, b, 'repeat')),
             TIMING0=0 if (slave or not sr) else timing(cc, sr), FORMAT0=fmt, THRESH0=1, SCLK0=half, CMD0=cmd,
             CMDQ0=cmdq, CST0=cst)
    if slave:
        pins = [('sclk', 'in', 1, 'sclk_i'), ('cs_n', 'in', 1, 'cs_n_i'), ('miso', 'out', 1, 'miso_o'),
                ('miso_oe', 'out', 1, 'miso_oe'), ('drdy', 'out', 1, 'drdy')]
        ties = {'mosi_i': "1'b0"}
    else:
        pins = [('sclk', 'out', 1, 'sclk_o'), ('cs_n', 'out', 1, 'cs_n_o'), ('mosi', 'out', 1, 'mosi_o')]
        ties = {'sclk_i': "1'b0", 'cs_n_i': "1'b1", 'mosi_i': "1'b0"}
    i = pe_inst(cc, b, 'grv_pe_spi_tx', p, [(x, tgt.w)], [], 'out', 'spi_slave' if slave else 'spi_master', pins, ties,
                fmt=tgt, depth=depth, fb=fb, dpos=(fmt >> 8) & 31, cmd=cmd, cmdq=cmdq, half=half, pace=sr if not slave else None,
                mode=(fmt >> 16) & 3, lsbf=bool(fmt & (1 << 18)), ofs=bool(fmt & (1 << 19)), db=db, cst=cst)
    i.cost.update(lut=190 if not slave else 160, bram=bram_for(depth * (tgt.tw + 1)))
    return []


# ------------------------------------------------------------------ GPIO
GPIO_IN = {'periodic': 0, 'strobe': 1, 'change': 2}
GPIO_OUT = {'parallel': 0, 'pwm': 1, 'sdm': 2}


@mapper('grv_gpio_source')
def m_gpio_src(cc, b, ins):
    t = gtype(cc, b, 'byte')
    mode = GPIO_IN.get(pstr(cc, b, 'mode', 'periodic'), 0)
    cplx = t == 'complex'
    npin = pp(cc, b, 'pins', None)
    db = int(pp(cc, b, 'data_bits', 0) or 0)            # 0: pins / components
    if db == 0:
        db = int(npin or 8) // (2 if cplx else 1)
    of = field_fmt(t, db, cplx)
    if npin is not None and int(npin) != of.tw:
        cc.diag.err('E606', f'{b.name}: {npin} pins for {of.nc} x {db} data bits')
    if not 1 <= db <= 32:
        cc.diag.err('E606', f'{b.name}: {db} data bits (1 .. 32)')
    sr = pp(cc, b, 'samp_rate', None)
    sr = float(sr) if sr else None
    if mode == 0 and not sr:
        cc.diag.err('E607', f'{b.name}: a periodic GPIO input needs samp_rate')
    clko = pbool(cc, b, 'clk_out')
    fmt = mode | (int(pstr(cc, b, 'edge', 'rising') in ('falling', '1')) << 2) | (int(pbool(cc, b, 'offset_binary')) << 3) \
        | (int(clko) << 4) | ((int(pp(cc, b, 'phase', 2) or 0) & 0xFF) << 8) | ((int(pp(cc, b, 'filter', 4) or 0) & 0xFF) << 16)
    depth = pow2(int(pp(cc, b, 'depth', 32) or 32))
    p = dict(DBITS=db, NC=of.nc, SIGNED=int(of.signed), FRAC=max(of.f, 0), DEPTH=depth, CTRL0=ctrl0(),
             TIMING0=timing(cc, sr) if mode == 0 else 0, FORMAT0=fmt, THRESH0=1)
    pins = [('in', 'in', of.tw, 'pins_i')]
    ties = {}
    if mode == 1:
        pins.append(('stb', 'in', 1, 'stb_i'))
    else:
        ties['stb_i'] = "1'b0"
    if clko and mode == 0:
        pins.append(('clk', 'out', 1, 'clk_o'))
    rng = of.maxval() if t not in INT_FMT else float(2 ** (db - 1))
    i = pe_inst(cc, b, 'grv_pe_gpio_in', p, [], [(of, rng)], 'in', 'gpio', pins, ties,
                anchor=sr if mode == 0 else None, fmt=of, depth=depth, gmode=mode, db=db, ofs=bool(fmt & 8),
                phase=(fmt >> 8) & 0xFF, filt=(fmt >> 16) & 0xFF, clko=clko, distinct=mode == 2,
                edge=bool(fmt & 4), pace=sr if mode == 0 else None)
    if mode != 0 and sr:
        for o in i.outs:
            o.rate = sr
    i.cost.update(lut=70 + 3 * of.tw, bram=bram_for(depth * of.tw))
    return i.outs


@mapper('grv_gpio_sink')
def m_gpio_snk(cc, b, ins):
    x = ins[0]
    mode = GPIO_OUT.get(pstr(cc, b, 'mode', 'parallel'), 0)
    t = gtype(cc, b, 'float') if not x.fmt.cplx else 'complex'
    pins_p = pp(cc, b, 'pins', None)
    db = int(pp(cc, b, 'data_bits', 0) or 0)            # 0: pins / components (parallel), 8 (PWM), 12 (sigma-delta)
    if db == 0:
        db = int(pins_p) // x.fmt.nc if (pins_p and mode == 0) else (8 if mode == 1 else 12 if mode == 2 else 8)
    tgt = field_fmt(t, db, x.fmt.cplx)
    x = to_fmt(cc, b, x, tgt, f'{b.name}_q')
    sr = pp(cc, b, 'samp_rate', None)
    sr = float(sr) if sr else None
    clko = pbool(cc, b, 'clk_out')
    sdo1 = int(pp(cc, b, 'sdm_order', 2) or 2) == 1
    fmt = mode | (int(pbool(cc, b, 'offset_binary')) << 3) | (int(clko) << 4) | (int(sdo1) << 5) \
        | ((int(pp(cc, b, 'phase', 1) or 0) & 0xFF) << 8) | ((int(pp(cc, b, 'sdm_div', 0) or 0) & 0xFF) << 16)
    npin = tgt.tw if mode == 0 else tgt.nc
    if pins_p is not None and mode == 0 and int(pins_p) != npin:
        cc.diag.err('E606', f'{b.name}: {pins_p} pins, the mode needs {npin}')
    depth = pow2(int(pp(cc, b, 'depth', 32) or 32))
    if mode == 1 and db > 16:
        cc.diag.err('E606', f'{b.name}: PWM with {db} bits (period 2^{db} clocks); use at most 16')
    p = dict(DBITS=db, NC=tgt.nc, NPIN=npin, SIGNED=int(tgt.signed), FRAC=max(tgt.f, 0), DEPTH=depth,
             CTRL0=ctrl0(drop=pbool(cc, b, 'drop'), repeat=pbool(cc, b, 'repeat', True)),
             TIMING0=timing(cc, sr) if sr else 0, FORMAT0=fmt, THRESH0=0)
    pins = [('out', 'out', npin, 'pins_o')]
    if clko and mode == 0:
        pins.append(('clk', 'out', 1, 'clk_o'))
    i = pe_inst(cc, b, 'grv_pe_gpio_out', p, [(x, tgt.w)], [], 'out', 'gpio', pins, {}, fmt=tgt, depth=depth,
                gmode=mode, db=db, pace=sr, ofs=bool(fmt & 8), clko=clko, phase=(fmt >> 8) & 0xFF,
                sdm_order=1 if sdo1 else 2, sdm_div=(fmt >> 16) & 0xFF, npin=npin)
    i.cost.update(lut=60 + 2 * npin + (tgt.nc * (2 * db + 20) if mode == 1 else 0) + (tgt.nc * (4 * (db + 4) + 20) if mode == 2 else 0),
                  bram=bram_for(depth * tgt.tw))
    return []


# ------------------------------------------------------------------ I2S
I2S_JUST = {'i2s': 0, 'left': 1, 'left_justified': 1, 'right': 2, 'right_justified': 2, '0': 0, '1': 1, '2': 2}


def i2s_settings(cc, b, cplx, sink):
    slave = pstr(cc, b, 'role', 'master') in ('slave', '1')
    slot = int(pp(cc, b, 'slot_bits', 32) or 32)
    db = int(pp(cc, b, 'data_bits', 16) or 16)
    just = I2S_JUST.get(pstr(cc, b, 'format', 'i2s'), 0)
    if not 8 <= slot <= 32 or not 8 <= db <= slot:
        cc.diag.err('E606', f'{b.name}: {db} data bits in a slot of {slot} bits (8 <= data bits <= slot bits <= 32)')
    mono_r = (not cplx) and pstr(cc, b, 'channel', 'left') in ('right', '1')
    dup = (not cplx) and sink and pbool(cc, b, 'duplicate')
    sr = pp(cc, b, 'samp_rate', None)
    sr = float(sr) if sr else None
    fmt = (slot - 1) | (just << 8) | (int(mono_r) << 10) | (int(dup) << 11) | (int(pbool(cc, b, 'ws_invert')) << 13)
    tm, mdiv = 0, 0
    if not slave:
        if not sr:
            cc.diag.err('E607', f'{b.name}: an I2S master needs samp_rate')
        else:
            tm = int(round(cc.clk / (4.0 * slot * sr) * 256))
            if tm < 4 * 256:
                cc.diag.err('E610', f'{b.name}: bit clock {2 * slot * sr / 1e6:.4g} MHz above clk / 8 '
                                    f'({cc.clk / 8e6:.4g} MHz); use a shorter slot or a faster clock')
            elif abs(cc.clk / (4.0 * slot * tm / 256) - sr) > sr * 1e-3:
                cc.diag.note(f'{b.name}: frame rate {cc.clk / (4.0 * slot * tm / 256):.6g} Hz for {sr:g} Hz')
        mclk = float(pp(cc, b, 'mclk', 0) or 0)
        if mclk:
            fmt |= 1 << 16
            mdiv = max(0, min(255, int(round(cc.clk / (2 * mclk))) - 1))
            real = cc.clk / (2 * (mdiv + 1))
            if abs(real - mclk) > mclk * 0.01:
                cc.diag.warn('W605', f'{b.name}: master clock {real / 1e6:.4g} MHz for {mclk / 1e6:.4g} MHz '
                                     f'(clk / {2 * (mdiv + 1)}); codecs with a PLL accept it')
    elif sr and 2 * slot * sr > cc.clk / 8:
        cc.diag.warn('W603', f'{b.name}: I2S slave bit clock {2 * slot * sr / 1e6:.4g} MHz above clk / 8')
    return slave, slot, db, just, fmt, tm, mdiv, sr, mono_r, dup


def i2s_fmt(t, db, cplx):
    return Fmt(db, db - 1 if t in ('float', 'complex') else 0, cplx, True)


def i2s_pins(slave, sink, mclk):
    if slave:
        pins = [('bclk', 'in', 1, 'bclk_i'), ('ws', 'in', 1, 'ws_i')]
        ties = {}
    else:
        pins = [('bclk', 'out', 1, 'bclk_o'), ('ws', 'out', 1, 'ws_o')] + ([('mclk', 'out', 1, 'mclk_o')] if mclk else [])
        ties = {'bclk_i': "1'b0", 'ws_i': "1'b0"}
    pins.append(('sd', 'out', 1, 'sd_o') if sink else ('sd', 'in', 1, 'sd_i'))
    return pins, ties


@mapper('grv_i2s_source')
def m_i2s_src(cc, b, ins):
    t = gtype(cc, b, 'complex')
    cplx = t == 'complex'
    slave, slot, db, just, fmt, tm, mdiv, sr, mono_r, dup = i2s_settings(cc, b, cplx, False)
    of = i2s_fmt(t, db, cplx)
    depth = pow2(int(pp(cc, b, 'depth', 32) or 32))
    p = dict(DBITS=db, NC=of.nc, SIGNED=1, FRAC=max(of.f, 0), DEPTH=depth, ROLE=int(slave), CTRL0=ctrl0(),
             TIMING0=tm, FORMAT0=fmt, THRESH0=1, MCLK0=mdiv)
    pins, ties = i2s_pins(slave, False, fmt & (1 << 16))
    rng = of.maxval() if t not in INT_FMT else float(2 ** (db - 1))
    i = pe_inst(cc, b, 'grv_pe_i2s_rx', p, [], [(of, rng)], 'in', 'i2s', pins, ties, anchor=None if slave else sr,
                fmt=of, depth=depth, slot=slot, db=db, just=just, slave=slave, mono_r=mono_r, dup=False,
                wsinv=bool(fmt & (1 << 13)))
    if slave and sr:
        for o in i.outs:
            o.rate = sr
    i.cost.update(lut=110 + 2 * of.tw, bram=bram_for(depth * of.tw))
    return i.outs


@mapper('grv_i2s_sink')
def m_i2s_snk(cc, b, ins):
    x = ins[0]
    cplx = x.fmt.cplx
    t = 'complex' if cplx else gtype(cc, b, 'float')
    slave, slot, db, just, fmt, tm, mdiv, sr, mono_r, dup = i2s_settings(cc, b, cplx, True)
    tgt = i2s_fmt(t, db, cplx)
    x = to_fmt(cc, b, x, tgt, f'{b.name}_q')
    depth = pow2(int(pp(cc, b, 'depth', 32) or 32))
    p = dict(DBITS=db, NC=tgt.nc, SIGNED=1, FRAC=max(tgt.f, 0), DEPTH=depth, ROLE=int(slave),
             CTRL0=ctrl0(drop=pbool(cc, b, 'drop'), repeat=pbool(cc, b, 'repeat')), TIMING0=tm, FORMAT0=fmt,
             THRESH0=0, MCLK0=mdiv)
    pins, ties = i2s_pins(slave, True, fmt & (1 << 16))
    i = pe_inst(cc, b, 'grv_pe_i2s_tx', p, [(x, tgt.w)], [], 'out', 'i2s', pins, ties, fmt=tgt, depth=depth,
                slot=slot, db=db, just=just, slave=slave, mono_r=mono_r, dup=dup, pace=sr,
                wsinv=bool(fmt & (1 << 13)))
    i.cost.update(lut=110 + 2 * tgt.tw, bram=bram_for(depth * tgt.tw))
    return []


# ------------------------------------------------------------------ DMA
DMA_MODES = {'single': 0, 'ring': 1, 'desc': 2, 'descriptor': 2}


def container(w):
    return 1 if w <= 8 else 2 if w <= 16 else 4


def dma_ctrl(cc, b, en, sink):
    mode = DMA_MODES.get(pstr(cc, b, 'mode', 'single'), 0)
    burst = max(1, min(16, int(pp(cc, b, 'burst', 1) or 1)))
    c = int(en) | (mode << 2) | (int(pbool(cc, b, 'flow')) << 7) | (int(sink and pbool(cc, b, 'drop')) << 8) \
        | (int(pbool(cc, b, 'msb_align')) << 9) | (int(pbool(cc, b, 'eof_last')) << 10) | ((burst - 1) << 12) \
        | ((int(pp(cc, b, 'gap', 0) or 0) & 0xFF) << 16) | (int(pbool(cc, b, 'prio')) << 24)
    return c, mode


def dma_common(cc, b, f, sink):
    addr = int(pp(cc, b, 'address', 0) or 0) & 0xFFFFFFFF
    length = int(pp(cc, b, 'length', 0) or 0)
    ctrl, mode = dma_ctrl(cc, b, addr != 0 and length != 0, sink)
    if addr & 3:
        cc.diag.err('E608', f'{b.name}: DMA buffer address 0x{addr:x} is not 4-byte aligned')
    depth = pow2(int(pp(cc, b, 'depth', 32) or 32))
    cb = container(f.w)
    p = dict(DIR=int(sink), W=f.tw, CW=f.w, NC=f.nc, SIGNED=int(f.signed), FRAC=max(f.f, 0), CB=cb, DEPTH=depth,
             CTRL0=ctrl, ADDR0=addr, LEN0=length, WM0=int(pp(cc, b, 'watermark', 0) or 0),
             FRAME0=int(pp(cc, b, 'frame', 0) or 0))
    return p, dict(fmt=f, depth=depth, cb=cb, eb=cb * f.nc, mode=mode, addr=addr, length=length)


@mapper('grv_dma_source')
def m_dma_src(cc, b, ins):
    t = gtype(cc, b, 'complex')
    of = cc.fmt_for(t, 1.0, b.prag)
    rng = of.maxval() if t not in INT_FMT else float(2 ** (of.w - 1))
    vlen = int(pp(cc, b, 'vlen', 1) or 1)
    if vlen > 1 and not int(pp(cc, b, 'frame', 0) or 0):
        b.prag['frame'] = str(vlen)                     # tlast at the end of each vector
    p, ep = dma_common(cc, b, of, False)
    i = mk(cc, b, 'grv_dma_ch', p, outs=[(of, rng, 1, vlen)], kind='dma', ovf=False)
    i.ep = dict(dir='in', **ep)
    i.model = False
    i.extra['run'] = 'run'
    sr = pp(cc, b, 'samp_rate', None)
    if sr:
        for o in i.outs:
            o.rate = float(sr)
        i.meta['anchor'] = float(sr)
    i.cost.update(lut=420, bram=0)
    return i.outs


@mapper('grv_dma_sink')
def m_dma_snk(cc, b, ins):
    x = ins[0]
    p, ep = dma_common(cc, b, x.fmt, True)
    i = mk(cc, b, 'grv_dma_ch', p, ins=[(x, x.fmt.w)], kind='dma', ovf=False)
    i.ep = dict(dir='out', **ep)
    i.model = False
    i.extra['run'] = 'run'
    i.cost.update(lut=420, bram=0)
    return []


# ------------------------------------------------------------------ @grv via=... on standard blocks
VIA = {('i2s', 'src'): m_i2s_src, ('i2s', 'snk'): m_i2s_snk, ('uart', 'src'): m_uart_src, ('uart', 'snk'): m_uart_snk, ('spi', 'src'): m_spi_src, ('spi', 'snk'): m_spi_snk,
       ('gpio', 'src'): m_gpio_src, ('gpio', 'snk'): m_gpio_snk, ('dma', 'src'): m_dma_src, ('dma', 'snk'): m_dma_snk}


def via(cc, b, ins, side):
    v = b.prag.get('via')
    if not v or v in ('axil', 'pad'):
        return None
    f = VIA.get((str(v).lower(), side))
    if f is None:
        cc.diag.err('E609', f'{b.name}: @grv via={v} (uart, spi, i2s, gpio, dma, axil or pad)')
    b.via = True
    return f(cc, b, ins)
