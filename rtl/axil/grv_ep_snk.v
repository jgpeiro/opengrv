// grv_ep_snk - AXI4-Lite sink endpoint (design document 8.7). STREAM mode: FIFO read by the CPU,
// back-pressure or (CTRL.DROP) drop when full. CAPTURE mode: never back-pressures; after ARM the
// trigger starts a capture of CAPLEN samples (PRE of them from before the trigger) into the
// capture buffer, which is read through DATA (in order from TRIG_POS) or the capture window.
//   0x00 DATA R   pop (STREAM, 2 or 4 packed samples with PACK) / next captured sample
//   0x04 DATA_HI  bits [W-1:32] of the last sample read
//   0x08 STATUS   [15:0] LEVEL [16] EMPTY [17] FULL [18] OVF [19] UNF [20] TIMEOUT [21] DONE
//                 [22] ARMED [23] TRIGGERED [24] IRQ   (W1C 18 .. 21)
//   0x0C CTRL     [0] EN [1] FLUSH [2] WAIT [3] PACK [4] IRQ_EN [5] DROP [7:6] MODE (0 STREAM,
//                 1 CAPTURE) [8] ARM [11:9] TRIG (0 now, 1 rising, 2 falling, 4 after tlast) [12] TRIG_Q
//   0x10 THRESH   interrupt while LEVEL >= THRESH (STREAM)
//   0x14 CAPLEN   [15:0] samples, [31:16] PRE
//   0x18 COUNT    samples received
//   0x1C INFO     as grv_ep_src, [27:24] log2 of the capture buffer
//   0x20 TRIG_LEVEL ; 0x24 DECIM (keep 1 in DECIM + 1) ; 0x28 TRIG_POS
//   0x40 .. 0x7C  aliases of DATA ; capture window: 0x8000 + 0x2000 k + 4 i (sample i, raw)
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_ep_snk #(
  parameter integer W      = 32,
  parameter integer CW     = 16,
  parameter integer NC     = 2,
  parameter integer SIGNED = 1,
  parameter integer FRAC   = 15,
  parameter integer DEPTH  = 512,
  parameter integer CAPD   = 0,
  parameter integer MODE0  = 0,
  parameter integer CAPLEN0 = 0
)(
  input  wire         clk,
  input  wire         rst_n,
  // register bus
  input  wire [15:0]  rb_addr,
  input  wire [31:0]  rb_wdata,
  input  wire         rb_we,
  input  wire         rb_re,
  input  wire         rb_force,
  input  wire         rb_sel,
  output wire         t_wrdy,
  output wire         t_rrdy,
  output reg  [31:0]  t_rdata,
  output wire         irq,
  // stream
  input  wire [W-1:0] s_tdata,
  input  wire         s_tvalid,
  output wire         s_tready,
  input  wire         s_tlast
);
  localparam integer AW  = $clog2(DEPTH);
  localparam integer CD  = (CAPD > 0) ? CAPD : 2;
  localparam integer CAW = $clog2(CD);
  localparam integer PK  = (W <= 8) ? 4 : (W <= 16) ? 2 : 1;
  localparam integer SW  = (PK == 4) ? 8 : (PK == 2) ? 16 : 32;

  reg  [31:0] ctrl, thresh, caplen, count, tlevel, decim;
  reg         f_ovf, f_unf, f_tmo, f_done, armed, trig;
  reg  [31:0] dc;
  wire        en     = ctrl[0];
  wire        pack   = ctrl[3] && (PK > 1);
  wire        drop   = ctrl[5];
  wire        capm   = (ctrl[7:6] == 2'd1) && (CAPD > 0);
  wire        keep   = (dc == 0);
  // ---------------- stream FIFO
  wire [W-1:0] f_d;
  wire         f_v, f_r, f_l;
  wire [AW+1:0] f_lvl;
  wire         f_in_v;
  wire         f_in_r;
  assign f_in_v   = s_tvalid && en && !capm && keep;
  assign s_tready = capm || !en || !keep || drop || f_in_r;
  grv_fifo #(.W(W), .DEPTH(DEPTH)) u_f (.clk(clk), .rst_n(rst_n && !(rb_sel && rb_we && rb_addr[7:0] == 8'h0C && rb_wdata[1])),
    .s_tdata(s_tdata), .s_tvalid(f_in_v), .s_tready(f_in_r), .s_tlast(s_tlast),
    .m_tdata(f_d), .m_tvalid(f_v), .m_tready(f_r), .m_tlast(f_l), .level(f_lvl));
  wire [W+31:0] f_dx = {32'd0, f_d};      // f_d padded for the packing selects (any W)
  // pack gatherer
  reg  [31:0] g;
  reg  [2:0]  gc;
  wire        gfull = (gc == PK);
  wire        gtake = pack && !gfull && f_v;
  // ---------------- register bus
  wire [7:0]  ra   = rb_addr[7:0];
  wire        win  = rb_addr[15];
  wire        is_data = !win && ((ra == 8'h00) || (ra >= 8'h40 && ra <= 8'h7C));
  wire        rdat = rb_sel && rb_re && is_data;
  wire [31:0] level = capm ? caplen[15:0] - rdi : (f_lvl + (pack ? gc : 0));
  wire        avail = capm ? f_done : (pack ? gfull : f_v);
  assign t_wrdy = 1'b1;
  assign t_rrdy = !is_data || !ctrl[2] || avail;
  wire        pop1  = rdat && !capm && !pack && f_v;
  assign f_r = pop1 || gtake;
  assign irq = ctrl[4] && (capm ? f_done : (level >= thresh && thresh != 0));
  reg  [31:0] hi;
  // ---------------- capture
  reg  [W:0]  cbuf [0:CD-1];
  reg  [CAW-1:0] cp, tpos;
  reg  [31:0] pre_n, post_n;
  reg  [W-1:0] prev;
  reg          prev_v, prev_l;
  reg  [15:0]  rdi;
  wire [15:0]  pre   = caplen[31:16];
  wire signed [CW-1:0] tv = ctrl[12] ? s_tdata[CW*(NC-1) +: CW] : s_tdata[0 +: CW];
  wire signed [CW-1:0] pvv = ctrl[12] ? prev[CW*(NC-1) +: CW] : prev[0 +: CW];
  wire signed [CW-1:0] lv = tlevel[CW-1:0];
  reg  tcond;
  always @(*) case (ctrl[11:9])
    3'd0: tcond = 1'b1;
    3'd1: tcond = prev_v && (pvv < lv) && (tv >= lv);
    3'd2: tcond = prev_v && (pvv >= lv) && (tv < lv);
    3'd4: tcond = prev_v && prev_l;
    default: tcond = 1'b0;
  endcase
  wire c_in = capm && armed && s_tvalid && keep;
  wire fire = c_in && !trig && tcond;
  wire [31:0] pre_av = (pre_n < pre) ? pre_n : pre;
  always @(posedge clk) if (c_in) cbuf[cp] <= {s_tlast, s_tdata};
  reg [W:0] crd;
  wire [CAW-1:0] cra = win ? rb_addr[CAW+1:2] : (tpos + rdi[CAW-1:0]);
  always @(posedge clk) if (rb_sel && rb_re) crd <= cbuf[cra];
  reg rd_cap, rd_hi;

  always @(posedge clk) begin
    if (!rst_n) begin
      ctrl <= {24'd0, MODE0[1:0], 6'd0}; thresh <= 32'd0; caplen <= CAPLEN0; count <= 32'd0; tlevel <= 32'd0;
      decim <= 32'd0; f_ovf <= 1'b0; f_unf <= 1'b0; f_tmo <= 1'b0; f_done <= 1'b0; armed <= 1'b0; trig <= 1'b0;
      dc <= 32'd0; gc <= 0; g <= 32'd0; cp <= 0; tpos <= 0; pre_n <= 32'd0; post_n <= 32'd0; prev_v <= 1'b0;
      rdi <= 16'd0;
    end else begin
      // decimation and counters
      if (s_tvalid && s_tready) begin
        count <= count + 1'b1;
        dc <= (dc >= decim) ? 32'd0 : dc + 1'b1;
        if (!capm && en && keep && !f_in_r && drop) f_ovf <= 1'b1;
      end
      // pack gatherer
      if (gtake) begin
        g  <= g | ({{(32-SW){1'b0}}, f_dx[SW-1:0]} << (SW * gc));
        gc <= gc + 1'b1;
      end
      // capture
      if (c_in) begin
        cp <= cp + 1'b1;
        prev <= s_tdata; prev_v <= 1'b1; prev_l <= s_tlast;
        if (!trig) begin
          if (fire) begin
            trig   <= 1'b1;
            tpos   <= cp - pre_av[CAW-1:0];
            post_n <= 32'd1;
            if (pre_av + 1 >= caplen[15:0]) begin armed <= 1'b0; f_done <= 1'b1; end
          end else if (pre_n < pre) pre_n <= pre_n + 1'b1;
        end else begin
          post_n <= post_n + 1'b1;
          if (pre_av + post_n + 1 >= caplen[15:0]) begin armed <= 1'b0; f_done <= 1'b1; end
        end
      end
      // reads
      if (rdat) begin
        if (capm) begin
          rdi <= rdi + 1'b1;
        end else if (pack) begin
          if (gfull) begin g <= 32'd0; gc <= 0; end
          else f_unf <= 1'b1;
        end else if (!f_v) f_unf <= 1'b1;
        if (rb_force && !avail) f_tmo <= 1'b1;
      end
      // writes
      if (rb_sel && rb_we && !win) case (ra)
        8'h08: begin
          if (rb_wdata[18]) f_ovf <= 1'b0;
          if (rb_wdata[19]) f_unf <= 1'b0;
          if (rb_wdata[20]) f_tmo <= 1'b0;
          if (rb_wdata[21]) f_done <= 1'b0;
        end
        8'h0C: begin
          ctrl <= rb_wdata & 32'h0000_1EFD;
          if (rb_wdata[1]) begin g <= 32'd0; gc <= 0; end
          if (rb_wdata[8]) begin
            armed <= 1'b1; trig <= 1'b0; f_done <= 1'b0; pre_n <= 32'd0; post_n <= 32'd0;
            prev_v <= 1'b0; rdi <= 16'd0;
          end
        end
        8'h10: thresh <= rb_wdata;
        8'h14: caplen <= rb_wdata;
        8'h20: tlevel <= rb_wdata;
        8'h24: begin decim <= rb_wdata; dc <= 32'd0; end
        default: ;
      endcase
    end
  end

  // read data: registers are registered at the strobe; DATA from the FIFO head, the gatherer or
  // the capture buffer (block RAM, registered above)
  reg [31:0] rq;
  wire [63:0] fext = {{(64-W){1'b0}}, f_d};
  wire [31:0] fhi  = fext[63:32];
  reg [W-1:0] dsel;
  wire [31:0] info = {4'd0, CAW[3:0], 3'd0, (W > 32), AW[3:0], 2'd0, FRAC[5:0], SIGNED[0], (NC == 2), CW[5:0]};
  function [31:0] sx(input [W-1:0] v);
    reg [W+63:0] z, s;
    begin
      z = {64'd0, v};
      s = {{64{v[W-1]}}, v};
      sx = (W < 32 && SIGNED != 0 && NC == 1) ? s[31:0] : z[31:0];
    end
  endfunction
  always @(posedge clk) begin
    if (rb_sel && rb_re) begin
      rd_cap <= win || (is_data && capm);
      if (is_data && !capm) begin
        rq <= pack ? g : (f_v ? sx(f_d) : 32'd0);
        if (!pack && f_v) hi <= fhi;
      end else case (ra)
        8'h04: rq <= hi;
        8'h08: rq <= {7'd0, irq, trig, armed, f_done, f_tmo, f_unf, f_ovf, (f_lvl == DEPTH + 1), (level == 0), level[15:0]};
        8'h0C: rq <= ctrl;
        8'h10: rq <= thresh;
        8'h14: rq <= caplen;
        8'h18: rq <= count;
        8'h1C: rq <= info;
        8'h20: rq <= tlevel;
        8'h24: rq <= decim;
        8'h28: rq <= {{(32-CAW){1'b0}}, tpos};
        default: rq <= 32'd0;
      endcase
    end
  end
  always @(*) begin
    t_rdata = rd_cap ? sx(crd[W-1:0]) : rq;
  end
endmodule

`default_nettype wire
