// grv_bfm.h - bus-functional models of the generated Verilator testbenches (revision 0.2): devices at
// the pins of the peripheral endpoints (UART, SPI master and slave, GPIO) and a memory at the DMA port.
// Copied next to <top>_tb.cpp by grvgen; the testbench defines rnd() before including it.
//
// Every model has a step() called once per clock, right after the rising edge: it sees the outputs of
// the design for this clock and returns the values of the inputs, which the design samples at the next
// edge (a device with a small delay after the edge). Inputs are driven once `on` is set (RUN written).
// Output models collect the samples they see in `got`; check() compares them with the expected samples,
// allowing leading samples that are not in the expected list (idle or underflow values before the graph
// delivers its first sample).
#pragma once
#include <cstdint>
#include <cstdio>
#include <cmath>
#include <deque>
#include <vector>
#include <unordered_map>

static inline uint64_t bfm_mask(int w) { return w >= 64 ? ~0ull : ((1ull << w) - 1); }
static inline int64_t bfm_sx(uint64_t v, int w) {
  v &= bfm_mask(w);
  return (w < 64 && (v >> (w - 1)) & 1) ? (int64_t)(v | ~bfm_mask(w)) : (int64_t)v;
}

// ------------------------------------------------------------------ comparison with alignment
struct Got {
  std::vector<uint64_t> d;
  bool dedupe = false;          // compare runs of equal values once (outputs that hold their value)
  int off = -1;                 // offset of the first expected sample
  size_t slack = 0;             // extra samples to collect (outputs that never stop: choose the best offset)
};
static std::vector<uint64_t> bfm_runs(const std::vector<uint64_t> &v) {
  std::vector<uint64_t> r;
  for (size_t k = 0; k < v.size(); k++) if (!k || v[k] != v[k - 1]) r.push_back(v[k]);
  return r;
}
// number of collected samples still needed (0: complete or hopeless)
static size_t bfm_need(Got &g, const std::vector<uint64_t> &exp0, int w) {
  std::vector<uint64_t> exp = g.dedupe ? bfm_runs(exp0) : exp0;
  std::vector<uint64_t> got = g.dedupe ? bfm_runs(g.d) : g.d;
  if (exp.empty()) return 0;
  size_t m = exp.size() < 8 ? exp.size() : 8;
  if (g.off < 0) {
    for (size_t o = 0; o + m <= got.size() && o <= 256; o++) {
      bool ok = true;
      for (size_t k = 0; k < m && ok; k++) ok = ((got[o + k] ^ exp[k]) & bfm_mask(w)) == 0;
      if (ok) { g.off = (int)o; break; }
    }
    if (g.off < 0) return got.size() < 256 + m ? 1 : 0;
  }
  size_t need = g.off + exp.size() + g.slack;
  return got.size() >= need ? 0 : need - got.size();
}
static size_t bfm_check(const char *name, Got &g, const std::vector<uint64_t> &exp0, int w, size_t &done) {
  std::vector<uint64_t> exp = g.dedupe ? bfm_runs(exp0) : exp0;
  std::vector<uint64_t> got = g.dedupe ? bfm_runs(g.d) : g.d;
  done = 0;
  if (exp.empty()) return 0;
  bfm_need(g, exp0, w);
  if (g.off >= 0) {             // the offset with the most matches (a prefix may match at several offsets)
    size_t best = 0; int bo = g.off;
    for (int o = g.off; o <= g.off + (int)g.slack + 8 && o < (int)got.size(); o++) {
      size_t m = 0;
      for (size_t k = 0; k < exp.size() && o + k < got.size(); k++) m += ((got[o + k] ^ exp[k]) & bfm_mask(w)) == 0;
      if (m > best) { best = m; bo = o; }
    }
    g.off = bo;
  }
  if (g.off < 0) {
    printf("MISMATCH %s: the first expected samples never appear (%zu samples seen", name, got.size());
    for (size_t k = 0; k < got.size() && k < 6; k++) printf("%s%llx", k ? " " : ": ", (unsigned long long)got[k]);
    printf(", expected %llx ...)\n", (unsigned long long)exp[0]);
    return exp.size();
  }
  size_t bad = 0;
  for (size_t k = 0; k < exp.size(); k++) {
    size_t i = g.off + k;
    if (i >= got.size()) break;
    done++;
    if (((got[i] ^ exp[k]) & bfm_mask(w)) != 0 && bad++ < 10)
      printf("MISMATCH %s[%zu]: got %llx expected %llx\n", name, k, (unsigned long long)(got[i] & bfm_mask(w)),
             (unsigned long long)(exp[k] & bfm_mask(w)));
  }
  return bad;
}

// ------------------------------------------------------------------ UART
// line towards the design (its rxd): bytes of the queued samples, LSB first in each byte
struct UartDrv {
  double bit; int par; bool stop2, inv, flow, msbf; int nb;
  std::deque<int> q;
  std::vector<int> lv;
  bool act = false;
  uint64_t start = 0, idle_until = 0;
  UartDrv(double bit_, int par_, bool stop2_, bool inv_, bool flow_, bool msbf_, int nb_)
    : bit(bit_), par(par_), stop2(stop2_), inv(inv_), flow(flow_), msbf(msbf_), nb(nb_) {}
  void push(uint64_t v) {
    for (int k = 0; k < nb; k++) q.push_back((int)((v >> (8 * (msbf ? nb - 1 - k : k))) & 0xFF));
  }
  int step(uint64_t cyc, bool on, int rts_n) {
    if (!act && on && !q.empty() && cyc >= idle_until && (!flow || !rts_n)) {
      int b = q.front(); q.pop_front();
      lv.clear(); lv.push_back(0);
      int ones = 0;
      for (int k = 0; k < 8; k++) { lv.push_back((b >> k) & 1); ones += (b >> k) & 1; }
      if (par) lv.push_back(par == 1 ? (ones & 1) : !(ones & 1));
      lv.push_back(1);
      if (stop2) lv.push_back(1);
      act = true; start = cyc;
    }
    int l = 1;
    if (act) {
      size_t i = (size_t)((double)(cyc - start) / bit);
      if (i >= lv.size()) { act = false; idle_until = cyc + (uint64_t)(bit * (1 + rnd() % 3)); }
      else l = lv[i];
    }
    return l ^ (int)inv;
  }
};

// line from the design (its txd): bytes -> samples (binary or hexadecimal text)
struct UartMon {
  double bit; int par; bool stop2, inv, msbf, text, flow; int nb;
  Got got;
  bool act = false, armed = false; uint64_t t0 = 0; int k = 0, nbits; uint32_t sh = 0;
  std::vector<int> bytes; uint64_t tv = 0; int nd = 0;
  size_t ferr = 0;
  UartMon(double bit_, int par_, bool stop2_, bool inv_, bool msbf_, bool text_, bool flow_, int nb_)
    : bit(bit_), par(par_), stop2(stop2_), inv(inv_), msbf(msbf_), text(text_), flow(flow_), nb(nb_) {
    nbits = 1 + 8 + (par ? 1 : 0) + 1;
  }
  void byte(int b) {
    if (text) {
      int d = (b >= '0' && b <= '9') ? b - '0' : (b >= 'A' && b <= 'F') ? b - 'A' + 10 : (b >= 'a' && b <= 'f') ? b - 'a' + 10 : -1;
      if (d >= 0) { tv = (tv << 4) | (uint64_t)d; nd++; }
      else if ((b == ' ' || b == '\n') && nd) { got.d.push_back(tv); tv = 0; nd = 0; }
      return;
    }
    bytes.push_back(b);
    if ((int)bytes.size() == nb) {
      uint64_t v = 0;
      for (int i = 0; i < nb; i++) v |= (uint64_t)bytes[i] << (8 * (msbf ? nb - 1 - i : i));
      got.d.push_back(v); bytes.clear();
    }
  }
  // returns cts_n
  int step(uint64_t cyc, bool on, int txd) {
    int l = txd ^ (int)inv;
    if (!act) {
      if (!on) return 0;
      if (!armed) armed = l;                              // a character starts after an idle line
      else if (!l) { act = true; t0 = cyc; k = 0; sh = 0; }
    } else if ((double)(cyc - t0) >= bit * (k + 0.5)) {
      sh |= (uint32_t)l << k;
      if (++k == nbits) {
        act = false;
        if ((sh & 1) || !((sh >> (nbits - 1)) & 1)) ferr++;
        else byte((sh >> 1) & 0xFF);
      }
    }
    return flow ? ((cyc / 7000) % 5 == 4) : 0;          // with flow control, stall the sender now and then
  }
};

// ------------------------------------------------------------------ SPI
struct SpiFmt {
  int fb, cpol, cpha, lsbf, dpos, db, ofs, nc;
  uint32_t fmask() const { return fb >= 32 ? 0xFFFFFFFFu : ((1u << fb) - 1); }
  uint32_t dmask() const { return (db >= 32 ? 0xFFFFFFFFu : ((1u << db) - 1)); }
  uint32_t word(uint32_t comp) const {               // frame carrying a component (other bits: a pattern)
    uint32_t f = (comp ^ (ofs ? 1u << (db - 1) : 0)) & dmask();
    return ((0x5A5AA5A5u & ~(dmask() << dpos)) | (f << dpos)) & fmask();
  }
  uint32_t field(uint32_t w) const { return ((w >> dpos) & dmask()) ^ (ofs ? 1u << (db - 1) : 0); }
  int bit(uint32_t w, int k) const { return k >= fb ? 0 : lsbf ? (w >> k) & 1 : (w >> (fb - 1 - k)) & 1; }
};

// SPI slave device at a master endpoint: sends queued components (an ADC) and/or receives (a DAC)
struct SpiDev {
  SpiFmt f;
  std::deque<uint32_t> q;          // components to send
  Got got;                         // samples received
  std::vector<uint32_t> comps;
  int psk = -1, pcs = 1, sent = 0, rn = 0, miso = 0;
  uint32_t tw = 0, rw = 0;
  size_t bad_frames = 0;
  explicit SpiDev(SpiFmt f_) : f(f_) {}
  void push(uint64_t v) { for (int c = 0; c < f.nc; c++) q.push_back((uint32_t)(v >> (c * f.db)) & f.dmask()); }
  int step(int sclk, int cs_n, int mosi) {
    if (psk < 0) psk = sclk;
    if (pcs && !cs_n) {
      uint32_t c = 0;
      if (!q.empty()) { c = q.front(); q.pop_front(); }
      tw = f.word(c); sent = 0; rn = 0; rw = 0;
      if (!f.cpha) miso = f.bit(tw, sent++);
    } else if (!cs_n && sclk != psk) {
      bool lead = (psk == f.cpol);
      bool samp = f.cpha ? !lead : lead;
      if (samp) {
        if (f.lsbf) rw |= (uint32_t)mosi << rn; else rw = (rw << 1) | (uint32_t)mosi;
        rn++;
      } else {
        miso = f.bit(tw, sent++);
      }
    } else if (!pcs && cs_n) {
      if (rn == f.fb) {
        comps.push_back(f.field(rw));
        if ((int)comps.size() == f.nc) {
          uint64_t v = 0;
          for (int c = 0; c < f.nc; c++) v |= (uint64_t)comps[c] << (c * f.db);
          got.d.push_back(v); comps.clear();
        }
      } else if (rn) bad_frames++;
    }
    psk = sclk; pcs = cs_n;
    return miso;
  }
};

// SPI master at a slave endpoint: one chip-select frame per sample (NC words); sends queued samples (tx)
// or reads samples while drdy is high (rx)
struct SpiHost {
  SpiFmt f; int half, gap; bool rx;
  std::deque<uint32_t> q;
  Got got;
  int st = 0, bi = 0, nb, sclk, cs_n = 1, mosi = 0;
  uint64_t until = 0;
  uint32_t tw[2] = {0, 0}, rw = 0; uint64_t rv = 0;
  SpiHost(SpiFmt f_, int half_, int gap_, bool rx_) : f(f_), half(half_), gap(gap_), rx(rx_) { sclk = f.cpol; nb = f.fb * f.nc; }
  void push(uint64_t v) { for (int c = 0; c < f.nc; c++) q.push_back((uint32_t)(v >> (c * f.db)) & f.dmask()); }
  int obit(int k) const { return f.bit(tw[k / f.fb], k % f.fb); }
  void samp(int miso) {
    int k = bi % f.fb;
    if (f.lsbf) rw |= (uint32_t)miso << k; else rw = (rw << 1) | (uint32_t)miso;
    if (k == f.fb - 1) { rv |= (uint64_t)f.field(rw) << ((bi / f.fb) * f.db); rw = 0; }
  }
  // st: 0 idle, 1 setup, 2 first half of bit bi, 3 second half, 4 hold
  void step(uint64_t cyc, bool on, int miso, int drdy) {
    if (cyc < until) return;
    switch (st) {
    case 0: {
      bool go = on && (rx ? drdy : !q.empty());
      if (!go) return;
      for (int c = 0; c < f.nc; c++) {
        uint32_t x = 0;
        if (!rx) { x = q.front(); q.pop_front(); }
        tw[c] = f.word(x);
      }
      rw = 0; rv = 0; bi = 0;
      cs_n = 0; sclk = f.cpol; mosi = f.cpha ? 0 : obit(0);
      st = 1; until = cyc + half;
      return;
    }
    case 1: st = 2; until = cyc + half; return;           // first half of bit 0 (sclk idle)
    case 2:                                               // leading edge
      sclk = !f.cpol;
      if (f.cpha) mosi = obit(bi); else samp(miso);
      st = 3; until = cyc + half; return;
    case 3:                                               // trailing edge
      sclk = f.cpol;
      if (f.cpha) samp(miso);
      if (++bi < nb) { if (!f.cpha) mosi = obit(bi); st = 2; until = cyc + half; }
      else { st = 4; until = cyc + half; }
      return;
    case 4:
      cs_n = 1;
      if (rx) got.d.push_back(rv);
      st = 0; until = cyc + gap + rnd() % gap;
      return;
    }
  }
};

// ------------------------------------------------------------------ GPIO
// pins towards a GPIO input endpoint
struct GpioDrv {
  int mode; double per; int phase, filt, edge; uint64_t ofs;
  std::vector<uint64_t> v;
  uint64_t c0 = 0; bool started = false;
  size_t i = 0; uint64_t t = 0;
  int stb;
  GpioDrv(int mode_, double per_, int phase_, int filt_, int edge_, uint64_t ofs_)
    : mode(mode_), per(per_), phase(phase_), filt(filt_), edge(edge_), ofs(ofs_) { stb = edge; }
  uint64_t step(uint64_t cyc, bool on, uint64_t run_cyc) {
    if (v.empty()) return 0;
    if (on && !started) { started = true; c0 = run_cyc; t = cyc + 40 + filt; }
    if (mode == 0) {                                      // PERIODIC: each value centred on its sampling instant
      if (!started) return v[0] ^ ofs;
      double x = ((double)cyc - (double)c0 - phase - 1 + per / 2) / per;
      long j = (long)std::floor(x) - 1;
      if (j < 0) j = 0;
      if (j >= (long)v.size()) j = (long)v.size() - 1;
      return v[j] ^ ofs;
    }
    if (mode == 1) {                                      // STROBE: data, then the active edge, then idle
      if (started && cyc >= t && i < v.size()) {
        uint64_t k = cyc - t;
        if (k == 3) stb = !edge;
        if (k == 6) { stb = edge; i++; t = cyc + 30 + rnd() % 20; }
      }
      return (i < v.size() ? v[i] : v.back()) ^ ofs;
    }
    if (started && cyc >= t && i + 1 < v.size()) { i++; t = cyc + filt + 8 + rnd() % 8; }   // CHANGE
    return v[i] ^ ofs;
  }
};

// pins of a GPIO output endpoint
struct GpioMon {
  int mode; double per; int d, nc; uint64_t ofs; bool paced;
  Got got;
  uint64_t c0 = 0; bool started = false; long k = 1;
  // PWM
  long r0 = -1; int prev = 0; uint64_t win_start = 0, b0 = 0; std::vector<uint8_t> bits;
  std::unordered_map<long, int> hist;
  // sigma-delta
  std::vector<std::vector<double>> sdm; std::vector<long> acc; long wn = 0; long wk = 1;
  uint64_t last = ~0ull;
  GpioMon(int mode_, double per_, int d_, int nc_, uint64_t ofs_)
    : mode(mode_), per(per_), d(d_), nc(nc_), ofs(ofs_) {
    paced = per >= 1.0;
    got.dedupe = (mode == 0 && !paced) || (mode == 1 && paced);
    got.slack = (mode == 0 && !paced) ? 0 : 32;          // a parallel port without pacing changes only with the data
    acc.assign(nc, 0); sdm.resize(nc);
  }
  void step(uint64_t cyc, bool on, uint64_t run_cyc, uint64_t pins) {
    if (on && !started) { started = true; c0 = run_cyc; }
    if (!started) return;
    if (mode == 0) {
      if (paced) {
        if ((double)cyc >= (double)c0 + (k + 0.5) * per + 1) { got.d.push_back(pins ^ ofs); k++; }
      } else if (pins != last) { got.d.push_back(pins ^ ofs); last = pins; }
      return;
    }
    if (mode == 1) {                                      // PWM: periods start with a rising edge (pc = 0)
      long P = 1L << d;
      int any = 0;
      for (int c = 0; c < nc; c++) any |= (int)((pins >> c) & 1) && !((prev >> c) & 1);
      prev = (int)pins;
      if (bits.empty()) b0 = cyc;
      bits.push_back((uint8_t)pins);
      if (r0 < 0) {                                       // the first edge may come from the enable, not pc = 0
        if (any) { long ph = (long)((cyc - b0) % P); if (++hist[ph] >= 3) r0 = ph; }
        if (r0 < 0) return;
        win_start = (uint64_t)r0;
      }
      while (win_start + P <= bits.size()) {
        uint64_t v = 0;
        for (int c = 0; c < nc; c++) {
          int o = 0;
          for (long x = 0; x < P; x++) o += (bits[win_start + x] >> c) & 1;
          v |= (uint64_t)((o ^ (1 << (d - 1))) & ((1 << d) - 1)) << (c * d);
        }
        got.d.push_back(v);
        win_start += P;
      }
      return;
    }
    // sigma-delta: mean of +-FS over each sample period
    for (int c = 0; c < nc; c++) acc[c] += ((pins >> c) & 1) ? 1 : -1;
    wn++;
    if ((double)cyc >= (double)c0 + wk * per) {
      for (int c = 0; c < nc; c++) { sdm[c].push_back((double)acc[c] / wn); acc[c] = 0; }
      wn = 0; wk++;
    }
  }
  size_t windows() const { return sdm.empty() ? 0 : sdm[0].size(); }
  // sigma-delta: block means of 8 samples against the expected ones, best offset; returns 1 on failure
  size_t check_sdm(const char *name, const std::vector<uint64_t> &exp, double &rms_out) {
    const int B = 8;
    double fs = (double)(1 << (d - 1));
    double best = 1e9; int bo = -1;
    size_t nb = exp.size() / B;
    for (int o = 0; o < 64; o++) {
      double e2 = 0; size_t n = 0;
      for (size_t b = 1; b + 1 < nb; b++) {
        for (int c = 0; c < nc; c++) {
          double me = 0, mg = 0; bool ok = true;
          for (int k2 = 0; k2 < B; k2++) {
            size_t ie = b * B + k2, ig = ie + o;
            if (ig >= sdm[c].size()) { ok = false; break; }
            me += (double)bfm_sx(exp[ie] >> (c * d), d) / fs;
            mg += sdm[c][ig];
          }
          if (!ok) continue;
          e2 += (me - mg) * (me - mg) / (B * B); n++;
        }
      }
      if (n > nb / 2 && sqrt(e2 / n) < best) { best = sqrt(e2 / n); bo = o; }
    }
    rms_out = best;
    if (bo < 0 || best > 0.03) {
      printf("MISMATCH %s: sigma-delta block means differ from the expected samples by %.4f of full scale (rms)\n", name, best);
      return 1;
    }
    return 0;
  }
};

// ------------------------------------------------------------------ I2S
// A codec at an I2S endpoint: it follows bclk and ws of a master endpoint, or is the master itself
// (half period `half` clocks) for a slave endpoint. It sends queued samples (towards an input) and
// receives samples (from an output) with the frame format of the endpoint.
struct I2sBfm {
  int slot, db, just, nc, mono_r, dup, wsinv, half; bool master;
  std::deque<uint64_t> q;
  Got got;
  int ll, off, frame;
  int bclk = 0, ws, sd = 0, pb = 0, pw, qf, wf, qr, wr, wok = 0, have_l = 0, locked_f = 1, locked_r = 1;
  bool started = false;
  uint64_t cur = 0, sh = 0, wl = 0, t = 0; int pos = 0;
  I2sBfm(int slot_, int db_, int just_, int nc_, int mono_r_, int dup_, int wsinv_, bool master_, int half_)
    : slot(slot_), db(db_), just(just_), nc(nc_), mono_r(mono_r_), dup(dup_), wsinv(wsinv_), half(half_), master(master_) {
    ll = ((just == 0) ^ wsinv) ? 0 : 1;
    off = just == 0 ? 1 : just == 1 ? 0 : slot - db;
    frame = 2 * slot;
    ws = ll; pw = ll; qf = qr = frame - 1; wf = wr = ll;
    // the endpoint and the codec both start a frame with the left channel when RUN is written
    got.slack = 32;
  }
  void push(uint64_t v) { q.push_back(v); }
  uint64_t m(int w) const { return bfm_mask(w); }
  // position of a bit period from the ws edges
  int next(int &qq, int &wp, int w, bool &edge) {
    edge = (w != wp);
    int n = edge ? (w == ll ? 0 : slot) : (qq + 1 >= frame ? 0 : qq + 1);
    qq = n; wp = w;
    return n;
  }
  void chk(int qn, int &ch, int &k) const {
    int qd = qn >= off ? qn - off : qn + frame - off;
    ch = qd >= slot; k = ch ? qd - slot : qd;
  }
  uint64_t word(uint64_t s, int ch) const {
    if (nc == 2) return (s >> (ch * db)) & m(db);
    return (ch ? (mono_r || dup) : (!mono_r || dup)) ? (s & m(db)) : 0;
  }
  void on_fall() {                     // drive the bit of the coming rising edge
    bool e; int qn = next(qf, wf, ws, e), ch, k;
    if (e) locked_f = 1;
    if (!locked_f) { sd = 0; return; }
    chk(qn, ch, k);
    if (!ch && k == 0) { if (!q.empty()) { cur = q.front(); q.pop_front(); } else cur = 0; }
    sd = k < db ? (int)((word(cur, ch) >> (db - 1 - k)) & 1) : 0;
  }
  void on_rise(int sdi) {              // sample the data of the output endpoint
    bool e; int qn = next(qr, wr, ws, e), ch, k;
    if (e) locked_r = 1;
    chk(qn, ch, k);
    if (k >= db) return;
    sh = ((sh << 1) | (uint64_t)sdi) & m(db);
    if (k == 0) wok = locked_r;
    if (k != db - 1) return;
    if (!wok) { if (!ch) have_l = 0; return; }
    if (!ch) { wl = sh; have_l = 1; }
    if (nc == 1 && ch == mono_r) got.d.push_back(sh);
    if (nc == 2 && ch && have_l) { got.d.push_back(wl | (sh << db)); have_l = 0; }
  }
  // inputs: the pins of the endpoint (bclk and ws when it is the master, its sd when it is an output)
  void step(uint64_t cyc, bool on, int bclk_i, int ws_i, int sd_i) {
    if (!on) return;
    if (!started) {                    // the bit of the first position is due before the first edge
      started = true; t = cyc + half; pb = bclk_i;
      if (master) {                    // lead-in: one right slot, so that the slave endpoint locks on the
        pos = slot; ws = !ll;          // ws edge of the first frame
        qf = slot - 1; wf = !ll; qr = slot - 1; wr = !ll;
      } else ws = ws_i;
      on_fall();
      return;
    }
    if (master) {                      // generate the clocks
      if (cyc < t) return;
      t = cyc + half;
      bclk = !bclk;
      if (!bclk) { pos = pos + 1 >= frame ? 0 : pos + 1; ws = pos < slot ? ll : !ll; on_fall(); }
      else on_rise(sd_i);
      return;
    }
    ws = ws_i;
    if (pb && !bclk_i) on_fall();
    if (!pb && bclk_i) on_rise(sd_i);
    pb = bclk_i;
  }
};

// ------------------------------------------------------------------ memory at the DMA port
struct MemBfm {
  std::unordered_map<uint32_t, uint32_t> m;
  bool busy = false, rdy = false; int lat = 0; uint32_t rdata = 0;
  uint64_t reads = 0, writes = 0;
  uint32_t rd32(uint32_t a) const { auto it = m.find(a >> 2); return it == m.end() ? 0xDEADBEEFu : it->second; }
  void wr8(uint32_t a, uint8_t b) {
    uint32_t w = rd32(a & ~3u), s = 8 * (a & 3);
    m[a >> 2] = (w & ~(0xFFu << s)) | ((uint32_t)b << s);
  }
  uint8_t rd8(uint32_t a) const { return (uint8_t)(rd32(a & ~3u) >> (8 * (a & 3))); }
  // returns ready; rdata in .rdata
  int step(int valid, uint32_t addr, uint32_t wdata, int wstrb) {
    if (rdy) { rdy = false; busy = false; return 0; }
    if (!busy && valid) { busy = true; lat = (int)(rnd() % 4); }
    if (busy) {
      if (lat-- > 0) return 0;
      if (wstrb) {
        uint32_t w = rd32(addr);
        for (int b = 0; b < 4; b++) if ((wstrb >> b) & 1) w = (w & ~(0xFFu << (8 * b))) | (wdata & (0xFFu << (8 * b)));
        m[addr >> 2] = w; writes++;
      } else { rdata = rd32(addr); reads++; }
      rdy = true;
      return 1;
    }
    return 0;
  }
  // samples <-> memory elements (containers of cb bytes, nc components, sign-extended or MSB-aligned)
  void put(uint32_t base, size_t k, uint64_t v, int w, int nc, int cb, bool sgn, bool msba) {
    for (int c = 0; c < nc; c++) {
      uint64_t comp = (v >> (c * w)) & bfm_mask(w);
      uint64_t x = sgn ? (uint64_t)bfm_sx(comp, w) : comp;
      if (msba) x = comp << (8 * cb - w);
      for (int b = 0; b < cb; b++) wr8(base + (uint32_t)(k * nc * cb + c * cb + b), (uint8_t)(x >> (8 * b)));
    }
  }
  bool get_check(uint32_t base, size_t k, uint64_t v, int w, int nc, int cb, bool sgn, bool msba, uint64_t &seen) {
    bool ok = true; seen = 0;
    for (int c = 0; c < nc; c++) {
      uint64_t comp = (v >> (c * w)) & bfm_mask(w);
      uint64_t x = sgn ? (uint64_t)bfm_sx(comp, w) : comp;
      if (msba) x = comp << (8 * cb - w);
      x &= bfm_mask(8 * cb);
      uint64_t g = 0;
      for (int b = 0; b < cb; b++) g |= (uint64_t)rd8(base + (uint32_t)(k * nc * cb + c * cb + b)) << (8 * b);
      ok = ok && g == x;
      seen |= (g & bfm_mask(w)) << (c * w);
    }
    return ok;
  }
};
