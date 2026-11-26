"""Testbench glue of the peripheral endpoints and DMA channels (revision 0.2): the code sections that
<top>_tb.cpp needs to drive and check the pins and the memory port with the models of tb/grv_bfm.h."""
from .expr import GrvError

MEM_BASE = 0x00100000          # buffers of the DMA channels in the memory model: MEM_BASE * (k + 1)


def sections(cc):
    S = dict(decl=[], init=[], tick=[], load=[], config=[], busy=[], final=[], ins=[], outs=[])
    for i in cc.pes:
        n, e = i.name, i.ep
        f = e['fmt']
        if f.tw > 64:
            raise GrvError(f'E601: testbench: {n} carries samples wider than 64 bits')
        pk, d = e['pkind'], e['dir']
        tw = f.tw
        if d == 'in':
            S['ins'].append((n, f, bool(e.get('distinct'))))
            S['decl'].append(f'static Vec in_{n};')
            S['load'].append(f'  load(dir + "/in_{n}.hex", in_{n}, {tw});')
        else:
            S['outs'].append((n, f))
            S['decl'].append(f'static Vec exp_{n};')
            S['load'].append(f'  if (!load(dir + "/exp_{n}.hex", exp_{n}, {tw})) {{ printf("missing exp_{n}.hex\\n"); return 2; }}')
        if pk == 'uart':
            fw = e['fmtw']
            bit = i.params['TIMING0'] / 256.0
            args = f'{bit!r}, {fw & 3}, {str(bool(fw & 4)).lower()}, {str(bool(fw & 32)).lower()}'
            flow = bool(fw & 16)
            if d == 'in':
                S['decl'].append(f'static UartDrv pe_{n}({args}, {str(flow).lower()}, {str(bool(fw & 8)).lower()}, {e["nb"]});')
                S['load'].append(f'  for (auto v : in_{n}.d) pe_{n}.push(v);')
                S['init'].append(f'  t->{n}_rxd = {0 if fw & 32 else 1};')
                S['tick'].append(f'  t->{n}_rxd = pe_{n}.step(cyc, pads_on, {f"t->{n}_rts_n" if flow else "0"});')
            else:
                S['decl'].append(f'static UartMon pe_{n}({args}, {str(bool(fw & 8)).lower()}, {str(bool(fw & 64)).lower()}, '
                                 f'{str(flow).lower()}, {e["nb"]});')
                S['tick'].append(f'  {f"t->{n}_cts_n = " if flow else ""}pe_{n}.step(cyc, pads_on, t->{n}_txd);')
                S['final'].append(f'  errors += pe_{n}.ferr; if (pe_{n}.ferr) printf("{n}: %zu framing errors\\n", pe_{n}.ferr);')
        elif pk in ('spi_master', 'spi_slave'):
            fmt = i.params['FORMAT0']
            sf = (f'SpiFmt{{{e["fb"]}, {(fmt >> 17) & 1}, {(fmt >> 16) & 1}, {int(e["lsbf"])}, {e["dpos"]}, {e["db"]}, '
                  f'{int(e["ofs"])}, {f.nc}}}')
            if pk == 'spi_master':
                S['decl'].append(f'static SpiDev pe_{n}({sf});')
                if d == 'in':
                    S['load'].append(f'  for (auto v : in_{n}.d) pe_{n}.push(v);')
                    S['tick'].append(f'  t->{n}_miso = pe_{n}.step(t->{n}_sclk, t->{n}_cs_n, t->{n}_mosi);')
                else:
                    S['tick'].append(f'  pe_{n}.step(t->{n}_sclk, t->{n}_cs_n, t->{n}_mosi);')
                    S['final'].append(f'  errors += pe_{n}.bad_frames; if (pe_{n}.bad_frames) printf("{n}: %zu short frames\\n", pe_{n}.bad_frames);')
            else:
                half = 6                                          # sclk = clk / 12 (slave limit: clk / 8)
                S['decl'].append(f'static SpiHost pe_{n}({sf}, {half}, {8 * half}, {str(d == "out").lower()});')
                S['init'].append(f'  t->{n}_cs_n = 1; t->{n}_sclk = {(fmt >> 17) & 1};')
                if d == 'in':
                    S['load'].append(f'  for (auto v : in_{n}.d) pe_{n}.push(v);')
                    S['tick'].append(f'  pe_{n}.step(cyc, pads_on, 0, 0); t->{n}_sclk = pe_{n}.sclk; t->{n}_cs_n = pe_{n}.cs_n; '
                                     f't->{n}_mosi = pe_{n}.mosi;')
                else:
                    S['tick'].append(f'  pe_{n}.step(cyc, pads_on, t->{n}_miso, t->{n}_drdy); t->{n}_sclk = pe_{n}.sclk; '
                                     f't->{n}_cs_n = pe_{n}.cs_n;')
        elif pk == 'i2s':
            fmt = i.params['FORMAT0']
            sl = e['slave']
            args = (f'{e["slot"]}, {e["db"]}, {e["just"]}, {f.nc}, {int(e["mono_r"])}, {int(e.get("dup", False))}, '
                    f'{int(e["wsinv"])}, {str(sl).lower()}, 6')
            S['decl'].append(f'static I2sBfm pe_{n}({args});')
            if d == 'in':
                S['load'].append(f'  for (auto v : in_{n}.d) pe_{n}.push(v);')
            sdi = f't->{n}_sd' if d == 'out' else '0'
            if sl:
                # the codec starts with a right slot (ws at the right level from reset: no edge before it)
                S['init'].append(f'  t->{n}_bclk = 0; t->{n}_ws = {1 if (e["just"] == 0) ^ e["wsinv"] else 0};')
                S['tick'].append(f'  pe_{n}.step(cyc, pads_on, 0, 0, {sdi}); t->{n}_bclk = pe_{n}.bclk; t->{n}_ws = pe_{n}.ws;'
                                 + (f' t->{n}_sd = pe_{n}.sd;' if d == 'in' else ''))
            else:
                S['tick'].append(f'  pe_{n}.step(cyc, pads_on, t->{n}_bclk, t->{n}_ws, {sdi});'
                                 + (f' t->{n}_sd = pe_{n}.sd;' if d == 'in' else ''))
        else:  # gpio
            fmt = i.params['FORMAT0']
            per = i.params['TIMING0'] / 256.0
            ofs = sum(1 << (c * e['db'] + e['db'] - 1) for c in range(f.nc)) if e['ofs'] else 0
            if d == 'in':
                S['decl'].append(f'static GpioDrv pe_{n}({e["gmode"]}, {per!r}, {e["phase"]}, {e["filt"]}, {int(e["edge"])}, 0x{ofs:x}ull);')
                S['load'].append(f'  pe_{n}.v = in_{n}.d;')
                S['tick'].append(f'  t->{n}_in = pe_{n}.step(cyc, pads_on, run_cyc);' +
                                 (f' t->{n}_stb = pe_{n}.stb;' if e['gmode'] == 1 else ''))
                S['init'].append(f'  t->{n}_in = in_{n}.d.empty() ? 0 : in_{n}.d[0] ^ 0x{ofs:x}ull;' +
                                 (f' t->{n}_stb = {int(e["edge"])};' if e['gmode'] == 1 else ''))
            else:
                pofs = ofs if e['gmode'] == 0 else 0
                S['decl'].append(f'static GpioMon pe_{n}({e["gmode"]}, {per!r}, {e["db"]}, {f.nc}, 0x{pofs:x}ull);')
                S['tick'].append(f'  pe_{n}.step(cyc, pads_on, run_cyc, (uint64_t)t->{n}_out);')
        if d == 'out':
            if pk == 'gpio' and e['gmode'] == 2:
                S['busy'].append(f'    if (pe_{n}.windows() < exp_{n}.d.size() + 64) busy = true;')
                S['final'].append(f'  {{ double r; size_t b = pe_{n}.check_sdm("{n}", exp_{n}.d, r);\n'
                                  f'    printf("%-20s sdm   %zu sample periods, block rms error %.4f FS%s\\n", "{n}", pe_{n}.windows(), r, b ? " (FAIL)" : "");\n'
                                  f'    errors += b; }}')
            else:
                S['busy'].append(f'    if (bfm_need(pe_{n}.got, exp_{n}.d, {tw})) busy = true;')
                S['final'].append(f'  {{ size_t dn; size_t b = bfm_check("{n}", pe_{n}.got, exp_{n}.d, {tw}, dn);\n'
                                  f'    printf("%-20s pins  %zu / %zu samples, %zu mismatches%s\\n", "{n}", dn, '
                                  f'pe_{n}.got.dedupe ? bfm_runs(exp_{n}.d).size() : exp_{n}.d.size(), b, pe_{n}.got.dedupe ? " (runs)" : "");\n'
                                  f'    errors += b + (dn < (pe_{n}.got.dedupe ? bfm_runs(exp_{n}.d).size() : exp_{n}.d.size())); }}')
    if cc.dmas:
        S['decl'].append('static MemBfm mem;')
        S['init'].append('  t->m_mem_ready = 0; t->m_mem_rdata = 0;')
        S['tick'].append('  t->m_mem_ready = mem.step(t->m_mem_valid, t->m_mem_addr, t->m_mem_wdata, t->m_mem_wstrb); '
                         't->m_mem_rdata = mem.rdata;')
    for k, i in enumerate(cc.dmas):
        n, e = i.name, i.ep
        f = e['fmt']
        if f.tw > 64:
            raise GrvError(f'E601: testbench: {n} carries samples wider than 64 bits')
        base = MEM_BASE * (k + 1)
        a = i.ep['addr']
        ctrl = (i.params['CTRL0'] & ~0x0D) | 0x01         # SINGLE, EN
        msba = bool(i.params['CTRL0'] & (1 << 9))
        args = f'{f.w}, {f.nc}, {e["cb"]}, {str(f.signed).lower()}, {str(msba).lower()}'
        if e['dir'] == 'in':
            S['ins'].append((n, f, False))
            S['decl'].append(f'static Vec in_{n};')
            S['load'].append(f'  load(dir + "/in_{n}.hex", in_{n}, {f.tw});')
            S['load'].append(f'  for (size_t k = 0; k < in_{n}.d.size(); k++) mem.put(0x{base:x}u, k, in_{n}.d[k], {args});')
            S['config'].append(f'  if (!in_{n}.d.empty()) {{ wr(0x{a:04x} + 0x08, 0x{base:x}u); wr(0x{a:04x} + 0x0C, (uint32_t)in_{n}.d.size()); '
                               f'wr(0x{a:04x}, 0x{ctrl:x}u); }}   // {n}: MM2S, SINGLE')
        else:
            S['outs'].append((n, f))
            S['decl'].append(f'static Vec exp_{n}; static bool done_{n} = false;')
            S['load'].append(f'  if (!load(dir + "/exp_{n}.hex", exp_{n}, {f.tw})) {{ printf("missing exp_{n}.hex\\n"); return 2; }}')
            S['config'].append(f'  if (!exp_{n}.d.empty()) {{ wr(0x{a:04x} + 0x08, 0x{base:x}u); wr(0x{a:04x} + 0x0C, (uint32_t)exp_{n}.d.size()); '
                               f'wr(0x{a:04x}, 0x{ctrl:x}u); }} else done_{n} = true;   // {n}: S2MM, SINGLE')
            S['busy'].append(f'    if (!done_{n}) {{\n      uint32_t st = rd(0x{a:04x} + 0x04);\n'
                             f'      if (st & 8) {{ printf("ERROR: {n}: DMA error, ERR_ADDR %08x\\n", rd(0x{a:04x} + 0x28)); errors++; done_{n} = true; }}\n'
                             f'      else if (st & 2) done_{n} = true; else busy = true;\n    }}')
            S['final'].append(f'  {{ size_t bad = 0;\n'
                              f'    for (size_t k = 0; k < exp_{n}.d.size(); k++) {{ uint64_t g;\n'
                              f'      if (!mem.get_check(0x{base:x}u, k, exp_{n}.d[k], {args}, g) && bad++ < 10)\n'
                              f'        printf("MISMATCH {n}[%zu]: memory %llx expected %llx\\n", k, (unsigned long long)g, '
                              f'(unsigned long long)(exp_{n}.d[k] & bfm_mask({f.tw})));\n    }}\n'
                              f'    printf("%-20s dma   %zu / %zu samples, %zu mismatches (memory)%s\\n", "{n}", done_{n} ? exp_{n}.d.size() : 0, exp_{n}.d.size(), bad, done_{n} ? "" : " (not done)");\n'
                              f'    errors += bad + !done_{n}; }}')
    if cc.dmas:
        S['final'].append('  printf("memory model: %llu reads, %llu writes\\n", (unsigned long long)mem.reads, (unsigned long long)mem.writes);')
    return S
