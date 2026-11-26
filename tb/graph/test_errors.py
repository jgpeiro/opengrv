#!/usr/bin/env python3
"""grvgen diagnostics: graphs that must be rejected with a given error code."""
import os, sys, subprocess, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
from mkgrc import G  # noqa: E402

CASES = []


def case(code, *args):
    def deco(f):
        CASES.append((f.__name__, code, f, list(args)))
        return f
    return deco


def src(g, name='s', t='float', rate=None):
    return g.b('analog_sig_source_x', name, type=t, samp_rate=1e6, waveform='analog.GR_COS_WAVE', freq=1e3, amp=0.5,
               offset=0, phase=0, comment=f'@grv rate={rate}' if rate else '')


@case('E101')
def unsupported(g):
    s = src(g)
    e = g.b('epy_block', 'py', _source_code='x')
    g.c(s, e)


@case('E109')
def unconnected(g):
    s = src(g)
    a = g.b('blocks_add_xx', 'add', type='float', num_inputs=2, vlen=1)
    g.c(s, a, 0, 1)


@case('E304')
def rate_mismatch(g):
    s = src(g)
    k = g.b('blocks_keep_one_in_n', 'k', type='float', n=2, vlen=1)
    a = g.b('blocks_add_xx', 'add', type='float', num_inputs=2, vlen=1)
    g.c(s, k); g.c(k, a, 0, 0); g.c(s, a, 0, 1)
    o = g.b('grv_axil_sink', 'o', type='float')
    g.c(a, o)


@case('E302')
def too_fast(g):
    s = src(g, rate=100e6)
    o = g.b('grv_axil_sink', 'o', type='float')
    g.c(s, o)


@case('E303')
def budget(g):
    s = src(g, t='complex', rate=10e6)
    q = g.b('analog_agc_xx', 'agc', type='complex', rate=1e-3, reference=1, gain=1, max_gain=10)
    o = g.b('grv_axil_sink', 'o', type='complex')
    g.chain(s, q, o)


@case('E401')
def nonlinear(g):
    g.var('x', 1.0, kind='variable_qtgui_range', start=0.1, stop=2, step=0.1)
    s = src(g)
    k = g.b('blocks_multiply_const_vxx', 'k', type='float', const='1 / x', vlen=1)
    o = g.b('grv_axil_sink', 'o', type='float')
    g.chain(s, k, o)


@case('E107')
def message(g):
    s = src(g)
    o = g.b('grv_axil_sink', 'o', type='float')
    g.c(s, o)
    g.conns.append(['s', 'freq', 'o', 'cmd'])


# ------------------------------------------------------------------ peripheral endpoints and DMA (revision 0.2)
@case('E602')
def spi_too_slow(g):
    a = g.b('grv_spi_source', 'adc', type='float', role='master', samp_rate=1e6, sclk=13.5e6, frame_bits=32, data_bits=16)
    g.c(a, g.b('grv_axil_sink', 'o', type='float'))


@case('E603')
def too_many_dma(g):
    s = src(g)
    for k in range(17):
        g.c(s, g.b('grv_dma_sink', f'd{k:02d}', type='float'))


@case('E604')
def pin_collision(g):
    a = g.b('pad_source', 'p', type='float', label='log_txd')
    g.c(a, g.b('pad_sink', 'q', type='float', label='x'))
    g.c(src(g), g.b('grv_uart_sink', 'log', type='float', baud=115200))


@case('E605')
def uart_too_fast(g):
    g.c(src(g), g.b('grv_uart_sink', 'u', type='float', baud=10e6))


@case('E606')
def spi_field(g):
    g.c(src(g), g.b('grv_spi_sink', 'd', type='float', role='master', frame_bits=16, data_pos=8, data_bits=12))


@case('E607')
def spi_master_rate(g):
    a = g.b('grv_spi_source', 'adc', type='float', role='master', sclk=13.5e6)
    g.c(a, g.b('grv_axil_sink', 'o', type='float'))


@case('E608')
def dma_align(g):
    g.c(src(g), g.b('grv_dma_sink', 'd', type='float', address=0x20000002, length=16))


@case('E609')
def bad_via(g):
    g.c(src(g), g.b('blocks_file_sink', 'f', type='float', file='x', comment='@grv via=i2c'))


@case('E610')
def i2s_too_fast(g):
    g.c(src(g), g.b('grv_i2s_sink', 'dac', type='float', role='master', samp_rate=192e3, slot_bits=32, data_bits=24))


@case('W605', '--strict')
def i2s_mclk(g):
    g.c(src(g), g.b('grv_i2s_sink', 'dac', type='float', role='master', samp_rate=48e3, slot_bits=32, data_bits=24,
                    mclk=12.288e6))


@case('W601', '--strict')
def uart_slow(g):
    s = g.b('analog_sig_source_x', 's', type='short', samp_rate=48e3, waveform='analog.GR_COS_WAVE', freq=1e3, amp=100,
            offset=0, phase=0, comment='@grv rate=48e3')
    g.c(s, g.b('grv_uart_sink', 'u', type='short', baud=115200))


@case('W602', '--strict')
def pace_mismatch(g):
    s = g.b('analog_sig_source_x', 's', type='float', samp_rate=44.1e3, waveform='analog.GR_COS_WAVE', freq=1e3, amp=0.5,
            offset=0, phase=0, comment='@grv rate=44.1e3')
    g.c(s, g.b('grv_gpio_sink', 'dac', type='float', mode='sdm', data_bits=12, samp_rate=48e3))


def main():
    fails = 0
    for name, code, f, args in CASES:
        d = tempfile.mkdtemp(prefix='grverr_')
        g = G(name)
        f(g)
        grc = g.write(os.path.join(d, f'{name}.grc'))
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'grvgen', 'grvgen.py'), grc, '-o', d, '-q'] + args,
                           capture_output=True, text=True)
        ok = r.returncode != 0 and code in r.stderr
        fails += not ok
        print(f'{"PASS" if ok else "FAIL"} {name}: {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "(no message)"}')
    print(f'{len(CASES) - fails} / {len(CASES)} diagnostics tests passed')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
