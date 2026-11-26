#!/usr/bin/env python3
"""Compares the bit-exact model of the generated NBFM receiver with a floating-point reference.

    python3 check_float.py BUILD_DIR [--tune HZ] [--ms MS] [--save FILE.npy]

The input is an FM signal (1 kHz tone, 3 kHz deviation) at +tune Hz in a 1.92 MS/s complex stream,
plus a weaker interferer and noise. The reference is the GNU Radio float chain written with NumPy
(frequency-translating filter, quadrature demodulator, low-pass filter, volume)."""
import sys, os, argparse, math
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument('build')
ap.add_argument('--tune', type=float, default=100e3)
ap.add_argument('--ms', type=float, default=40)
ap.add_argument('--volume', type=float, default=1.0)
ap.add_argument('--save', help='write the input samples to this .npy file (for the Verilator testbench)')
a = ap.parse_args()

sys.path.insert(0, os.path.abspath(a.build))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'grvgen'))
import nbfm_rx_top_model as M                     # noqa: E402
from grv.firdes import firdes                     # noqa: E402

fs, n = 1.92e6, int(1.92e6 * a.ms / 1000)
t = np.arange(n) / fs
rng = np.random.default_rng(1)
dev, fa = 3e3, 1e3
phase = 2 * np.pi * a.tune * t + dev / fa * np.sin(2 * np.pi * fa * t)
x = 0.5 * np.exp(1j * phase)
x += 0.1 * np.exp(1j * 2 * np.pi * (a.tune - 300e3) * t)                 # interferer outside the channel
x += 0.01 * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
if a.save:
    np.save(a.save, x)

# ---------------- float reference
h1 = np.array(firdes.low_pass(1, fs, 100e3, 20e3))
y = x * np.exp(-2j * np.pi * a.tune * t)
y = np.convolve(y, h1)[:n][::8]
gain = (fs / 8) / (2 * math.pi * 5e3)
d = gain * np.angle(y[1:] * np.conj(y[:-1]))
d = np.concatenate([[gain * np.angle(y[0])], d])
h2 = np.array(firdes.low_pass(1, fs / 8, 4e3, 2e3))
ref = a.volume * np.convolve(d, h2)[:len(d)][::5]

# ---------------- bit-exact model
f = 15
q = [(max(-32768, min(32767, int(round(v.real * 2 ** f)))), max(-32768, min(32767, int(round(v.imag * 2 ** f))))) for v in x]
out = M.run({'adc_iq': q}, params={'tune': a.tune, 'volume': a.volume})
fo = [s['fmt'] for s in [{'fmt': None}]]
fa_ = None
for snk in M.GRAPH['insts']:
    if snk['name'] == 'audio':
        fa_ = M.GRAPH['nets'][snk['ins'][0]]['f']
hw = np.array(out['audio']) / 2.0 ** fa_
m = min(len(hw), len(ref))
hw, ref = hw[:m], ref[:m]
skip = 80                                          # filter start-up
err = hw[skip:] - ref[skip:]
snr = 10 * np.log10(np.sum(ref[skip:] ** 2) / np.sum(err ** 2))
print(f'audio samples: {m}, output format s16.{fa_}')
print(f'model vs float reference: SNR {snr:.1f} dB, max |error| {np.max(np.abs(err)):.2e} (LSB {2.0 ** -fa_:.2e})')
# tone quality of the model output
seg = hw[skip:]
k = np.arange(len(seg))
tone = np.exp(-2j * np.pi * fa * k / 48e3)
amp = 2 * abs(np.sum(seg * tone)) / len(seg)
print(f'1 kHz tone amplitude {amp:.4f} (expected {dev / 5e3 * a.volume:.4f})')
ok = snr > 40
print('PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
