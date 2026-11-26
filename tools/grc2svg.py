#!/usr/bin/env python3
"""Draws a GNU Radio Companion flowgraph (.grc) as an SVG picture in the style of GRC: blocks at their
canvas positions with their key parameters, ports coloured by type, variables along the top.
    python3 tools/grc2svg.py FILE.grc [-o FILE.svg]"""
import os, sys, re, argparse, glob
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = {'complex': '#3399FF', 'float': '#F37A5C', 'int': '#00CC99', 'short': '#E6C200', 'byte': '#CC66CC',
        'bit': '#CC66CC', 'msg': '#888888'}
FONT = 'Roboto, Helvetica, Arial, sans-serif'

# label and parameters shown for the GNU Radio blocks used in the examples (others: the id)
GR = {
    'pad_source': ('Pad Source', ['label']), 'pad_sink': ('Pad Sink', ['label']),
    'freq_xlating_fir_filter_xxx': ('Frequency Xlating FIR Filter', ['decim', 'center_freq', 'taps']),
    'low_pass_filter': ('Low Pass Filter', ['decim', 'cutoff_freq', 'width']),
    'high_pass_filter': ('High Pass Filter', ['decim', 'cutoff_freq', 'width']),
    'band_pass_filter': ('Band Pass Filter', ['decim', 'low_cutoff_freq', 'high_cutoff_freq']),
    'root_raised_cosine_filter': ('Root Raised Cosine Filter', ['sym_rate', 'alpha', 'ntaps']),
    'interp_fir_filter_xxx': ('Interpolating FIR Filter', ['interp', 'taps']),
    'fir_filter_xxx': ('Decimating FIR Filter', ['decim', 'taps']),
    'analog_quadrature_demod_cf': ('Quadrature Demod', ['gain']),
    'single_pole_iir_filter_xx': ('Single Pole IIR Filter', ['alpha']),
    'blocks_complex_to_mag': ('Complex to Mag', []), 'blocks_complex_to_mag_squared': ('Complex to Mag^2', []),
    'blocks_complex_to_real': ('Complex to Real', []), 'blocks_complex_to_float': ('Complex to Float', []),
    'blocks_float_to_complex': ('Float to Complex', []), 'blocks_float_to_uchar': ('Float to UChar', []),
    'dc_blocker_xx': ('DC Blocker', ['length']), 'analog_agc_xx': ('AGC', ['rate', 'reference']),
    'blocks_multiply_const_vxx': ('Multiply Const', ['const']), 'blocks_add_xx': ('Add', []),
    'blocks_sub_xx': ('Subtract', []), 'blocks_probe_signal_x': ('Probe Signal', []),
    'digital_glfsr_source_x': ('GLFSR Source', ['degree']), 'blocks_pack_k_bits_bb': ('Pack K Bits', ['k']),
    'digital_chunks_to_symbols_xx': ('Chunks to Symbols', ['symbol_table']),
    'digital_costas_loop_cc': ('Costas Loop', ['w', 'order']), 'blocks_keep_one_in_n': ('Keep 1 in N', ['n']),
    'blocks_keep_m_in_n': ('Keep M in N', ['m', 'n']), 'digital_binary_slicer_fb': ('Binary Slicer', []),
    'blocks_stream_to_vector': ('Stream to Vector', ['num_items']),
    'blocks_vector_to_stream': ('Vector to Stream', ['num_items']),
    'fft_vxx': ('FFT', ['fft_size', 'window']), 'analog_sig_source_x': ('Signal Source', ['waveform', 'freq', 'amp']),
    'blocks_rotator_cc': ('Rotator', ['phase_inc']), 'blocks_abs_xx': ('Abs', []),
    'blocks_moving_average_xx': ('Moving Average', ['length', 'scale']),
    'blocks_threshold_ff': ('Threshold', ['low', 'high']),
    'variable': ('Variable', ['value']), 'variable_qtgui_range': ('QT GUI Range', ['value', 'start', 'stop']),
}
SHOW_GRV = {
    'grv_i2s_sink': ['role', 'samp_rate', 'format', 'data_bits'], 'grv_i2s_source': ['role', 'samp_rate', 'format', 'data_bits'],
    'grv_spi_sink': ['role', 'samp_rate', 'frame_bits', 'data_bits'], 'grv_spi_source': ['role', 'samp_rate', 'frame_bits', 'data_bits'],
    'grv_uart_sink': ['baud', 'text'], 'grv_uart_source': ['baud'],
    'grv_gpio_sink': ['mode', 'pins', 'samp_rate'], 'grv_gpio_source': ['mode', 'pins', 'samp_rate'],
    'grv_dma_sink': ['mode', 'burst'], 'grv_dma_source': ['mode', 'burst'],
    'grv_cic_decim': ['stages', 'ratio'], 'grv_cic_interp': ['stages', 'ratio'],
    'grv_axil_sink': ['depth'], 'grv_axil_source': ['depth'], 'grv_axil_probe': [],
}
NAMES = {'samp_rate': 'Sample Rate', 'decim': 'Decimation', 'interp': 'Interpolation', 'center_freq': 'Center Freq',
         'taps': 'Taps', 'cutoff_freq': 'Cutoff', 'width': 'Transition', 'gain': 'Gain', 'alpha': 'Alpha',
         'length': 'Length', 'rate': 'Rate', 'reference': 'Reference', 'const': 'Constant', 'degree': 'Degree',
         'k': 'K', 'symbol_table': 'Symbols', 'w': 'Loop BW', 'order': 'Order', 'n': 'N', 'm': 'M',
         'num_items': 'Items', 'fft_size': 'FFT Size', 'window': 'Window', 'waveform': 'Waveform', 'freq': 'Frequency',
         'amp': 'Amplitude', 'phase_inc': 'Phase Inc', 'scale': 'Scale', 'low': 'Low', 'high': 'High',
         'value': 'Value', 'start': 'Start', 'stop': 'Stop', 'label': 'Label', 'role': 'Role', 'format': 'Format',
         'data_bits': 'Data Bits', 'frame_bits': 'Frame Bits', 'baud': 'Baud', 'text': 'Text', 'mode': 'Mode',
         'pins': 'Pins', 'burst': 'Burst', 'stages': 'Stages', 'ratio': 'Ratio', 'depth': 'FIFO', 'sym_rate': 'Symbol Rate',
         'ntaps': 'Taps', 'low_cutoff_freq': 'Low Cutoff', 'high_cutoff_freq': 'High Cutoff'}


def grv_labels():
    out = {}
    for f in glob.glob(os.path.join(ROOT, 'grc', '*.block.yml')):
        y = yaml.safe_load(open(f))
        out[y['id']] = y.get('label', y['id'])
    return out


def esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def short(v, n=30):
    v = str(v).replace('window.', '').replace('analog.GR_', '').replace('firdes.', '').replace('_WAVE', '')
    v = re.sub(r'(\d)e\+?0*(\d)', r'\1e\2', v)
    try:
        x = float(v)
        if x != 0 and (abs(x) >= 1e4 or abs(x) < 1e-3):
            for unit, k in (('G', 1e9), ('M', 1e6), ('k', 1e3)):
                if abs(x) >= k:
                    v = f'{x / k:g}{unit}'
                    break
            else:
                v = f'{x:g}'
        else:
            v = f'{x:g}'
    except ValueError:
        pass
    return v if len(v) <= n else v[:n - 1] + '…'


def port_type(b):
    t = str(b['parameters'].get('type', ''))
    i = b['id']
    if i in ('blocks_complex_to_mag', 'blocks_complex_to_mag_squared', 'blocks_complex_to_real',
             'analog_quadrature_demod_cf'):
        return 'complex', 'float'
    if i == 'digital_binary_slicer_fb':
        return 'float', 'byte'
    if i == 'blocks_float_to_uchar':
        return 'float', 'byte'
    if i in ('blocks_pack_k_bits_bb', 'digital_glfsr_source_x'):
        return 'byte', 'byte'
    if i == 'digital_chunks_to_symbols_xx':
        return 'byte', b['parameters'].get('out_type', 'complex')
    if i in ('blocks_rotator_cc', 'digital_costas_loop_cc'):
        return 'complex', 'complex'
    if i == 'blocks_threshold_ff':
        return 'float', 'float'
    if i in ('freq_xlating_fir_filter_xxx', 'interp_fir_filter_xxx', 'fir_filter_xxx'):
        m = {'c': 'complex', 'f': 'float', 's': 'short', 'i': 'int'}
        return m.get(t[:1], 'complex'), m.get(t[1:2], 'complex')
    if i in ('low_pass_filter', 'high_pass_filter', 'band_pass_filter', 'root_raised_cosine_filter'):
        c = 'complex' if 'ccf' in t or 'ccc' in t else 'float'
        return c, c
    if i == 'dc_blocker_xx':
        return ('complex',) * 2 if t == 'cc' else ('float',) * 2
    if i == 'grv_cic_decim' or i == 'grv_cic_interp':
        return (t or 'float',) * 2
    t = t if t in PORT else 'float' if t in ('', 'fff') else 'complex' if t == 'ccc' else 'float'
    return t, t


def nports(b, conns, side):
    name = b['name']
    idx = [int(c[1] if side == 'out' else c[3]) for c in conns if c[0 if side == 'out' else 2] == name]
    i = b['id']
    if side == 'in':
        if i in ('pad_source', 'analog_sig_source_x', 'digital_glfsr_source_x') or i.endswith('_source') \
                or i.startswith('variable'):
            return 0
        k = int(b['parameters'].get('num_inputs', 1) or 1)
        return max([k] + [x + 1 for x in idx])
    if i.endswith('_sink') or i.startswith('variable') or i == 'blocks_probe_signal_x':
        return 0
    return max([1] + [x + 1 for x in idx])


_LABELS = None


def box(b, conns):
    """text lines, size and ports of a block"""
    global _LABELS
    if _LABELS is None:
        _LABELS = dict(GR)
        for k, v in grv_labels().items():
            _LABELS[k] = (v, SHOW_GRV.get(k, []))
    lab, show = _LABELS.get(b['id'], (b['id'], []))
    lines = [(lab, True), (f'ID: {b["name"]}', False)]
    for k in show:
        if k in b['parameters'] and str(b['parameters'][k]) not in ('', 'None'):
            lines.append((f'{NAMES.get(k, k)}: {short(b["parameters"][k])}', False))
    w = max(130, max(len(t) * (7.6 if bold else 6.6) for t, bold in lines) + 26)
    nin, nout = nports(b, conns, 'in'), nports(b, conns, 'out')
    h = max(22 + 15 * (len(lines) - 1) + 12, 24 * max(nin, nout) + 12)
    return dict(w=w, h=h, lines=lines, nin=nin, nout=nout, types=port_type(b), var=b['id'].startswith('variable'))


def render(path, wrap=None):
    y = yaml.safe_load(open(path))
    conns = y.get('connections', [])
    boxes = {}
    for b in y['blocks']:
        if b.get('states', {}).get('state') == 'disabled':
            continue
        d = box(b, conns)
        d['x'], d['y'] = b['states']['coordinate']
        boxes[b['name']] = d
    # long graphs: the columns wrap into bands of at most `wrap` pixels, one below the other
    blocks = [b for b in boxes.values() if not b['var']]
    for b in boxes.values():
        b['band'] = 0
    if wrap and blocks:
        xs = sorted({b['x'] for b in blocks})
        right = {x: max(b['x'] + b['w'] for b in blocks if b['x'] == x) for x in xs}
        bands, start = [[]], xs[0]
        for x in xs:
            if bands[-1] and right[x] - start > wrap:
                bands.append([])
                start = x
            bands[-1].append(x)
        if len(bands) > 1:
            nexty = None
            for k, cols in enumerate(bands):
                mem = [b for b in blocks if b['x'] in cols]
                dx = cols[0] - (16 if k == 0 else 56)
                dy = 0 if nexty is None else nexty - min(b['y'] for b in mem)     # each band right below the last
                for b in mem:
                    b['band'] = k
                    b['x'] -= dx
                    b['y'] += dy
                nexty = max(b['y'] + b['h'] for b in mem) + 64
    # options block
    op = y['options']['parameters']
    boxes['_options'] = dict(x=y['options']['states']['coordinate'][0], y=y['options']['states']['coordinate'][1],
                             w=0, h=0, lines=[('Options', True), (f'ID: {op.get("id", "")}', False),
                                              ('Generate: No GUI', False)], nin=0, nout=0, types=('', ''), var=True)
    b = boxes['_options']
    b['w'] = max(130, max(len(t) * 7 for t, _ in b['lines']) + 26)
    b['h'] = 22 + 15 * 2 + 12

    def pin(name, side, k):
        b = boxes[name]
        n = b['nin'] if side == 'in' else b['nout']
        py = b['y'] + b['h'] / 2 + (k - (n - 1) / 2) * 24
        return (b['x'] - 9 if side == 'in' else b['x'] + b['w'] + 9), py
    W = max(b['x'] + b['w'] for b in boxes.values()) + 40
    H = max(b['y'] + b['h'] for b in boxes.values()) + 24
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} {H:.0f}" width="{W:.0f}" height="{H:.0f}" '
           f'font-family="{FONT}">',
           '<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
           '<path d="M0 1L10 5L0 9z" fill="#555"/></marker></defs>',
           f'<rect width="{W:.0f}" height="{H:.0f}" fill="#FFFFFF"/>']
    # connections behind the blocks: vertical runs in the gaps between columns, long runs in the gaps
    # between rows
    edges = [(a, int(pa), bb, int(pb)) for a, pa, bb, pb in conns if a in boxes and bb in boxes]
    # a lane per source port in each gap, ordered by the height of the source
    lanes = {}
    for bd, gx in sorted({(boxes[bb]['band'], boxes[bb]['x']) for _, _, bb, _ in edges}):
        srcs = sorted({(a, pa) for a, pa, bb, _ in edges if boxes[bb]['x'] == gx and boxes[bb]['band'] == bd
                       and boxes[a]['band'] == bd}, key=lambda k: pin(k[0], 'out', k[1])[1])
        left = max([c['x'] + c['w'] for c in boxes.values() if not c['var'] and c['band'] == bd and c['x'] < gx]
                   + [gx - 80]) + 18
        step = min(10, (gx - 18 - left) / max(1, len(srcs)))
        for i, k in enumerate(srcs):
            lanes[(bd, gx, k)] = left + step * i
    cross = {}
    for bd in sorted({boxes[a]['band'] for a, _, _, _ in edges}):
        cs = sorted([e for e in edges if boxes[e[0]]['band'] == bd and boxes[e[2]]['band'] != bd],
                    key=lambda e: pin(e[0], 'out', e[1])[1])
        for i, e in enumerate(cs):
            cross[e] = i
    for a, pa, bb, pb in edges:
        sa, ta = boxes[a], boxes[bb]
        x1, y1 = pin(a, 'out', pa)
        x2, y2 = pin(bb, 'in', pb)
        xb = lanes.get((ta['band'], ta['x'], (a, pa)), x2 - 20)
        if sa['band'] != ta['band']:            # into the next band: down below the band, left, down to the port
            i = cross[(a, pa, bb, pb)]
            yc = max(c['y'] + c['h'] for c in boxes.values() if not c['var'] and c['band'] == sa['band']) + 18 + 9 * i
            xt = ta['x'] - 22 - 9 * i
            d = f'M{x1:.1f} {y1:.1f}H{x1 + 12:.1f}V{yc:.1f}H{xt:.1f}V{y2:.1f}H{x2:.1f}'
            out.append(f'<path d="{d}" fill="none" stroke="#555" stroke-width="1.4" marker-end="url(#a)"/>')
            continue
        between = [c for c in boxes.values() if not c['var'] and c['band'] == sa['band'] and c['x'] > sa['x'] + 1
                   and c['x'] < ta['x'] - 1]
        if not between:
            d = f'M{x1:.1f} {y2:.1f}H{x2:.1f}' if abs(y1 - y2) < 6 else f'M{x1:.1f} {y1:.1f}H{xb:.1f}V{y2:.1f}H{x2:.1f}'
        else:
            xa = sa['x'] + sa['w'] + 30
            blocking = [c for c in between if c['y'] - 4 < y1 < c['y'] + c['h'] + 4]
            if not blocking:
                d = f'M{x1:.1f} {y1:.1f}H{xb:.1f}V{y2:.1f}H{x2:.1f}'
            else:
                yc = min(c['y'] for c in between + [ta] if c['y'] + c['h'] > min(y1, y2) - 4) - 13
                d = f'M{x1:.1f} {y1:.1f}H{xa:.1f}V{yc:.1f}H{xb:.1f}V{y2:.1f}H{x2:.1f}'
        out.append(f'<path d="{d}" fill="none" stroke="#555" stroke-width="1.4" marker-end="url(#a)"/>')
    for name, b in boxes.items():
        fill, stroke = ('#F2F0FA', '#6B6B8E') if not b['var'] else ('#EFEFF6', '#8C8CA8')
        out.append(f'<rect x="{b["x"]}" y="{b["y"]}" width="{b["w"]:.0f}" height="{b["h"]:.0f}" rx="4" fill="{fill}" '
                   f'stroke="{stroke}" stroke-width="1.3"/>')
        cy = b['y'] + 18
        for i, (t, bold) in enumerate(b['lines']):
            if bold:
                out.append(f'<text x="{b["x"] + b["w"] / 2:.1f}" y="{cy}" font-size="12.5" font-weight="bold" '
                           f'text-anchor="middle" fill="#202030">{esc(t)}</text>')
                cy += 18
            else:
                out.append(f'<text x="{b["x"] + 10}" y="{cy}" font-size="11" fill="#303040">{esc(t)}</text>')
                cy += 15
        for side, n, t in (('in', b['nin'], b['types'][0]), ('out', b['nout'], b['types'][1])):
            for k in range(n):
                px, py = pin(name, side, k)
                x0 = px if side == 'out' else px
                out.append(f'<rect x="{x0 - 9 if side == "out" else x0:.1f}" y="{py - 7:.1f}" width="9" height="14" '
                           f'fill="{PORT.get(t, "#999")}" stroke="#444" stroke-width="0.8"/>')
    out.append('</svg>')
    return '\n'.join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('grc')
    ap.add_argument('-o')
    ap.add_argument('--wrap', type=int, help='wrap the columns into bands of at most this many pixels')
    a = ap.parse_args()
    s = render(a.grc, a.wrap)
    o = a.o or os.path.splitext(a.grc)[0] + '.svg'
    open(o, 'w').write(s)
    print(o)


if __name__ == '__main__':
    main()
