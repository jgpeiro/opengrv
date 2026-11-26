"""Unit-test harness: runs one OpenGRV module in Icarus Verilog with random tvalid / tready timing
and returns the samples on its output ports, for comparison with the bit-exact Python model."""
import os, subprocess, tempfile, random, shutil

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
RTL_DIRS = ['rtl/prim', 'rtl/blocks', 'rtl/axil', 'rtl/sim']
INC_DIRS = ['rtl/inc', 'rtl/prim']


def vparam(v):
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, tuple):          # (width, unsigned value) for wide packed parameters
        w, u = v
        return f"{w}'h{u:x}"
    return str(int(v))


def run(module, params, ins=(), lasts=None, nout=(), iwt=0, owt=0, cfg=None, run_src=False,
        vp=70, rp=70, seed=1, timeout=200000, extra_ports='', keep=False, ni=None, no=None):
    """ins: list (per input port) of packed tdata ints; nout: samples expected per output port.
    iwt / owt: tdata width of one port. cfg: {port: (width, value)}. Returns (outs, lasts_out)."""
    ni = len(ins) if ni is None else ni
    no = len(nout) if no is None else no
    lasts = lasts or [[0] * len(x) for x in ins]
    d = tempfile.mkdtemp(prefix='grvtb_')
    for k, x in enumerate(ins):
        with open(os.path.join(d, f'in{k}.hex'), 'w') as f:
            for v, l in zip(x, lasts[k]):
                f.write(f'{(int(l) << iwt) | v:x}\n')
    L = []
    L.append('`timescale 1ns/1ps\nmodule tb;\n  reg clk = 0, rst_n = 0;\n  always #5 clk = ~clk;\n')
    L.append(f'  integer seed = {seed};\n  integer cyc = 0, fd;\n')
    if ni:
        L.append(f'  wire [{ni * iwt - 1}:0] s_tdata; reg [{ni - 1}:0] s_tvalid = 0; wire [{ni - 1}:0] s_tready; wire [{ni - 1}:0] s_tlast;\n')
        for k in range(ni):
            n = len(ins[k])
            L.append(f'  reg [{iwt}:0] mem{k} [0:{max(n, 1) - 1}]; integer ix{k} = 0;\n')
            L.append(f'  initial if ({n} > 0) $readmemh("{d}/in{k}.hex", mem{k});\n')
            L.append(f'  wire [{iwt}:0] cur{k} = (ix{k} < {n}) ? mem{k}[ix{k}] : 0;\n')
            L.append(f'  assign s_tdata[{k * iwt} +: {iwt}] = cur{k}[{iwt - 1}:0];\n  assign s_tlast[{k}] = cur{k}[{iwt}];\n')
    if no:
        L.append(f'  wire [{no * owt - 1}:0] m_tdata; wire [{no - 1}:0] m_tvalid; reg [{no - 1}:0] m_tready = 0; wire [{no - 1}:0] m_tlast;\n')
        for k in range(no):
            L.append(f'  integer oc{k} = 0;\n')
    pl = ',\n    '.join(f'.{k}({vparam(v)})' for k, v in params.items())
    conns = ['.clk(clk)', '.rst_n(rst_n)']
    if ni:
        conns += ['.s_tdata(s_tdata)', '.s_tvalid(s_tvalid)', '.s_tready(s_tready)', '.s_tlast(s_tlast)']
    if no:
        conns += ['.m_tdata(m_tdata)', '.m_tvalid(m_tvalid)', '.m_tready(m_tready)', '.m_tlast(m_tlast)']
    if run_src:
        conns.append('.run(rst_n)')
    for name, (w, val) in (cfg or {}).items():
        conns.append(f".{name}({w}'h{val & ((1 << w) - 1):x})")
    if extra_ports:
        conns.append(extra_ports)
    L.append(f'  {module} #(\n    {pl}\n  ) dut (\n    ' + ',\n    '.join(conns) + '\n  );\n')
    L.append(f'  initial begin fd = $fopen("{d}/out.txt", "w"); repeat (4) @(posedge clk); rst_n <= 1; end\n')
    L.append('  always @(posedge clk) begin\n    cyc <= cyc + 1;\n')
    for k in range(ni):
        n = len(ins[k])
        L.append(f'    if (rst_n) begin\n      if (s_tvalid[{k}] && s_tready[{k}]) ix{k} = ix{k} + 1;\n'
                 f'      if (!s_tvalid[{k}] || s_tready[{k}]) s_tvalid[{k}] <= (ix{k} < {n}) && (($random(seed) & 127) < {vp * 128 // 100});\n    end\n')
    for k in range(no):
        L.append(f'    if (rst_n && m_tvalid[{k}] && m_tready[{k}]) begin $fwrite(fd, "%0d %h %0d\\n", {k}, m_tdata[{k * owt} +: {owt}], m_tlast[{k}]); oc{k} = oc{k} + 1; end\n'
                 f'    m_tready[{k}] <= (($random(seed) & 127) < {rp * 128 // 100});\n')
    done = ' && '.join([f'oc{k} >= {nout[k]}' for k in range(no)] or ['1'])
    L.append(f'    if (({done}) || cyc > {timeout}) begin $fclose(fd); $finish; end\n  end\nendmodule\n')
    tb = os.path.join(d, 'tb.v')
    open(tb, 'w').write(''.join(L))
    cmd = ['iverilog', '-g2005', '-o', os.path.join(d, 'sim'), '-s', 'tb']
    for i in INC_DIRS:
        cmd += ['-I', os.path.join(ROOT, i)]
    for r in RTL_DIRS:
        cmd += ['-y', os.path.join(ROOT, r)]
    cmd += ['-Y', '.v', tb]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError('iverilog failed:\n' + r.stderr + '\n' + tb)
    r = subprocess.run(['vvp', '-n', os.path.join(d, 'sim')], capture_output=True, text=True, cwd=d)
    if r.returncode:
        raise RuntimeError('vvp failed:\n' + r.stdout + r.stderr)
    outs = [[] for _ in range(no)]
    louts = [[] for _ in range(no)]
    for ln in open(os.path.join(d, 'out.txt')):
        k, v, l = ln.split()
        outs[int(k)].append(int(v, 16))
        louts[int(k)].append(int(l))
    if not keep:
        shutil.rmtree(d, ignore_errors=True)
    return outs, louts
