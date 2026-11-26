// grv_fir - FIR filters: fir_filter_xxx (decim M), interp_fir_filter_xxx (interp L),
// rational_resampler_xxx (L / M), and the GRC filter design blocks (low_pass_filter, ...).
//
// Output m uses the polyphase taps of phase l_m and the input samples up to n_m (GNU Radio):
//   y[m] = sum_j h[l_m + j*L] * x[n_m - j]      (x[k] = 0 for k < 0)
//   l_0 = 0, n_0 = 0 ; after each output: l += M, while l >= L: l -= L, n += 1
// Engines:
//   LANES = 0  parallel: delay line in registers, all TPP = ceil(NTAPS/L) taps in one clock,
//              pipelined adder tree, up to one output per clock
//   LANES > 0  folded: delay line in RAM (one copy per lane, two with SYM), LANES taps per
//              clock, ceil(TPP/LANES) + 7 clocks per output (ceil(NTAPS/2) work items with SYM)
//   SYM = 1    symmetric taps (L = 1): x[n-j] + x[n-(N-1-j)] pre-added, half the multipliers
// Taps: COEFS, tap k at [k*CW*NCC +: CW*NCC], {imag, real} for complex taps. The exact sum is
// resized (SHIFT, ROUND, SAT). The output is complex if the data or the taps are.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_fir #(
  parameter integer IW     = 16,
  parameter integer ICPLX  = 0,
  parameter integer CW     = 18,
  parameter integer CCPLX  = 0,
  parameter integer NTAPS  = 8,
  parameter [NTAPS*CW*(CCPLX+1)-1:0] COEFS = {NTAPS*CW*(CCPLX+1){1'b0}},
  parameter integer L      = 1,
  parameter integer M      = 1,
  parameter integer LANES  = 0,
  parameter integer SYM    = 0,
  parameter integer OW     = 16,
  parameter integer SHIFT  = 17,
  parameter integer ROUND  = 1,
  parameter integer SAT    = 1,
  parameter integer OREG   = 1
)(
  input  wire                                 clk,
  input  wire                                 rst_n,
  input  wire [IW*(ICPLX+1)-1:0]              s_tdata,
  input  wire                                 s_tvalid,
  output wire                                 s_tready,
  input  wire                                 s_tlast,
  output wire [OW*(((ICPLX|CCPLX)!=0)+1)-1:0] m_tdata,
  output wire                                 m_tvalid,
  input  wire                                 m_tready,
  output wire                                 m_tlast,
  output wire                                 ovf
);
  localparam integer NCI = ICPLX + 1;
  localparam integer NCC = CCPLX + 1;
  localparam integer OC  = ((ICPLX != 0) || (CCPLX != 0)) ? 1 : 0;
  localparam integer NCO = OC + 1;
  localparam integer TPP = (NTAPS + L - 1) / L;
  localparam integer SY  = ((SYM != 0) && (L == 1)) ? 1 : 0;
  localparam integer NPR = SY ? (NTAPS + 1) / 2 : TPP;           // products per output
  localparam integer XW  = IW + SY;                               // after the pre-adder
  localparam integer PW  = XW + CW + 1;                           // one (complex) product
  localparam integer GW  = IW + CW + $clog2(TPP + 1) + 3;         // exact sum
  localparam integer A   = M / L;
  localparam integer R   = M % L;
  localparam integer PHW = (L > 1) ? $clog2(L) : 1;

  function signed [CW-1:0] tap(input integer k, input integer im);
    begin
      if (k < NTAPS && (im == 0 || CCPLX != 0)) tap = COEFS[(k*NCC + im)*CW +: CW];
      else           tap = {CW{1'b0}};
    end
  endfunction

  // ------------------------------------------------ rate control
  reg  [31:0]    adv;          // inputs still needed before the next output
  reg  [PHW-1:0] ph;           // phase of the next output
  wire           eng_free;     // engine can start an output
  wire           room;         // delay line can take a sample
  assign s_tready = (adv != 0) && room;
  wire wr     = s_tvalid && s_tready;
  wire launch = eng_free && ((adv == 0) || (adv == 1 && wr));
  wire carry  = ({1'b0, ph} + R) >= L;
  always @(posedge clk) begin
    if (!rst_n) begin
      adv <= 32'd1;
      ph  <= {PHW{1'b0}};
    end else if (launch) begin
      adv <= A + carry;
      ph  <= carry ? ph + R - L : ph + R;
    end else if (wr) begin
      adv <= adv - 1'b1;
    end
  end
  reg last_in;                 // tlast of the newest sample
  always @(posedge clk) if (wr) last_in <= s_tlast;
  wire launch_last = wr ? s_tlast : last_in;

  wire [OW*NCO-1:0] res;
  wire              res_v, res_l, res_r;
  wire              res_ovf;

  genvar j, c;
  generate
    if (LANES == 0) begin : g_par
      // ============================================ parallel engine
      localparam integer TL = (NPR <= 1) ? 0 : (NPR <= 4) ? 1 : (NPR <= 16) ? 2 : (NPR <= 64) ? 3 :
                              (NPR <= 256) ? 4 : (NPR <= 1024) ? 5 : 6;
      localparam integer PL = TL + 2;          // products, tree levels, resize
      wire pce, pov;
      wire [PL:1] pv;
      // delay line d[0] = newest
      wire [IW*NCI-1:0] dl [0:TPP-1];
      wire [IW*NCI-1:0] sv [0:TPP-1];        // samples seen by a launch
      for (j = 0; j < TPP; j = j + 1) begin : g_d
        reg [IW*NCI-1:0] d;
        always @(posedge clk)
          if (!rst_n) d <= {IW*NCI{1'b0}};
          else if (wr) d <= (j == 0) ? s_tdata : dl[(j > 0) ? j - 1 : 0];
        assign dl[j] = d;
        assign sv[j] = wr ? ((j == 0) ? s_tdata : dl[(j > 0) ? j - 1 : 0]) : d;
      end
      // products, registered (stage 1)
      wire [GW*NPR-1:0] p_re, p_im;
      for (j = 0; j < NPR; j = j + 1) begin : g_p
        reg signed [GW-1:0] pr, pi;
        // operand j (pre-added for symmetric taps)
        wire signed [XW-1:0] ar, ai;
        if (SY) begin : g_sym
          localparam integer JB = NTAPS - 1 - j;
          wire signed [IW-1:0] xr_a = sv[j][0 +: IW];
          wire signed [IW-1:0] xi_a = sv[j][IW*ICPLX +: IW];
          wire signed [IW-1:0] xr_b = sv[JB][0 +: IW];
          wire signed [IW-1:0] xi_b = sv[JB][IW*ICPLX +: IW];
          assign ar = (JB == j) ? xr_a : xr_a + xr_b;
          assign ai = (JB == j) ? xi_a : xi_a + xi_b;
        end else begin : g_nsym
          assign ar = $signed(sv[j][0 +: IW]);
          assign ai = $signed(sv[j][IW*ICPLX +: IW]);
        end
        // taps of this product for every phase
        reg signed [CW-1:0] hr, hi;
        integer q;
        always @(*) begin
          hr = tap(j * L, 0);
          hi = (CCPLX != 0) ? tap(j * L, 1) : {CW{1'b0}};
          for (q = 1; q < L; q = q + 1)
            if (ph == q) begin
              hr = tap(q + j * L, 0);
              hi = (CCPLX != 0) ? tap(q + j * L, 1) : {CW{1'b0}};
            end
        end
        wire signed [PW-1:0] m_rr = ar * hr;
        wire signed [PW-1:0] m_ii = ai * hi;
        wire signed [PW-1:0] m_ri = ar * hi;
        wire signed [PW-1:0] m_ir = ai * hr;
        always @(posedge clk) if (pce) begin
          if (ICPLX != 0 && CCPLX != 0) begin pr <= m_rr - m_ii; pi <= m_ri + m_ir; end
          else if (ICPLX != 0)          begin pr <= m_rr;        pi <= m_ir; end
          else                          begin pr <= m_rr;        pi <= m_ri; end
        end
        assign p_re[j*GW +: GW] = pr;
        assign p_im[j*GW +: GW] = pi;
      end
      // adder tree: TL registered levels of 4-input adders after the product stage
      wire [GW-1:0] s_re, s_im;
      grv_fir_tree #(.GW(GW), .N(NPR), .LV(TL)) u_tre (.clk(clk), .ce(pce), .x(p_re), .y(s_re));
      grv_fir_tree #(.GW(GW), .N(NPR), .LV(TL)) u_tim (.clk(clk), .ce(pce), .x(p_im), .y(s_im));
      grv_pctl #(.L(PL)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(launch), .out_ready(res_r), .ce(pce), .out_valid(pov), .v(pv));
      assign eng_free = pce;
      assign room = 1'b1;
      reg [PL-1:0] lp;
      always @(posedge clk) if (pce) lp <= {lp[PL-2:0], launch_last};
      wire [OW-1:0] rr, ri;
      wire          ovr, ovi;
      grv_resize #(.GW(GW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_rr (.x(s_re), .y(rr), .ovf(ovr));
      grv_resize #(.GW(GW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_ri (.x(s_im), .y(ri), .ovf(ovi));
      reg [OW*NCO-1:0] ro;
      reg              rl, rov;
      always @(posedge clk) if (pce) begin
        ro  <= OC ? {ri, rr} : rr;
        rl  <= lp[PL-2];
        rov <= pv[PL-1] & (ovr | (ovi & (OC != 0)));
      end
      assign res = ro;
      assign res_v = pov;
      assign res_l = rl;
      assign res_ovf = rov & pce & pv[PL];
    end else begin : g_fold
      // ============================================ folded engine
      localparam integer NW   = SY ? (NTAPS + 1) / 2 : TPP;     // work items per output
      localparam integer P    = (NW + LANES - 1) / LANES;       // clocks of address issue
      localparam integer DEP0 = TPP + A + 3;
      localparam integer AW   = (DEP0 > 2) ? $clog2(DEP0) : 1;
      localparam integer DEP  = 1 << AW;
      localparam integer CAW  = $clog2(L * TPP + 1);
      localparam integer PCW  = $clog2(P + 1);
      localparam [2:0] S_IDLE = 3'd0, S_RUN = 3'd1, S_DRAIN = 3'd2, S_SUM = 3'd3, S_OUT = 3'd4;
      reg [2:0]      st;
      reg [AW-1:0]   wp;              // next write address
      reg [AW-1:0]   base;            // address of x[n_m]
      reg [31:0]     nwr;             // samples written, saturating
      reg [31:0]     nb;              // samples available at launch
      reg [PHW-1:0]  lph;
      reg [PCW-1:0]  cyc;
      reg [3:0]      dr;
      reg            ll;
      reg [OW*NCO-1:0] ro;
      reg            rov;
      reg            ovr_q;
      assign eng_free = (st == S_IDLE);
      assign room = 1'b1;              // depth covers TPP + A + 2 samples
      always @(posedge clk) begin
        if (!rst_n) begin
          wp <= 0; nwr <= 32'd0;
        end else if (wr) begin
          wp <= wp + 1'b1;
          if (nwr < NTAPS) nwr <= nwr + 1'b1;
        end
      end
      // per-lane memories, pipelines and accumulators
      wire [GW*LANES-1:0] acc_re, acc_im;
      reg  issue_q1, issue_q2, issue_q3;   // address issued 1/2/3 clocks ago
      for (j = 0; j < LANES; j = j + 1) begin : g_lane
        reg [IW*NCI-1:0] mem_a [0:DEP-1];
        reg [IW*NCI-1:0] mem_b [0:DEP-1];
        reg signed [CW*NCC-1:0] crom [0:L*TPP-1];
        integer q, k;
        initial for (q = 0; q < L; q = q + 1) for (k = 0; k < TPP; k = k + 1)
          crom[q*TPP + k] = {tap(q + k*L, 1), tap(q + k*L, 0)};
        always @(posedge clk) if (wr) begin
          mem_a[wp] <= s_tdata;
          if (SY) mem_b[wp] <= s_tdata;
        end
        // work item w of this lane in this clock
        wire [31:0] w   = cyc * LANES + j;
        wire        wok = (st == S_RUN) && (w < NW);
        wire [31:0] ja  = w;                         // newer sample index offset
        wire [31:0] jb  = NTAPS - 1 - w;             // older partner (SYM)
        wire        va  = wok && (ja < nb);
        wire        vb  = wok && SY && (jb < nb) && (jb != ja);
        wire [AW-1:0] adr_a = base - ja[AW-1:0];
        wire [AW-1:0] adr_b = base - jb[AW-1:0];
        wire [CAW-1:0] cadr = SY ? w[CAW-1:0] : (lph * TPP + w);
        // stage q1: memory and coefficient reads
        reg [IW*NCI-1:0] xa1, xb1;
        reg              va1, vb1;
        reg [CW*NCC-1:0] h1;
        always @(posedge clk) begin
          xa1 <= mem_a[adr_a];
          xb1 <= mem_b[adr_b];
          h1  <= crom[(cadr < L * TPP) ? cadr : 0];
          va1 <= va;
          vb1 <= vb;
        end
        // stage q2: pre-add
        reg signed [XW-1:0] or2, oi2;
        reg [CW*NCC-1:0]    h2;
        wire signed [IW-1:0] ar = va1 ? $signed(xa1[0 +: IW]) : $signed({IW{1'b0}});
        wire signed [IW-1:0] ai = va1 ? $signed(xa1[IW*ICPLX +: IW]) : $signed({IW{1'b0}});
        wire signed [IW-1:0] br = vb1 ? $signed(xb1[0 +: IW]) : $signed({IW{1'b0}});
        wire signed [IW-1:0] bi = vb1 ? $signed(xb1[IW*ICPLX +: IW]) : $signed({IW{1'b0}});
        always @(posedge clk) begin
          or2 <= ar + br;
          oi2 <= (ICPLX != 0) ? ai + bi : $signed({XW{1'b0}});
          h2  <= h1;
        end
        // stage q3: products
        wire signed [CW-1:0] hr = h2[0 +: CW];
        wire [CW*(CCPLX+1)+CW-1:0] h2x = {{CW{1'b0}}, h2};
        wire signed [CW-1:0] hi = (CCPLX != 0) ? h2x[CW +: CW] : {CW{1'b0}};
        reg  signed [PW-1:0] m_rr, m_ii, m_ri, m_ir;
        always @(posedge clk) begin
          m_rr <= or2 * hr;
          m_ii <= oi2 * hi;
          m_ri <= or2 * hi;
          m_ir <= oi2 * hr;
        end
        // stage q4: accumulate
        reg signed [GW-1:0] are, aim;
        always @(posedge clk) begin
          if (st == S_IDLE) begin
            are <= {GW{1'b0}};
            aim <= {GW{1'b0}};
          end else if (issue_q3) begin
            if (ICPLX != 0 && CCPLX != 0) begin are <= are + m_rr - m_ii; aim <= aim + m_ri + m_ir; end
            else if (ICPLX != 0)          begin are <= are + m_rr;        aim <= aim + m_ir; end
            else                          begin are <= are + m_rr;        aim <= aim + m_ri; end
          end
        end
        assign acc_re[j*GW +: GW] = are;
        assign acc_im[j*GW +: GW] = aim;
      end
      // sum of the lanes
      reg signed [GW-1:0] tre, tim;
      integer t;
      always @(*) begin
        tre = {GW{1'b0}};
        tim = {GW{1'b0}};
        for (t = 0; t < LANES; t = t + 1) begin
          tre = tre + $signed(acc_re[t*GW +: GW]);
          tim = tim + $signed(acc_im[t*GW +: GW]);
        end
      end
      wire [OW-1:0] rr, ri;
      wire          ovr, ovi;
      grv_resize #(.GW(GW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_rr (.x(tre), .y(rr), .ovf(ovr));
      grv_resize #(.GW(GW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_ri (.x(tim), .y(ri), .ovf(ovi));
      always @(posedge clk) begin
        issue_q1 <= (st == S_RUN);
        issue_q2 <= issue_q1;
        issue_q3 <= issue_q2;
        rov <= 1'b0;
        if (!rst_n) begin
          st <= S_IDLE;
        end else case (st)
          S_IDLE: if (launch) begin
            base <= wr ? wp : wp - 1'b1;
            nb   <= (wr && nwr < NTAPS) ? nwr + 1'b1 : nwr;
            lph  <= ph;
            ll   <= launch_last;
            cyc  <= 0;
            st   <= S_RUN;
          end
          S_RUN: begin
            if (cyc == P - 1) begin st <= S_DRAIN; dr <= 4'd0; end
            cyc <= cyc + 1'b1;
          end
          S_DRAIN: begin
            dr <= dr + 1'b1;
            if (dr == 4'd3) st <= S_SUM;
          end
          S_SUM: begin
            ro  <= OC ? {ri, rr} : rr;
            rov <= ovr | (ovi & (OC != 0));
            st  <= S_OUT;
          end
          default: if (res_r) st <= S_IDLE;
        endcase
      end
      assign res = ro;
      assign res_v = (st == S_OUT);
      assign res_l = ll;
      assign res_ovf = rov;
    end
  endgenerate

  assign ovf = res_ovf;
  grv_oreg #(.W(OW*NCO), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(res), .s_tvalid(res_v), .s_tready(res_r),
    .s_tlast(res_l), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

// grv_fir_tree - pipelined adder tree: LV registered levels of 4-input adders (clocked by ce)
module grv_fir_tree #(
  parameter integer GW = 32,
  parameter integer N  = 8,
  parameter integer LV = 2
)(
  input  wire            clk,
  input  wire            ce,
  input  wire [GW*N-1:0] x,
  output wire [GW-1:0]   y
);
  generate
    if (LV == 0) begin : g_end
      assign y = x[GW-1:0];
    end else begin : g_lvl
      localparam integer NN = (N + 3) / 4;
      wire [GW*NN-1:0] s;
      genvar i;
      for (i = 0; i < NN; i = i + 1) begin : g_n
        reg signed [GW-1:0] sum, a;
        integer k;
        always @(*) begin
          sum = {GW{1'b0}};
          for (k = 0; k < 4; k = k + 1)
            if (4 * i + k < N) sum = sum + $signed(x[(4*i + k)*GW +: GW]);
        end
        always @(posedge clk) if (ce) a <= sum;
        assign s[i*GW +: GW] = a;
      end
      grv_fir_tree #(.GW(GW), .N(NN), .LV(LV - 1)) u_n (.clk(clk), .ce(ce), .x(s), .y(y));
    end
  endgenerate
endmodule

`default_nettype wire
