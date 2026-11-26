#!/usr/bin/env python3
"""Writes examples/<name>/README.md, examples/<name>/<name>.png (the flowgraph, drawn by grc2svg) and the
index examples/README.md from examples/examples.json and the outputs of tools/run_examples.py (build/ex).
    python3 tools/example_docs.py"""
import os, sys, json, re, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from grc2svg import render  # noqa: E402

PK = {'i2s': 'I2S', 'uart': 'UART', 'spi_master': 'SPI master', 'spi_slave': 'SPI slave', 'gpio': 'GPIO'}


def png(svg_path, png_path):
    """SVG -> PNG at twice the size, with headless Chrome (Playwright)"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path='/usr/bin/google-chrome', args=['--no-sandbox'])
        pg = br.new_page(device_scale_factor=2)
        pg.goto('file://' + os.path.abspath(svg_path))
        pg.query_selector('svg').screenshot(path=png_path)
        br.close()


def hz(x):
    for u, k in (('MHz', 1e6), ('kHz', 1e3)):
        if abs(x) >= k:
            return f'{x / k:g} {u}'
    return f'{x:g} Hz'


def rate(x):
    for u, k in (('MS/s', 1e6), ('kS/s', 1e3)):
        if abs(x) >= k:
            return f'{x / k:g} {u}'
    return f'{x:g} S/s'


def doc(name, meta, all_meta):
    d = os.path.join(ROOT, 'examples', name)
    b = os.path.join(ROOT, 'build', 'ex', name)
    top = name + '_top'
    m = json.load(open(os.path.join(b, top + '_map.json')))
    rep = open(os.path.join(b, top + '_report.md')).read()
    tot = re.search(r'Estimated totals: (.*?)\. Estimates', rep)
    svg = os.path.join(b, name + '.svg')
    open(svg, 'w').write(render(os.path.join(d, name + '.grc'), wrap=1100))
    png(svg, os.path.join(d, name + '.png'))
    L = [f'# {meta["title"]}', '', f'![{name} flowgraph]({name}.png)', '', meta['desc'], '',
         '## Interfaces', '', '| Interface | Kind | Format and rate | Pins or address |', '|---|---|---|---|']
    for p in m['pads']:
        L.append(f'| {p["label"]} | AXI4-Stream pad ({p["dir"]}) | {p["fmt"]["str"]}, {rate(p["rate"]) if p.get("rate") else "-"} '
                 f'| `{p["label"]}_tdata`, `_tvalid`, `_tready`, `_tlast` |')
    for p in m['periph']:
        pins = ', '.join(f'`{x["name"]}`' for x in p['pins'])
        r = p.get('pace') or p.get('rate')
        L.append(f'| {p["name"]} | {PK[p["periph"]]} {"input" if p["dir"] == "in" else "output"} | {p["fmt"]["str"]}'
                 f'{", " + rate(r) if r else ""} | {pins} (registers at 0x{p["addr"]:04x}) |')
    for p in m['dma']:
        L.append(f'| {p["name"]} | DMA channel ({p["dir"].upper()}, {p["mode"]}) | {p["fmt"]["str"]} in {p["container"]}-byte '
                 f'containers{", " + rate(p["rate"]) if p.get("rate") else ""} | `m_mem_*` (registers at 0x{p["addr"]:04x}) |')
    for p in m['probes']:
        L.append(f'| {p["name"]} | probe | {p["fmt"]["str"]} | register 0x{p["addr"]:04x} |')
    for p in m['sources'] + m['sinks']:
        L.append(f'| {p["name"]} | AXI4-Lite endpoint | {p["fmt"]["str"]} | 0x{p["addr"]:04x} |')
    if m['params']:
        L += ['', '## Runtime parameters', '', '| Variable | Range | Default | Register | Block |', '|---|---|---|---|---|']
        for p in m['params']:
            L.append(f'| `{p["var"]}` | {p["lo"]:g} .. {p["hi"]:g} | {p["default"]} | 0x{p["addr"]:04x} | {p["inst"]} |')
        L += ['', 'Write the hardware value of a parameter with the conversion function of the generated header '
              f'(`{top}_<name>_hw()`), then set `CTRL.COMMIT`.']
    L += ['', '## Resources', '', f'grvgen estimate at {m["clk"] / 1e6:g} MHz: {tot.group(1) if tot else "see the report"}. '
          'The report in `generated/` lists every block, filter and stream.', '',
          '## Build and simulate', '', '```sh',
          f'python3 grvgen/grvgen.py examples/{name}/{name}.grc -o build/{name}']
    sim = f'build/{name}/{top}_sim.sh -n {meta["n"]}' + ''.join(f' --param {k}={v}' for k, v in meta['params'].items())
    L += [sim, '```', '', 'The testbench drives and checks the pins with models of the devices (converters, codecs, a '
          'UART line, a memory with random latency) and compares every output with the bit-exact graph model. '
          f'`python3 tools/run_examples.py -k {name}` does both steps.', '',
          '`generated/` holds the top level, the C header, the report' + (' and the pin constraint template' if m['periph'] else '') +
          ' as grvgen writes them.', '']
    open(os.path.join(d, 'README.md'), 'w').write('\n'.join(L))
    return m, tot.group(1) if tot else ''


def main():
    meta = json.load(open(os.path.join(ROOT, 'examples', 'examples.json')))
    rows = []
    for n in meta:
        m, tot = doc(n, meta[n], meta)
        ifs = sorted({PK[p['periph']] for p in m['periph']} | ({'DMA'} if m['dma'] else set()) |
                     ({'pad'} if m['pads'] else set()) | ({'probe'} if m['probes'] else set()))
        rows.append(f'| [{n}]({n}/README.md) | {meta[n]["title"]} | {", ".join(ifs)} |')
    L = ['# Examples', '', 'Every example is a GNU Radio Companion flowgraph that grvgen turns into a top level. '
         '`python3 tools/run_examples.py` generates and simulates all of them against their bit-exact models '
         '(`-k NAME` for one, `-j N` in parallel). The flowgraphs come from `tools/mkexamples.py`; the pictures '
         'from `tools/grc2svg.py`.', '',
         '| Example | What it is | Interfaces |', '|---|---|---|',
         '| [nbfm_rx](nbfm_rx/nbfm_rx.grc) | The NBFM receiver of the design document | pad, AXI4-Lite, probe |',
         '| [nbfm_rx_pe](nbfm_rx_pe/nbfm_rx_pe.grc) | The same receiver with a sigma-delta pin, DMA and a UART log | pad, GPIO, DMA, UART |'] + rows + ['']
    open(os.path.join(ROOT, 'examples', 'README.md'), 'w').write('\n'.join(L))


if __name__ == '__main__':
    main()
