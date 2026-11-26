"""Filter design: GNU Radio's gr::filter::firdes and gr::fft::window, reimplemented in NumPy
(same formulas, same tap counts), for graphs evaluated without GNU Radio installed."""
import math
import numpy as np

WIN_HAMMING, WIN_HANN, WIN_BLACKMAN, WIN_RECTANGULAR, WIN_KAISER, WIN_BLACKMAN_hARRIS, WIN_BARTLETT, WIN_FLATTOP = 0, 1, 2, 3, 4, 5, 6, 7
WIN_BLACKMAN_HARRIS = WIN_BLACKMAN_hARRIS
WIN_HANNING = WIN_HANN


class window:
    WIN_HAMMING, WIN_HANN, WIN_HANNING, WIN_BLACKMAN, WIN_RECTANGULAR = 0, 1, 1, 2, 3
    WIN_KAISER, WIN_BLACKMAN_hARRIS, WIN_BLACKMAN_HARRIS, WIN_BARTLETT, WIN_FLATTOP = 4, 5, 5, 6, 7

    @staticmethod
    def max_attenuation(t, beta=6.76):
        return {0: 53.0, 1: 44.0, 2: 74.0, 3: 21.0, 5: 92.0, 6: 27.0, 7: 93.0}.get(t, beta / 0.1102 + 8.7)

    @staticmethod
    def build(t, n, beta=6.76):
        k = np.arange(n)
        if n == 1:
            return np.ones(1)
        c = 2 * np.pi * k / (n - 1)
        if t == 0:
            return 0.54 - 0.46 * np.cos(c)
        if t == 1:
            return 0.5 - 0.5 * np.cos(c)
        if t == 2:
            return 0.42 - 0.5 * np.cos(c) + 0.08 * np.cos(2 * c)
        if t == 3:
            return np.ones(n)
        if t == 4:
            return np.i0(beta * np.sqrt(1 - (2.0 * k / (n - 1) - 1) ** 2)) / np.i0(beta)
        if t == 5:
            return 0.35875 - 0.48829 * np.cos(c) + 0.14128 * np.cos(2 * c) - 0.01168 * np.cos(3 * c)
        if t == 6:
            return 1 - np.abs(2.0 * k / (n - 1) - 1)
        if t == 7:
            return 1 - 1.93 * np.cos(c) + 1.29 * np.cos(2 * c) - 0.388 * np.cos(3 * c) + 0.028 * np.cos(4 * c)
        raise ValueError(f'window type {t}')

    hamming = staticmethod(lambda n: window.build(0, n))
    hann = staticmethod(lambda n: window.build(1, n))
    blackman = staticmethod(lambda n: window.build(2, n))
    rectangular = staticmethod(lambda n: window.build(3, n))
    kaiser = staticmethod(lambda n, beta=6.76: window.build(4, n, beta))
    blackman_harris = staticmethod(lambda n: window.build(5, n))
    blackmanharris = blackman_harris
    hanning = hann
    bartlett = staticmethod(lambda n: window.build(6, n))
    flattop = staticmethod(lambda n: window.build(7, n))


def _ntaps(fs, tw, win, beta):
    n = int(window.max_attenuation(win, beta) * fs / (22.0 * tw))
    return n | 1


def _lp_core(fs, fc, n, win, beta):
    w = window.build(win, n, beta)
    M = (n - 1) // 2
    k = np.arange(-M, M + 1)
    wc = 2 * np.pi * fc / fs
    with np.errstate(invalid='ignore', divide='ignore'):
        h = np.where(k == 0, wc / np.pi, np.sin(k * wc) / (np.pi * np.where(k == 0, 1, k)))
    return h * w, M


class firdes:
    WIN_HAMMING, WIN_HANN, WIN_HANNING, WIN_BLACKMAN, WIN_RECTANGULAR = 0, 1, 1, 2, 3
    WIN_KAISER, WIN_BLACKMAN_hARRIS, WIN_BLACKMAN_HARRIS, WIN_BARTLETT, WIN_FLATTOP = 4, 5, 5, 6, 7

    @staticmethod
    def low_pass(gain, fs, fc, tw, win=0, beta=6.76):
        n = _ntaps(fs, tw, win, beta)
        h, M = _lp_core(fs, fc, n, win, beta)
        fmax = h[M] + 2 * h[M + 1:].sum()
        return list(h * (gain / fmax))

    @staticmethod
    def low_pass_2(gain, fs, fc, tw, att, win=0, beta=6.76):
        n = int(att * fs / (22.0 * tw)) | 1
        h, M = _lp_core(fs, fc, n, win, beta)
        fmax = h[M] + 2 * h[M + 1:].sum()
        return list(h * (gain / fmax))

    @staticmethod
    def high_pass(gain, fs, fc, tw, win=0, beta=6.76):
        n = _ntaps(fs, tw, win, beta)
        w = window.build(win, n, beta)
        M = (n - 1) // 2
        k = np.arange(-M, M + 1)
        wc = 2 * np.pi * fc / fs
        with np.errstate(invalid='ignore', divide='ignore'):
            h = np.where(k == 0, 1 - wc / np.pi, -np.sin(k * wc) / (np.pi * np.where(k == 0, 1, k))) * w
        fmax = h[M] + 2 * (h[M + 1:] * np.cos(np.arange(1, M + 1) * np.pi)).sum()
        return list(h * (gain / fmax))

    @staticmethod
    def band_pass(gain, fs, lo, hi, tw, win=0, beta=6.76):
        n = _ntaps(fs, tw, win, beta)
        w = window.build(win, n, beta)
        M = (n - 1) // 2
        k = np.arange(-M, M + 1)
        w0, w1 = 2 * np.pi * lo / fs, 2 * np.pi * hi / fs
        with np.errstate(invalid='ignore', divide='ignore'):
            h = np.where(k == 0, (w1 - w0) / np.pi, (np.sin(k * w1) - np.sin(k * w0)) / (np.pi * np.where(k == 0, 1, k))) * w
        fmax = h[M] + 2 * (h[M + 1:] * np.cos(np.arange(1, M + 1) * (w0 + w1) * 0.5)).sum()
        return list(h * (gain / fmax))

    @staticmethod
    def band_reject(gain, fs, lo, hi, tw, win=0, beta=6.76):
        n = _ntaps(fs, tw, win, beta)
        w = window.build(win, n, beta)
        M = (n - 1) // 2
        k = np.arange(-M, M + 1)
        w0, w1 = 2 * np.pi * lo / fs, 2 * np.pi * hi / fs
        with np.errstate(invalid='ignore', divide='ignore'):
            h = np.where(k == 0, 1.0 + (w0 - w1) / np.pi, (np.sin(k * w0) - np.sin(k * w1)) / (np.pi * np.where(k == 0, 1, k))) * w
        fmax = h[M] + 2 * h[M + 1:].sum()
        return list(h * (gain / fmax))

    @staticmethod
    def complex_band_pass(gain, fs, lo, hi, tw, win=0, beta=6.76):
        lp = firdes.low_pass(gain, fs, (hi - lo) / 2, tw, win, beta)
        f = math.pi * (hi + lo) / fs
        ph = -f * (len(lp) >> 1)
        out = []
        for t in lp:
            out.append(t * complex(math.cos(ph), math.sin(ph)))
            ph += f
        return out

    @staticmethod
    def root_raised_cosine(gain, fs, sym_rate, alpha, ntaps):
        ntaps |= 1
        spb = fs / sym_rate
        taps, scale = [], 0.0
        for i in range(ntaps):
            x = i - ntaps // 2
            x1 = math.pi * x / spb
            x2 = 4 * alpha * x / spb
            x3 = x2 * x2 - 1
            if abs(x3) >= 1e-6:
                if i != ntaps // 2:
                    num = math.cos((1 + alpha) * x1) + math.sin((1 - alpha) * x1) / (4 * alpha * x / spb)
                else:
                    num = math.cos((1 + alpha) * x1) + (1 - alpha) * math.pi / (4 * alpha)
                den = x3 * math.pi
            else:
                if alpha == 1:
                    taps.append(-1.0)
                    scale += -1.0
                    continue
                x3 = (1 - alpha) * x1
                x2 = (1 + alpha) * x1
                num = (math.sin(x2) * (1 + alpha) * math.pi - math.cos(x3) * ((1 - alpha) * math.pi * spb) / (4 * alpha * x)
                       + math.sin(x3) * spb * spb / (4 * alpha * x * x))
                den = -32 * math.pi * alpha * alpha * x / spb
            t = 4 * alpha * num / den
            taps.append(t)
            scale += t
        return [t * gain / scale for t in taps]

    @staticmethod
    def gaussian(gain, spb, bt, ntaps):
        dt = 1.0 / spb
        s = 1.0 / (math.sqrt(math.log(2.0)) / (2 * math.pi * bt))
        t0 = -0.5 * ntaps
        taps = []
        for _ in range(ntaps):
            t0 += 1
            ts = s * dt * t0
            taps.append(math.exp(-0.5 * ts * ts))
        sc = sum(taps)
        return [t * gain / sc for t in taps]

    @staticmethod
    def window(t, n, beta=6.76):
        return list(window.build(t, n, beta))
