"""Emitters: top-level Verilog, file list, C header, address map, graph model, report."""
import os, json, math, datetime
from .fx import to_u
from .expr import GrvError
from . import vports

VERSION = '0.3'
DROP_OK = ('ROUND', 'SAT', 'OREG')


def vnum(v, w):
    return f"{w}'h{to_u(int(v), w):x}"


def vparam(v):
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, tuple):
        w, u = v
        return f"{w}'h{u:x}"
    v = int(v)
    if v < 0:
        return f'-{-v}'
    return str(v)


def rparam(k, v):
    """reset values of 32-bit registers in hexadecimal"""
    if k.endswith('0') and isinstance(v, int) and k not in ('DIR',):
        return f"32'h{v & 0xFFFFFFFF:08x}"
    return vparam(v)


def cname(s):
    import re
    return re.sub(r'[^A-Za-z0-9_]', '_', s).upper()


# ------------------------------------------------------------------ preparation (names, checks)
def prepare(cc):
    used = set()
    for i in cc.insts:
        if i.kind == 'pad_in':
            used.add(i.ep['label'])
        if i.kind == 'pad_out':
            used.add(i.ep['label'])
    for i in cc.insts:
        for k, n in enumerate(i.outs):
            base = i.name if len(i.outs) == 1 else f'{i.name}_{k}'
            if base in used or base in ('clk', 'rst_n', 'run', 'irq', 'grst_n', 'cfg_live', 'ovf'):
                base += '_o'
            n.name = base
            used.add(base)
    for i in cc.insts:
        if i.kind not in ('block', 'fork', 'src', 'snk', 'pe', 'dma'):
            continue
        mi = vports.info(i.module)
        for k in list(i.params):
            if k not in mi.params:
                if k in DROP_OK:
                    del i.params[k]
                else:
                    raise GrvError(f'internal: module {i.module} has no parameter {k} ({i.name})')
        i.ovf = bool(i.ovf) and 'ovf' in mi.ports
        given = {c.port for c in i.cfg} | set(i.extra)
        for p in mi.ports:
            if p.startswith('cfg_') and p not in given:
                raise GrvError(f'internal: {i.name} ({i.module}) has no value for port {p}')


# ------------------------------------------------------------------ Verilog
def in_expr(net, w, raw):
    f = net.fmt
    if raw or w == f.w:
        if raw and w != f.tw:
            raise GrvError(f'internal: raw input of width {w} from {net.name} ({f})')
        return f'{net.name}_tdata'
    if w < f.w:
        raise GrvError(f'internal: input of width {w} narrower than {net.name} ({f})')
    parts = []
    for c in reversed(range(f.nc)):
        hi = c * f.w + f.w - 1
        ext = f'{{{w - f.w}{{{net.name}_tdata[{hi}]}}}}' if f.signed else f"{w - f.w}'d0"
        parts.append(f'{ext}, {net.name}_tdata[{c * f.w} +: {f.w}]')
    return '{' + ', '.join(parts) + '}'


def cat(xs):
    xs = list(xs)
    return xs[0] if len(xs) == 1 else '{' + ', '.join(reversed(xs)) + '}'


def cfg_expr(cc, c):
    if c.const is not None:
        return vnum(c.const, c.width)
    if c.param is not None:
        return f'p_{c.param.name}'
    pidx, vals, _ = c.mux
    e = vnum(vals[-1], c.width)
    for k in reversed(range(len(vals) - 1)):
        e = f'(p_{pidx.name} == 8\'d{k}) ? {vnum(vals[k], c.width)} : {e}'
    return f'({e})'


def describe(i):
    f_in = ', '.join(repr(n.fmt) for n, _ in i.ins)
    f_out = ', '.join(repr(n.fmt) for n in i.outs)
    s = f"{i.module} '{i.name}'"
    if i.blk is not None:
        s += f' from {i.blk.id} {i.blk.name}'
    if f_in or f_out:
        s += f': {f_in or "-"} -> {f_out or "-"}'
    ii = i.meta.get('ii', 1)
    if ii > 1:
        s += f', II {ii}'
    return s


PE_KIND = {'uart': 'UART', 'spi_master': 'SPI master', 'spi_slave': 'SPI slave', 'gpio': 'GPIO', 'i2s': 'I2S'}
GPIO_MODES = {('in', 0): 'periodic', ('in', 1): 'strobe', ('in', 2): 'change',
              ('out', 0): 'parallel', ('out', 1): 'PWM', ('out', 2): 'sigma-delta'}


def pe_desc(i):
    e = i.ep
    s = f'{PE_KIND[e["pkind"]]} {"input" if e["dir"] == "in" else "output"}, {e["fmt"]}'
    if e['pkind'] == 'uart':
        s += f', {e["baud"]:g} Bd' + (', text' if e.get('text') else '')
    elif e['pkind'] == 'gpio':
        s += f', {GPIO_MODES[(e["dir"], e["gmode"])]}'
    elif e['pkind'] == 'i2s':
        s = (f'I2S {"slave" if e["slave"] else "master"} {"input" if e["dir"] == "in" else "output"}, {e["fmt"]}, '
             f'{["I2S", "left-justified", "right-justified"][e["just"]]}, {e["db"]} of {e["slot"]} bits'
             + ('' if e['fmt'].cplx else f', mono {"right" if e["mono_r"] else "left"}' + (' and right' if e['dup'] else '')))
    else:
        s += f', {e["fb"]}-bit frames, mode {e["mode"]}'
    r = e.get('pace') or (i.outs[0].rate if i.outs else None)
    if r:
        s += f', {r / 1e3:g} kS/s'
    return s


def dma_desc(i):
    e = i.ep
    return (f'{"MM2S" if e["dir"] == "in" else "S2MM"}, {e["fmt"]}, {e["cb"]}-byte containers, '
            f'{e["eb"]}-byte elements, {["SINGLE", "RING", "DESC"][e["mode"]]}')


def emit_verilog(cc, d):
    top = cc.top
    srcs, snks, prbs = cc.srcs, cc.snks, cc.prbs
    pes, dmas = cc.pes, cc.dmas
    ns, nk, npb, ne, nd = len(srcs), len(snks), len(prbs), len(pes), len(dmas)
    tp = 1 + ns + nk + (1 if npb else 0)          # first peripheral endpoint target
    nt = tp + ne + nd
    pads_in = [i for i in cc.insts if i.kind == 'pad_in']
    pads_out = [i for i in cc.insts if i.kind == 'pad_out']
    novf = len(cc.ovf_list)
    L = []
    w = L.append
    w(f'// {top} - generated by grvgen {VERSION} from {os.path.basename(cc.path)}; do not edit.\n')
    w(f'// graph hash 0x{cc.hash:08x}, {len(cc.insts)} instances, clock {cc.clk / 1e6:g} MHz.\n')
    w('`default_nettype none\n\n')
    ports = ['  input  wire        clk', '  input  wire        rst_n',
             '  input  wire [15:0] s_axil_awaddr', '  input  wire        s_axil_awvalid', '  output wire        s_axil_awready',
             '  input  wire [31:0] s_axil_wdata', '  input  wire [3:0]  s_axil_wstrb', '  input  wire        s_axil_wvalid',
             '  output wire        s_axil_wready', '  output wire [1:0]  s_axil_bresp', '  output wire        s_axil_bvalid',
             '  input  wire        s_axil_bready', '  input  wire [15:0] s_axil_araddr', '  input  wire        s_axil_arvalid',
             '  output wire        s_axil_arready', '  output wire [31:0] s_axil_rdata', '  output wire [1:0]  s_axil_rresp',
             '  output wire        s_axil_rvalid', '  input  wire        s_axil_rready', '  output wire        irq']
    for p in pads_in:
        n, lb = p.outs[0], p.ep['label']
        ports += [f'  // pad source {p.name}: {n.fmt}', f'  input  wire [{n.fmt.tw - 1}:0] {lb}_tdata', f'  input  wire        {lb}_tvalid',
                  f'  output wire        {lb}_tready', f'  input  wire        {lb}_tlast']
    for p in pads_out:
        n, lb = p.ins[0][0], p.ep['label']
        ports += [f'  // pad sink {p.name}: {n.fmt}', f'  output wire [{n.fmt.tw - 1}:0] {lb}_tdata', f'  output wire        {lb}_tvalid',
                  f'  input  wire        {lb}_tready', f'  output wire        {lb}_tlast']
    for p in pes:
        ports.append(f'  // peripheral endpoint {p.name}: {pe_desc(p)}')
        for pn, d_, wd, _ in p.ep['pins']:
            ports.append(f'  {"input " if d_ == "in" else "output"} wire {f"[{wd - 1}:0] " if wd > 1 else "       "}{p.name}_{pn}')
    if dmas:
        ports += ['  // DMA memory port (PicoRV32 native interface)', '  output wire        m_mem_valid',
                  '  output wire [31:0] m_mem_addr', '  output wire [31:0] m_mem_wdata', '  output wire [3:0]  m_mem_wstrb',
                  '  input  wire        m_mem_ready', '  input  wire [31:0] m_mem_rdata']
    body = []
    for k, p in enumerate(ports):
        last = all(q.lstrip().startswith('//') for q in ports[k + 1:])
        body.append(p if p.lstrip().startswith('//') else p + ('' if last else ','))
    w(f'module {top} (\n' + '\n'.join(body) + '\n);\n\n')

    # ---- control plane
    pinit = sum(to_u(p.init, min(32, p.cfg.width)) << (32 * p.index) if p.words == 1 else
                to_u(p.init, p.cfg.width) << (32 * p.index) for p in cc.params)
    plive = 0
    for p in cc.params:
        live = not (p.var in cc.rvars and cc.blocks[cc.rvars[p.var]['block']].prag.get('commit'))
        if live and p.words == 1:
            plive |= 1 << p.index
    config = ns | (nk << 8) | (npb << 16)
    config2 = ne | (nd << 8) | ((1 if nd else 0) << 16)
    wlo, whi = getattr(cc, 'dma_window', (0, 0xFFFFFFFF))
    w('  // ---------------------------------------------------------------- control plane\n')
    w(f'  localparam integer NT = {nt};\n')
    w('  wire [15:0] rb_addr; wire [31:0] rb_wdata; wire rb_we, rb_re, rb_force;\n')
    w('  wire [NT-1:0] rb_sel, t_wrdy, t_rrdy; wire [32*NT-1:0] t_rdata;\n')
    w(f'  wire [15:0] timeout; wire run, grst_n, cfg_upd;\n  wire [{32 * cc.npw - 1}:0] cfg_live;\n')
    w(f'  wire [15:0] irq_snk, irq_src, irq_pe, irq_dma;\n  wire [31:0] dma_win_lo, dma_win_hi;\n'
      f'  wire [{max(novf, 1) - 1}:0] ovf;\n')
    w(f'  grv_axil_dec #(.NS({ns}), .NK({nk}), .NP({npb}), .NE({ne}), .ND({nd})) u_dec (.clk(clk), .rst_n(rst_n), .timeout(timeout),\n'
      '    .s_axil_awaddr(s_axil_awaddr), .s_axil_awvalid(s_axil_awvalid), .s_axil_awready(s_axil_awready),\n'
      '    .s_axil_wdata(s_axil_wdata), .s_axil_wstrb(s_axil_wstrb), .s_axil_wvalid(s_axil_wvalid), .s_axil_wready(s_axil_wready),\n'
      '    .s_axil_bresp(s_axil_bresp), .s_axil_bvalid(s_axil_bvalid), .s_axil_bready(s_axil_bready),\n'
      '    .s_axil_araddr(s_axil_araddr), .s_axil_arvalid(s_axil_arvalid), .s_axil_arready(s_axil_arready),\n'
      '    .s_axil_rdata(s_axil_rdata), .s_axil_rresp(s_axil_rresp), .s_axil_rvalid(s_axil_rvalid), .s_axil_rready(s_axil_rready),\n'
      '    .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re), .rb_force(rb_force),\n'
      '    .rb_sel(rb_sel), .t_wrdy(t_wrdy), .t_rrdy(t_rrdy), .t_rdata(t_rdata));\n')
    ovf_in = '64\'d0' if not novf else (f'{{{64 - novf}\'d0, ovf}}' if novf < 64 else 'ovf[63:0]')
    w(f'  grv_regs #(.NPW({cc.npw}), .PINIT({32 * cc.npw}\'h{pinit:x}), .PLIVE({cc.npw}\'h{plive:x}),\n'
      f'    .HASH(32\'h{cc.hash:08x}), .CONFIG(32\'h{config:08x}), .CLK_HZ(32\'d{int(cc.clk)}), .CONFIG2(32\'h{config2:08x}),\n'
      f'    .WINLO0(32\'h{wlo:08x}), .WINHI0(32\'h{whi:08x})) u_regs (\n'
      '    .clk(clk), .rst_n(rst_n), .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re),\n'
      '    .rb_sel(rb_sel[0]), .t_wrdy(t_wrdy[0]), .t_rrdy(t_rrdy[0]), .t_rdata(t_rdata[0 +: 32]),\n'
      '    .run(run), .graph_rst_n(grst_n), .cfg_upd(cfg_upd), .cfg_live(cfg_live),\n'
      f'    .irq_snk(irq_snk), .irq_src(irq_src), .irq_pe(irq_pe), .irq_dma(irq_dma), .dma_win_lo(dma_win_lo),\n'
      f'    .dma_win_hi(dma_win_hi), .ovf_in({ovf_in}), .err_in(64\'d0), .timeout(timeout), .irq(irq));\n')
    w(f'  assign irq_src[15:{ns}] = 0;\n' if ns < 16 else '')
    w(f'  assign irq_snk[15:{nk}] = 0;\n' if nk < 16 else '')
    w(f'  assign irq_pe[15:{ne}] = 0;\n' if ne < 16 else '')
    w(f'  assign irq_dma[15:{nd}] = 0;\n' if nd < 16 else '')
    if cc.params:
        w('\n  // runtime parameters (word index, header name)\n')
        for p in sorted(cc.params, key=lambda p: p.index):
            sg = 'signed ' if p.cfg.signed and p.affine is not None else ''
            w(f'  wire [{p.cfg.width - 1}:0] p_{p.name} = cfg_live[{32 * p.index} +: {p.cfg.width}];'
              f'  // 0x{0x100 + 4 * p.index:04x} {cname(p.name)}: {p.desc}\n')

    # ---- nets
    w('\n  // ---------------------------------------------------------------- streams\n')
    for n in cc.nets:
        if n.src is None:
            continue
        w(f'  wire [{n.fmt.tw - 1}:0] {n.name}_tdata; wire {n.name}_tvalid, {n.name}_tready, {n.name}_tlast;  // {n.fmt}'
          + (f', {n.rate / 1e3:g} kS/s' if n.rate else '') + (f', vectors of {n.vlen}' if n.vlen > 1 else '') + '\n')
    st_wires = {}
    for i in cc.insts:
        if i.kind in ('block',) and getattr(i, 'status', None) is not None or (i.kind == 'block' and any(
                p.startswith('st_') for p in vports.info(i.module).ports)):
            for p in vports.info(i.module).ports:
                if p.startswith('st_'):
                    sw = (getattr(i, 'status', None) or {}).get(p[3:], (1, 0))[0]
                    st_wires[(i.name, p)] = sw
                    w(f'  wire [{sw - 1}:0] {i.name}_{p};\n')

    # ---- pads
    for p in pads_in:
        n, lb = p.outs[0], p.ep['label']
        w(f'\n  // pad source {lb}: data is dropped while RUN is clear\n')
        w(f'  assign {n.name}_tdata = {lb}_tdata;\n  assign {n.name}_tvalid = {lb}_tvalid && run;\n'
          f'  assign {n.name}_tlast = {lb}_tlast;\n  assign {lb}_tready = {n.name}_tready || !run;\n')
    for p in pads_out:
        n, lb = p.ins[0][0], p.ep['label']
        w(f'\n  // pad sink {lb}\n')
        w(f'  assign {lb}_tdata = {n.name}_tdata;\n  assign {lb}_tvalid = {n.name}_tvalid && run;\n'
          f'  assign {lb}_tlast = {n.name}_tlast;\n  assign {n.name}_tready = {lb}_tready || !run;\n')
    for i in cc.insts:
        if i.kind == 'null':
            n = i.ins[0][0]
            w(f'  assign {n.name}_tready = 1\'b1;  // null sink {i.name}\n')
    for n in cc.nets:
        if n.src is not None and not n.dst:
            w(f'  assign {n.name}_tready = 1\'b1;  // unconnected output\n')

    # ---- blocks
    w('\n  // ---------------------------------------------------------------- blocks\n')
    for i in cc.insts:
        if i.kind not in ('block', 'fork'):
            continue
        mi = vports.info(i.module)
        w(f'\n  // {describe(i)}\n')
        pl = ', '.join(f'.{k}({vparam(v)})' for k, v in i.params.items())
        conns = ['.clk(clk)', '.rst_n(grst_n)']
        raw = getattr(i, 'raw_in', False)
        if i.ins:
            conns.append('.s_tdata(' + cat(in_expr(n, wd, raw) for n, wd in i.ins) + ')')
            conns.append('.s_tvalid(' + cat(f'{n.name}_tvalid' for n, _ in i.ins) + ')')
            conns.append('.s_tready(' + cat(f'{n.name}_tready' for n, _ in i.ins) + ')')
            conns.append('.s_tlast(' + cat(f'{n.name}_tlast' for n, _ in i.ins) + ')')
        if i.outs:
            for sfx in ('tdata', 'tvalid', 'tready', 'tlast'):
                conns.append(f'.m_{sfx}(' + cat(f'{n.name}_{sfx}' for n in i.outs) + ')')
        if 'run' in mi.ports:
            conns.append('.run(run)')
        for c in i.cfg:
            if c.port in mi.ports:
                conns.append(f'.{c.port}({cfg_expr(cc, c)})')
        for k, v in i.extra.items():
            if k != 'run' and k in mi.ports:
                conns.append(f'.{k}({v})')
        for p in mi.ports:
            if p.startswith('st_'):
                conns.append(f'.{p}({i.name}_{p})')
        if i.ovf:
            conns.append(f'.ovf(ovf[{i.ovf_index}])')
        elif 'ovf' in mi.ports:
            conns.append('.ovf()')
        body = ',\n    '.join(conns)
        w(f'  {i.module} #({pl})\n  u_{i.name} (\n    {body});\n' if pl else f'  {i.module} u_{i.name} (\n    {body});\n')

    # ---- endpoints
    if srcs or snks:
        w('\n  // ---------------------------------------------------------------- endpoints\n')
    for k, i in enumerate(srcs):
        t = 1 + k
        n = i.outs[0]
        pl = ', '.join(f'.{a}({vparam(v)})' for a, v in i.params.items())
        w(f'  // source endpoint {k} {i.name} at 0x{i.ep["addr"]:04x}: {n.fmt}\n')
        w(f'  grv_ep_src #({pl}) u_{i.name} (.clk(clk), .rst_n(grst_n), .run(run),\n'
          f'    .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re), .rb_force(rb_force),\n'
          f'    .rb_sel(rb_sel[{t}]), .t_wrdy(t_wrdy[{t}]), .t_rrdy(t_rrdy[{t}]), .t_rdata(t_rdata[{32 * t} +: 32]), .irq(irq_src[{k}]),\n'
          f'    .m_tdata({n.name}_tdata), .m_tvalid({n.name}_tvalid), .m_tready({n.name}_tready), .m_tlast({n.name}_tlast));\n')
    for k, i in enumerate(snks):
        t = 1 + ns + k
        n = i.ins[0][0]
        pl = ', '.join(f'.{a}({vparam(v)})' for a, v in i.params.items())
        w(f'  // sink endpoint {k} {i.name} at 0x{i.ep["addr"]:04x}: {n.fmt}, {i.ep["mode"]}' +
          (f', capture window 0x{i.ep["window"]:04x}' if i.ep.get('capd') else '') + '\n')
        w(f'  grv_ep_snk #({pl}) u_{i.name} (.clk(clk), .rst_n(grst_n),\n'
          f'    .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re), .rb_force(rb_force),\n'
          f'    .rb_sel(rb_sel[{t}]), .t_wrdy(t_wrdy[{t}]), .t_rrdy(t_rrdy[{t}]), .t_rdata(t_rdata[{32 * t} +: 32]), .irq(irq_snk[{k}]),\n'
          f'    .s_tdata({n.name}_tdata), .s_tvalid({n.name}_tvalid), .s_tready({n.name}_tready), .s_tlast({n.name}_tlast));\n')
    if npb:
        t = tp - 1
        w('\n  // probes\n')
        data, valid = [], []
        for k, i in enumerate(prbs):
            if i.ep.get('status'):
                src, port = i.ep['status']
                sw = st_wires[(src.name, port)]
                s = f'{src.name}_{port}'
                data.append(f'{{{{{64 - sw}{{{s}[{sw - 1}]}}}}, {s}}}' if sw < 64 else s)
                valid.append("1'b1")
                continue
            n = i.ins[0][0]
            f = n.fmt
            if f.cplx:
                if f.w > 32:
                    raise GrvError(f'{i.name}: probe of complex components wider than 32 bits')
                parts = [f'{{{{{32 - f.w}{{{n.name}_tdata[{c * f.w + f.w - 1}]}}}}, {n.name}_tdata[{c * f.w} +: {f.w}]}}'
                         if f.w < 32 else f'{n.name}_tdata[{c * f.w} +: 32]' for c in (1, 0)]
                data.append('{' + ', '.join(parts) + '}')
            else:
                if f.w > 64:
                    raise GrvError(f'{i.name}: probe wider than 64 bits')
                fill = f'{n.name}_tdata[{f.w - 1}]' if f.signed else "1'b0"
                data.append(f'{{{{{64 - f.w}{{{fill}}}}}, {n.name}_tdata}}' if f.w < 64 else f'{n.name}_tdata')
            valid.append(f'{n.name}_tvalid')
        readies = []
        for k, i in enumerate(prbs):
            if i.ep.get('status'):
                readies.append(None)
            else:
                readies.append(f'{i.ins[0][0].name}_tready')
        w(f'  wire [{npb - 1}:0] prb_ready;\n')
        for k, r in enumerate(readies):
            if r:
                w(f'  assign {r} = prb_ready[{k}];\n')
        w(f'  grv_probes #(.NP({npb})) u_probes (.clk(clk), .rst_n(rst_n), .rb_addr(rb_addr), .rb_re(rb_re),\n'
          f'    .rb_sel(rb_sel[{t}]), .t_wrdy(t_wrdy[{t}]), .t_rrdy(t_rrdy[{t}]), .t_rdata(t_rdata[{32 * t} +: 32]),\n'
          f'    .s_tdata({cat(data)}), .s_tvalid({cat(valid)}), .s_tready(prb_ready));\n')
    if pes:
        w('\n  // ---------------------------------------------------------------- peripheral endpoints\n')
    for k, i in enumerate(pes):
        t = tp + k
        mi = vports.info(i.module)
        pl = ', '.join(f'.{a}({rparam(a, v)})' for a, v in i.params.items())
        conns = ['.clk(clk)', '.rst_n(grst_n)', '.run(run)', '.rb_addr(rb_addr)', '.rb_wdata(rb_wdata)', '.rb_we(rb_we)',
                 '.rb_re(rb_re)', f'.rb_sel(rb_sel[{t}])', f'.t_wrdy(t_wrdy[{t}])', f'.t_rrdy(t_rrdy[{t}])',
                 f'.t_rdata(t_rdata[{32 * t} +: 32])', f'.irq(irq_pe[{k}])']
        if i.outs:
            n = i.outs[0]
            conns += [f'.m_{x}({n.name}_{x})' for x in ('tdata', 'tvalid', 'tready', 'tlast')]
        else:
            n = i.ins[0][0]
            conns += [f'.s_{x}({n.name}_{x})' for x in ('tdata', 'tvalid', 'tready', 'tlast')]
        done = {c[1:c.index('(')] for c in conns}
        for pn, _, _, port in i.ep['pins']:
            conns.append(f'.{port}({i.name}_{pn})')
            done.add(port)
        for port, v in i.ep['ties'].items():
            conns.append(f'.{port}({v})')
            done.add(port)
        for port in mi.order:
            if port not in done:
                conns.append(f'.{port}()')
        w(f'  // {i.ep["addr"]:#06x} {i.name}: {pe_desc(i)}\n')
        w(f'  {i.module} #({pl})\n  u_{i.name} (\n    ' + ',\n    '.join(conns) + ');\n')
    if dmas:
        w('\n  // ---------------------------------------------------------------- DMA channels\n')
        w(f'  wire [{nd - 1}:0] dma_rq_valid, dma_rq_prio, dma_rq_gnt, dma_rq_done;\n'
          f'  wire [{32 * nd - 1}:0] dma_rq_addr, dma_rq_wdata;\n  wire [{4 * nd - 1}:0] dma_rq_wstrb, dma_rq_burst;\n'
          '  wire [31:0] dma_rq_rdata; wire dma_rq_err; wire [1:0] dma_rq_ecode;\n')
    for k, i in enumerate(dmas):
        t = tp + ne + k
        pl = ', '.join(f'.{a}({rparam(a, v)})' for a, v in i.params.items())
        f = i.ep['fmt']
        if i.outs:
            n = i.outs[0]
            st = (f".s_tdata({f.tw}'d0), .s_tvalid(1'b0), .s_tready(), .s_tlast(1'b0),\n"
                  f'    .m_tdata({n.name}_tdata), .m_tvalid({n.name}_tvalid), .m_tready({n.name}_tready), .m_tlast({n.name}_tlast)')
        else:
            n = i.ins[0][0]
            st = (f'.s_tdata({n.name}_tdata), .s_tvalid({n.name}_tvalid), .s_tready({n.name}_tready), .s_tlast({n.name}_tlast),\n'
                  "    .m_tdata(), .m_tvalid(), .m_tready(1'b1), .m_tlast()")
        w(f'  // {i.ep["addr"]:#06x} {i.name}: {dma_desc(i)}\n')
        w(f'  grv_dma_ch #({pl})\n  u_{i.name} (.clk(clk), .rst_n(grst_n), .run(run),\n'
          f'    .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re),\n'
          f'    .rb_sel(rb_sel[{t}]), .t_wrdy(t_wrdy[{t}]), .t_rrdy(t_rrdy[{t}]), .t_rdata(t_rdata[{32 * t} +: 32]), .irq(irq_dma[{k}]),\n'
          f'    {st},\n'
          f'    .rq_valid(dma_rq_valid[{k}]), .rq_addr(dma_rq_addr[{32 * k} +: 32]), .rq_wdata(dma_rq_wdata[{32 * k} +: 32]),\n'
          f'    .rq_wstrb(dma_rq_wstrb[{4 * k} +: 4]), .rq_burst(dma_rq_burst[{4 * k} +: 4]), .rq_prio(dma_rq_prio[{k}]),\n'
          f'    .rq_gnt(dma_rq_gnt[{k}]), .rq_done(dma_rq_done[{k}]), .rq_rdata(dma_rq_rdata), .rq_err(dma_rq_err),\n'
          f'    .rq_ecode(dma_rq_ecode));\n')
    if dmas:
        w(f'  grv_dma_bus #(.NCH({nd})) u_dma_bus (.clk(clk), .rst_n(rst_n),\n'
          '    .rq_valid(dma_rq_valid), .rq_addr(dma_rq_addr), .rq_wdata(dma_rq_wdata), .rq_wstrb(dma_rq_wstrb),\n'
          '    .rq_burst(dma_rq_burst), .rq_prio(dma_rq_prio), .rq_gnt(dma_rq_gnt), .rq_done(dma_rq_done),\n'
          '    .rq_rdata(dma_rq_rdata), .rq_err(dma_rq_err), .rq_ecode(dma_rq_ecode),\n'
          '    .win_lo(dma_win_lo), .win_hi(dma_win_hi), .timeout(timeout),\n'
          '    .m_mem_valid(m_mem_valid), .m_mem_addr(m_mem_addr), .m_mem_wdata(m_mem_wdata), .m_mem_wstrb(m_mem_wstrb),\n'
          '    .m_mem_ready(m_mem_ready), .m_mem_rdata(m_mem_rdata));\n')
    w('\nendmodule\n\n`default_nettype wire\n')
    path = os.path.join(d, f'{top}.v')
    open(path, 'w').write(''.join(L))
    return path


def emit_filelist(cc, d):
    mods = {i.module for i in cc.insts if i.kind in ('block', 'fork')}
    mods |= {'grv_axil_dec', 'grv_regs'}
    if cc.srcs:
        mods.add('grv_ep_src')
    if cc.snks:
        mods.add('grv_ep_snk')
    if cc.prbs:
        mods.add('grv_probes')
    mods |= {i.module for i in cc.pes + cc.dmas}
    if cc.dmas:
        mods.add('grv_dma_bus')
    files = vports.closure(mods)
    root = vports.ROOT
    lines = [f'+incdir+{os.path.join(root, "rtl/inc")}', f'+incdir+{os.path.join(root, "rtl/prim")}']
    lines += files + [os.path.abspath(os.path.join(d, f'{cc.top}.v'))]
    path = os.path.join(d, f'{cc.top}.f')
    open(path, 'w').write('\n'.join(lines) + '\n')
    cc.files = files
    return path


def emit_gprj(cc, d):
    lines = [f'<File path="{f}" type="file.verilog" enable="1"/>' for f in cc.files + [os.path.abspath(os.path.join(d, f'{cc.top}.v'))]]
    path = os.path.join(d, f'{cc.top}.gprj')
    open(path, 'w').write('\n'.join(lines) + '\n')
    return path


# ------------------------------------------------------------------ map (JSON)
def ep_json(i):
    e = dict(name=i.name, kind=i.kind, addr=i.ep.get('addr'), index=i.ep.get('index'))
    if i.kind == 'src':
        e.update(fmt=i.outs[0].fmt.to_json(), depth=i.ep['depth'], loop=i.ep.get('loop', False), irq_bit=16 + i.ep['index'],
                 vlen=i.outs[0].vlen, rate=i.outs[0].rate)
    elif i.kind == 'snk':
        n = i.ins[0][0]
        e.update(fmt=n.fmt.to_json(), depth=i.ep['depth'], mode=i.ep['mode'], capd=i.ep.get('capd', 0),
                 caplen=i.ep.get('caplen', 0), window=i.ep.get('window'), irq_bit=i.ep['index'], vlen=n.vlen, rate=n.rate)
    elif i.kind == 'pe':
        n = i.outs[0] if i.outs else i.ins[0][0]
        e.update(dir=i.ep['dir'], periph=i.ep['pkind'], module=i.module, fmt=n.fmt.to_json(), depth=i.ep['depth'],
                 irq2_bit=i.ep['index'], rate=n.rate, pace=i.ep.get('pace'),
                 pins=[dict(name=f'{i.name}_{pn}', dir=d_, width=wd) for pn, d_, wd, _ in i.ep['pins']],
                 regs={k: i.params[k] for k in ('CTRL0', 'TIMING0', 'FORMAT0', 'THRESH0', 'SCLK0', 'CMD0', 'CMDQ0', 'CST0', 'MCLK0')
                       if k in i.params})
    elif i.kind == 'dma':
        n = i.outs[0] if i.outs else i.ins[0][0]
        e.update(dir='mm2s' if i.ep['dir'] == 'in' else 's2mm', fmt=n.fmt.to_json(), container=i.ep['cb'],
                 element=i.ep['eb'], mode=['single', 'ring', 'desc'][i.ep['mode']], irq2_bit=16 + i.ep['index'],
                 rate=n.rate, vlen=n.vlen, regs={k: i.params[k] for k in ('CTRL0', 'ADDR0', 'LEN0', 'WM0', 'FRAME0')})
    elif i.kind == 'probe':
        if i.ep.get('status'):
            src, port = i.ep['status']
            e.update(fmt=i.ep['fmt'].to_json(), status=f'{src.name}.{port}')
        else:
            e.update(fmt=i.ins[0][0].fmt.to_json())
    return e


def param_json(cc, p):
    rv = cc.rvars.get(p.var, {})
    return dict(name=p.name, index=p.index, addr=0x100 + 4 * p.index, words=p.words, width=p.cfg.width, signed=p.cfg.signed,
                var=p.var, kind=rv.get('kind'), inst=p.inst.name if p.inst else None, port=p.cfg.port if p.inst else None,
                init=p.init, affine=list(p.affine) if p.affine else None, desc=p.desc,
                options=[repr(o) for o in rv.get('options', [])] if rv.get('kind') == 'chooser' else None,
                lo=rv.get('lo'), hi=rv.get('hi'), default=repr(rv.get('default')))


def emit_map(cc, d):
    m = dict(top=cc.top, grvgen=VERSION, source=os.path.basename(cc.path), hash=f'0x{cc.hash:08x}', base=f'0x{cc.base:08x}',
             clk=cc.clk, profile=cc.prof,
             sources=[ep_json(i) for i in cc.srcs], sinks=[ep_json(i) for i in cc.snks], probes=[ep_json(i) for i in cc.prbs],
             periph=[ep_json(i) for i in cc.pes], dma=[ep_json(i) for i in cc.dmas],
             dma_window=[f'0x{x:08x}' for x in getattr(cc, 'dma_window', (0, 0xFFFFFFFF))],
             params=[param_json(cc, p) for p in sorted(cc.params, key=lambda p: p.index)],
             pads=[dict(label=i.ep['label'], dir='in' if i.kind == 'pad_in' else 'out',
                        fmt=(i.outs[0] if i.kind == 'pad_in' else i.ins[0][0]).fmt.to_json(),
                        rate=(i.outs[0] if i.kind == 'pad_in' else i.ins[0][0]).rate)
                   for i in cc.insts if i.kind in ('pad_in', 'pad_out')],
             ovf=[dict(bit=i.ovf_index, inst=i.name) for i in cc.ovf_list],
             blocks=[dict(name=i.name, module=i.module, grc=i.blk.name if i.blk else None, grc_id=i.grc_id,
                          ins=[repr(n.fmt) for n, _ in i.ins], outs=[repr(n.fmt) for n in i.outs],
                          rate_out=[n.rate for n in i.outs], ii=i.meta.get('ii', 1), cost=i.cost)
                     for i in cc.insts])
    path = os.path.join(d, f'{cc.top}_map.json')
    json.dump(m, open(path, 'w'), indent=1)
    return path


# ------------------------------------------------------------------ C header
def emit_header(cc, d):
    P = cname(cc.top[:-4] if cc.top.endswith('_top') else cc.top)
    g = f'{P}_REGS_H'
    L = [f'/* {cc.top}_regs.h - generated by grvgen {VERSION} from {os.path.basename(cc.path)}; do not edit. */',
         f'#ifndef {g}', f'#define {g}', '#include <stdint.h>', '#include "grv.h"', '',
         f'#define {P}_BASE            0x{cc.base:08x}u',
         f'#define {P}_HASH            0x{cc.hash:08x}u          /* GRV_GRAPH_HASH */',
         f'#define {P}_CLK_HZ          {int(cc.clk)}u',
         f'#define {P}_N_SRC           {len(cc.srcs)}u', f'#define {P}_N_SNK           {len(cc.snks)}u',
         f'#define {P}_N_PROBE         {len(cc.prbs)}u', f'#define {P}_N_PARAM_WORDS   {cc.npw}u',
         f'#define {P}_N_PE            {len(cc.pes)}u', f'#define {P}_N_DMA           {len(cc.dmas)}u', '']
    if cc.srcs:
        L.append('/* source endpoints */')
    for i in cc.srcs:
        n = cname(i.name)
        f = i.outs[0].fmt
        L += [f'#define {P}_SRC_{n:<16} 0x{i.ep["addr"]:04x}u   /* {f}, FIFO {i.ep["depth"]} */',
              f'#define {P}_IRQ_SRC_{n:<12} (1u << {16 + i.ep["index"]})',
              f'#define {P}_SRC_{n}_FRAC    {f.f}']
    if cc.snks:
        L.append('/* sink endpoints */')
    for i in cc.snks:
        n = cname(i.name)
        f = i.ins[0][0].fmt
        L += [f'#define {P}_SNK_{n:<16} 0x{i.ep["addr"]:04x}u   /* {f}, {i.ep["mode"]}, FIFO {i.ep["depth"]} */',
              f'#define {P}_IRQ_SNK_{n:<12} (1u << {i.ep["index"]})',
              f'#define {P}_SNK_{n}_FRAC    {f.f}']
        if i.ep.get('capd'):
            L += [f'#define {P}_CAP_{n:<16} 0x{i.ep["window"]:04x}u   /* capture buffer, {i.ep["capd"]} samples */',
                  f'#define {P}_CAP_{n}_LEN     {i.ep["capd"]}u']
    if cc.prbs:
        L.append('/* probes */')
    for i in cc.prbs:
        f = i.ep['fmt'] if i.ep.get('status') else i.ins[0][0].fmt
        L.append(f'#define {P}_PROBE_{cname(i.name):<14} 0x{i.ep["addr"]:04x}u   /* {f} */')
    if cc.pes:
        L += ['', '/* peripheral endpoints: offsets, IRQ2_STATUS bits and the reset values grvgen computed */']
    for i in cc.pes:
        n = cname(i.name)
        L += [f'#define {P}_PE_{n:<17} 0x{i.ep["addr"]:04x}u   /* {pe_desc(i)} */',
              f'#define {P}_IRQ_PE_{n:<13} (1u << {i.ep["index"]})',
              f'#define {P}_PE_{n}_FRAC     {i.ep["fmt"].f}']
        for k in ('CTRL0', 'TIMING0', 'FORMAT0', 'SCLK0', 'CMD0', 'CMDQ0', 'CST0', 'MCLK0'):
            if k in i.params:
                L.append(f'#define {P}_PE_{n}_{k[:-1]:<8} 0x{int(i.params[k]) & 0xFFFFFFFF:08x}u')
        L.append(f'/*   pins: {", ".join(f"{i.name}_{pn} ({d_})" for pn, d_, _, _ in i.ep["pins"])} */')
    if cc.dmas:
        wlo, whi = getattr(cc, 'dma_window', (0, 0xFFFFFFFF))
        L += ['', '/* DMA channels: offsets, IRQ2_STATUS bits, memory layout of the samples */',
              f'#define {P}_DMA_WIN_LO        0x{wlo:08x}u', f'#define {P}_DMA_WIN_HI        0x{whi:08x}u']
    for i in cc.dmas:
        n = cname(i.name)
        L += [f'#define {P}_DMA_{n:<16} 0x{i.ep["addr"]:04x}u   /* {dma_desc(i)} */',
              f'#define {P}_IRQ_DMA_{n:<12} (1u << {16 + i.ep["index"]})',
              f'#define {P}_DMA_{n}_CB      {i.ep["cb"]}u     /* bytes per component */',
              f'#define {P}_DMA_{n}_EB      {i.ep["eb"]}u     /* bytes per sample */',
              f'#define {P}_DMA_{n}_FRAC    {i.ep["fmt"].f}',
              f'#define {P}_DMA_{n}_CTRL    0x{int(i.params["CTRL0"]) & 0xFFFFFFFF:08x}u']
    if cc.params:
        L += ['', '/* runtime parameters: write the hardware value, then GRV_CTRL_COMMIT (live words take effect at once) */']
    for p in sorted(cc.params, key=lambda p: p.index):
        n = cname(p.name)
        where = f'{p.inst.name}.{p.cfg.port}' if p.inst else 'chooser index'
        L.append(f'#define {P}_P_{n:<18} 0x{0x100 + 4 * p.index:04x}u   /* {where}, {p.cfg.width} bits, {p.desc}; variable {p.var} */')
        L.append(f'#define {P}_P_{n}_INIT     {p.init}')
        rv = cc.rvars.get(p.var, {})
        if p.affine:
            a, b = p.affine
            L.append(f'#define {P}_P_{n}_A        ({a!r})   /* hw = A * {p.var} + B */')
            L.append(f'#define {P}_P_{n}_B        ({b!r})')
        if rv.get('kind') == 'chooser':
            for k, o in enumerate(rv['options']):
                L.append(f'#define {P}_{cname(p.var)}_OPT{k:<10} {k}u   /* {p.var} = {o!r} */')
    # setter functions per runtime variable
    byvar = {}
    for p in cc.params:
        byvar.setdefault(p.var, []).append(p)
    if byvar:
        L += ['', '#ifndef GRV_NO_FLOAT', '/* set a runtime variable in GRC units (needs floating point; define GRV_NO_FLOAT to omit) */']
        for var, ps in sorted(byvar.items()):
            rv = cc.rvars[var]
            if rv['kind'] == 'chooser':
                p = ps[0]
                L += [f'static inline void {cc.top}_set_{var}(uintptr_t base, uint32_t index)',
                      f'{{ GRV_REG(base, {P}_P_{cname(p.name)}) = index; }}']
                continue
            L.append(f'static inline void {cc.top}_set_{var}(uintptr_t base, double v)\n{{')
            for p in ps:
                n = cname(p.name)
                a, b = p.affine
                L.append(f'    {{ double h = {P}_P_{n}_A * v + {P}_P_{n}_B; int64_t q = (int64_t)(h < 0 ? h - 0.5 : h + 0.5);')
                for k in range(p.words):
                    L.append(f'      GRV_REG(base, {P}_P_{n} + {4 * k}u) = (uint32_t)((uint64_t)q >> {32 * k}); }}' if k == p.words - 1
                             else f'      GRV_REG(base, {P}_P_{n} + {4 * k}u) = (uint32_t)((uint64_t)q >> {32 * k});')
            L.append('}')
        L.append('#endif')
        L += ['', '/* integer-only conversion for integer values of a variable (e.g. Hz): hw = (v * A_Q16 >> 16) + B */']
        for var, ps in sorted(byvar.items()):
            for p in ps:
                if p.affine is None or p.words > 1:
                    continue
                a, b = p.affine
                n = cname(p.name)
                L += [f'#define {P}_P_{n}_A_Q16    ({int(round(a * 65536))}LL)',
                      f'static inline uint32_t {cc.top}_{p.name}_hw(int32_t v)',
                      f'{{ return (uint32_t)((((int64_t)v * {P}_P_{n}_A_Q16) >> 16) + {int(round(b))}); }}']
    if cc.ovf_list:
        L += ['', '/* bits of GRV_OVF_MAP (saturation or wrap in the block) */']
        for i in cc.ovf_list:
            L.append(f'#define {P}_OVF_{cname(i.name):<16} {i.ovf_index}u')
    pads = [i for i in cc.insts if i.kind in ('pad_in', 'pad_out')]
    if pads:
        L += ['', '/* pads (top-level AXI4-Stream ports) */']
        for i in pads:
            f = (i.outs[0] if i.kind == 'pad_in' else i.ins[0][0]).fmt
            L.append(f'/*   {i.ep["label"]}_tdata: {"input" if i.kind == "pad_in" else "output"} {f} */')
    L += ['', f'#endif /* {g} */', '']
    path = os.path.join(d, f'{cc.top}_regs.h')
    open(path, 'w').write('\n'.join(L))
    return path


# ------------------------------------------------------------------ graph model
def cfg_model_value(c, value):
    u = to_u(int(value), c.width)
    return u


def emit_model(cc, d):
    nets = {}
    for n in cc.nets:
        nets[n.name] = dict(w=n.fmt.w, f=n.fmt.f, cplx=n.fmt.cplx, signed=n.fmt.signed, vlen=n.vlen, rate=n.rate)
    insts = []
    for i in cc.insts:
        e = dict(name=i.name, module=i.module, kind=i.kind, raw=bool(getattr(i, 'raw_in', False)),
                 ins=[n.name for n, _ in i.ins], outs=[n.name for n in i.outs],
                 params={k: (list(v) if isinstance(v, tuple) else v) for k, v in i.params.items()}, cfg={})
        for c in i.cfg:
            spec = dict(width=c.width, signed=c.signed, split=(c.width // 2) if getattr(c, 'model', None) else 0)
            if c.const is not None:
                spec['const'] = to_u(c.const, c.width)
            elif c.param is not None:
                spec['param'] = c.param.name
            else:
                spec['mux'] = c.mux[0].name
                spec['vals'] = [to_u(v, c.width) for v in c.mux[1]]
            e['cfg'][c.port[4:] if c.port.startswith('cfg_') else c.port] = spec
        for k, v in i.extra.items():
            if k.startswith('cfg_') and "'d" in v:
                w_, val = v.split("'d")
                e['cfg'][k[4:]] = dict(width=int(w_), signed=False, split=0, const=int(val))
        for k, v in (getattr(i, 'model_cfg', None) or {}).items():
            e['cfg'][k] = dict(width=64, signed=True, split=0, const=v)
        if i.ep:
            e['ep'] = {k: (v.to_json() if hasattr(v, 'to_json') else v) for k, v in i.ep.items() if k != 'status'}
        e['anchor'] = i.meta.get('anchor')
        insts.append(e)
    params = {p.name: dict(init=p.init, width=p.cfg.width, signed=p.cfg.signed, var=p.var,
                           affine=list(p.affine) if p.affine else None) for p in cc.params}
    g = dict(top=cc.top, nets=nets, insts=insts, params=params,
             rvars={k: dict(kind=v['kind'], options=[repr(o) for o in v.get('options', [])]) for k, v in cc.rvars.items()})
    gdir = os.path.abspath(os.path.join(vports.ROOT, 'grvgen'))
    src = f'''"""{cc.top}_model.py - bit-exact model of {os.path.basename(cc.path)}, generated by grvgen {VERSION}.

    out = run(inputs={{name: [samples]}}, n=4096, params={{variable: value}}, raw_params={{param: hw value}})

Inputs are keyed by source endpoint name or pad label, samples are hardware integers (complex as (i, q)).
Free-running sources produce n samples (scaled by their rate relative to the fastest anchored source).
The result maps sink endpoint names, pad labels and probe names to lists of samples (and '<name>.last').
"""
import os, sys, json
sys.path.insert(0, os.environ.get('GRVGEN_DIR', {gdir!r}))
from grv.graphmodel import run_graph, to_float

GRAPH = json.loads({json.dumps(json.dumps(g))})


def run(inputs=None, n=4096, params=None, raw_params=None):
    return run_graph(GRAPH, inputs or {{}}, n, params or {{}}, raw_params or {{}})


if __name__ == '__main__':
    out = run(n=int(sys.argv[1]) if len(sys.argv) > 1 else 64)
    for k, v in out.items():
        if not k.endswith('.last'):
            print(k, len(v), v[:8])
'''
    path = os.path.join(d, f'{cc.top}_model.py')
    open(path, 'w').write(src)
    return path


# ------------------------------------------------------------------ report
def emit_report(cc, d):
    L = [f'# {cc.top}', '', f'Generated by grvgen {VERSION} from `{os.path.basename(cc.path)}` on '
         f'{datetime.date.today().isoformat()}; graph hash `0x{cc.hash:08x}`, clock {cc.clk / 1e6:g} MHz, '
         f'profile {cc.prof}.', '']
    L += ['## Blocks', '', '| Instance | Module | GRC block | In | Out | Rate out | II | Mult | BRAM | LUT (est.) |',
          '|---|---|---|---|---|---|---|---|---|---|']
    tot = dict(lut=0, mult=0, bram=0)
    for i in cc.insts:
        rate = ', '.join(f'{n.rate / 1e3:g} k' for n in i.outs if n.rate) or '-'
        L.append(f'| {i.name} | {i.module} | {i.blk.name + " (" + i.blk.id + ")" if i.blk else "-"} | '
                 f'{", ".join(repr(n.fmt) for n, _ in i.ins) or "-"} | {", ".join(repr(n.fmt) for n in i.outs) or "-"} | '
                 f'{rate} | {i.meta.get("ii", 1)} | {i.cost.get("mult", 0)} | {i.cost.get("bram", 0)} | {i.cost.get("lut", 0)} |')
        for k in tot:
            tot[k] += i.cost.get(k, 0)
    ctl = 1100 + 400 * len(cc.srcs) + 40 * len(cc.prbs) + 20 * cc.npw + (250 if cc.dmas else 0)
    L += ['', f'Estimated totals: about {tot["lut"] + ctl} LUT ({ctl} in the control plane), {tot["mult"]} multipliers '
          f'(18x18), {tot["bram"]} block RAMs. Estimates only: run synthesis for the real numbers.', '']
    firs = [i for i in cc.insts if getattr(i, 'taps', None)]
    if firs:
        L += ['## Filters', '', '| Instance | Taps | Coefficient format | Symmetric | Tap SQNR | L1 gain | LANES |', '|---|---|---|---|---|---|---|']
        for i in firs:
            t = i.taps
            L.append(f'| {i.name} | {t["n"]} | s{i.params["CW"]}.{t["cf"]}{" complex" if t["cplx"] else ""} | '
                     f'{"yes" if t["sym"] else "no"} | {t["sqnr"]:.1f} dB | {t["l1"]:.3f} | {i.params.get("LANES", 0) or "parallel"} |')
        L.append('')
    L += ['## Streams', '', '| Net | From | To | Format | Range | Rate |', '|---|---|---|---|---|---|']
    for n in cc.nets:
        if n.src is None:
            continue
        L.append(f'| {n.name} | {n.src[0].name} | {", ".join(x.name for x, _ in n.dst) or "-"} | {n.fmt} | '
                 f'{n.rng:.4g} | {f"{n.rate:.6g}" if n.rate else "unknown"} |')
    L += ['', '## Address map', '', f'Base `0x{cc.base:08x}`.', '', '| Offset | Name | Kind | Details |', '|---|---|---|---|']
    for i in cc.srcs + cc.snks + cc.prbs:
        f = i.ep.get('fmt')
        L.append(f'| 0x{i.ep["addr"]:04x} | {i.name} | {i.kind} | {f}' +
                 (f', capture window 0x{i.ep["window"]:04x}' if i.ep.get('window') else '') + ' |')
    for i in cc.pes:
        L.append(f'| 0x{i.ep["addr"]:04x} | {i.name} | peripheral endpoint | {pe_desc(i)}; TIMING 0x{i.params["TIMING0"]:x}, '
                 f'FORMAT 0x{i.params["FORMAT0"]:x} |')
    for i in cc.dmas:
        L.append(f'| 0x{i.ep["addr"]:04x} | {i.name} | DMA channel | {dma_desc(i)} |')
    for p in sorted(cc.params, key=lambda p: p.index):
        L.append(f'| 0x{0x100 + 4 * p.index:04x} | {p.name} | parameter | {p.desc}; variable `{p.var}`, init {p.init} |')
    if cc.pes or cc.dmas:
        L += ['', '## Pins', '', '| Port | Direction | Width | Endpoint |', '|---|---|---|---|']
        for i in cc.pes:
            for pn, d_, wd, _ in i.ep['pins']:
                L.append(f'| {i.name}_{pn} | {d_} | {wd} | {i.name} |')
        if cc.dmas:
            L.append(f'| m_mem_* | | | DMA memory port ({len(cc.dmas)} channels) |')
    L += ['', '## Diagnostics', '']
    if not cc.diag.items:
        L.append('None.')
    for kind, code, msg in cc.diag.items:
        L.append(f'- {kind} {code}: {msg}')
    path = os.path.join(d, f'{cc.top}_report.md')
    open(path, 'w').write('\n'.join(L) + '\n')
    return path


# ------------------------------------------------------------------ pin constraints (Gowin .cst template)
def emit_pins(cc, d):
    L = [f'// {cc.top}_pins.cst - pin constraint template generated by grvgen {VERSION}; fill in the IO_LOC values.',
         '// Pull-ups on UART and SPI inputs (idle high lines); set IO_TYPE to the bank voltage of the board.', '']
    for i in cc.pes:
        L.append(f'// {i.name}: {pe_desc(i)}')
        for pn, d_, wd, _ in i.ep['pins']:
            pull = 'UP' if (d_ == 'in' and i.ep['pkind'] in ('uart', 'spi_master', 'spi_slave')) else 'NONE'
            for b in range(wd):
                nm = f'{i.name}_{pn}' + (f'[{b}]' if wd > 1 else '')
                L.append(f'IO_LOC "{nm}" ?;')
                L.append(f'IO_PORT "{nm}" IO_TYPE=LVCMOS33 PULL_MODE={pull}' + (' DRIVE=8' if d_ == 'out' else '') + ';')
        L.append('')
    if not cc.pes:
        L.append('// no peripheral endpoints in this graph')
    path = os.path.join(d, f'{cc.top}_pins.cst')
    open(path, 'w').write('\n'.join(L) + '\n')
    return path
