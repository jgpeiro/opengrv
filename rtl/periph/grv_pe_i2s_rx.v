// grv_pe_i2s_rx - I2S receiver endpoint, master or slave (design document, section 9.4). A stereo
// stream is complex (I = left, Q = right), a mono stream real (FORMAT.MONO_R: the right channel).
// Each channel word is DBITS bits, most significant first, in a slot of SLOT bits:
//   JUST 0 I2S             MSB one bclk after the ws edge, ws low = left
//   JUST 1 left-justified  MSB at the ws edge, ws high = left
//   JUST 2 right-justified LSB at the end of the slot, ws high = left
// FORMAT.WSINV swaps the ws levels. Data are sampled on the rising edge of bclk. Master (ROLE 0):
// bclk, ws and mclk come from grv_i2s_clk; slave (ROLE 1): bclk_i and ws_i come from the outside,
// at most clk / 8. Either way bclk, ws and sd pass through the same synchronisers, so the timing
// is the same. A slave locks at the first ws edge; ws edges at the wrong bit position count errors.
//   FORMAT [4:0] SLOT - 1 [9:8] JUST [10] MONO_R [13] WSINV [16] MCLKO
//   TIMING half period of bclk (master), 24.8 clocks;  K0 [7:0] MDIV: mclk half period - 1 clocks
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_pe_i2s_rx #(
  parameter integer DBITS   = 16,
  parameter integer NC      = 2,
  parameter integer SIGNED  = 1,
  parameter integer FRAC    = 15,
  parameter integer DEPTH   = 32,
  parameter integer ROLE    = 0,          // 0 master, 1 slave
  parameter [31:0]  CTRL0   = 32'h1,
  parameter [31:0]  TIMING0 = 32'd0,
  parameter [31:0]  FORMAT0 = 32'h0000_001F,
  parameter [31:0]  THRESH0 = 32'd1,
  parameter [31:0]  MCLK0   = 32'd0
)(
  input  wire                clk,
  input  wire                rst_n,
  input  wire                run,
  input  wire [15:0]         rb_addr,
  input  wire [31:0]         rb_wdata,
  input  wire                rb_we,
  input  wire                rb_re,
  input  wire                rb_sel,
  output wire                t_wrdy,
  output wire                t_rrdy,
  output wire [31:0]         t_rdata,
  output wire                irq,
  output wire [DBITS*NC-1:0] m_tdata,
  output wire                m_tvalid,
  input  wire                m_tready,
  output wire                m_tlast,
  output wire                bclk_o,
  output wire                ws_o,
  output wire                mclk_o,
  input  wire                bclk_i,
  input  wire                ws_i,
  input  wire                sd_i
);
  localparam integer W  = DBITS * NC;
  localparam integer AW = $clog2(DEPTH);
  localparam [31:0] INFO = {2'd0, DBITS[4:0] - 5'd1, 1'b0, 4'd5, AW[3:0], 2'd0, FRAC[5:0], SIGNED[0], (NC == 2), DBITS[5:0]};

  wire [31:0] ctrl, thresh, timing, format, k0, k1, k2, k3;
  wire        flush;
  wire [15:0] level;
  wire        en = ctrl[0] && run;
  wire [5:0]  slot = {1'b0, format[4:0]} + 6'd1;
  wire [1:0]  just = format[9:8];
  wire        mono_r = format[10];
  wire        left_lvl = (just == 2'd0) ^ format[13] ? 1'b0 : 1'b1;

  reg  [W-1:0] p_data;
  reg          p_push, ev_err;
  wire         f_ready, f_valid;
  wire [W-1:0] f_data;
  grv_fifo_fl #(.W(W), .DEPTH(DEPTH)) u_fifo (.clk(clk), .rst_n(rst_n), .flush(flush),
    .s_data(p_data), .s_valid(p_push), .s_ready(f_ready),
    .m_data(f_data), .m_valid(f_valid), .m_ready(m_tready && en), .level(level));
  assign m_tdata  = f_data;
  assign m_tlast  = 1'b0;
  assign m_tvalid = f_valid && en;

  grv_pe_regs #(.DIR(0), .INFO(INFO), .CTRL0(CTRL0), .THRESH0(THRESH0), .TIMING0(TIMING0), .FORMAT0(FORMAT0),
                .K00(MCLK0))
  u_regs (.clk(clk), .rst_n(rst_n), .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re),
    .rb_sel(rb_sel), .t_wrdy(t_wrdy), .t_rrdy(t_rrdy), .t_rdata(t_rdata), .irq(irq),
    .ctrl(ctrl), .thresh(thresh), .timing(timing), .format(format), .k0(k0), .k1(k1), .k2(k2), .k3(k3),
    .flush(flush), .level(level), .full(!f_ready), .busy(en), .ev_xfer(m_tvalid && m_tready),
    .ev_ovf(p_push && !f_ready), .ev_unf(1'b0), .ev_err(ev_err));

  // clocks: generated (master) or from the pins (slave); the same synchronisers either way
  wire mb, mw;
  generate if (ROLE == 0) begin : g_master
    grv_i2s_clk u_clk (.clk(clk), .rst_n(rst_n), .en(en), .timing(timing), .slot(slot), .left_lvl(left_lvl),
      .mclko(format[16]), .mdiv(k0[7:0]), .bclk_o(mb), .ws_o(mw), .mclk_o(mclk_o));
  end else begin : g_slave
    assign mb = 1'b0;
    assign mw = 1'b0;
    assign mclk_o = 1'b0;
  end endgenerate
  assign bclk_o = mb;
  assign ws_o   = mw;
  wire bs, wss, sds;
  grv_sync #(.N(3)) u_sync (.clk(clk), .rst_n(rst_n),
    .d({ROLE == 0 ? mb : bclk_i, ROLE == 0 ? mw : ws_i, sd_i}), .q({bs, wss, sds}));

  // bit position in the frame at each rising edge of bclk
  reg         bs_d, wsp, locked, seen, have_l, wok;
  reg  [6:0]  q;
  reg  [DBITS-1:0] sh, wl;
  wire        rise = bs && !bs_d;
  wire [6:0]  frame = {slot, 1'b0};
  wire        wedge = (wss != wsp);
  wire [6:0]  qn = wedge ? ((wss == left_lvl) ? 7'd0 : {1'b0, slot}) : ((q + 7'd1 >= frame) ? 7'd0 : q + 7'd1);
  wire [6:0]  off = (just == 2'd0) ? 7'd1 : (just == 2'd1) ? 7'd0 : {1'b0, slot} - DBITS[6:0];
  wire [6:0]  qd = (qn >= off) ? qn - off : qn + frame - off;      // position relative to the left MSB
  wire        ch = (qd >= {1'b0, slot});
  wire [6:0]  k  = ch ? qd - {1'b0, slot} : qd;
  wire        exp_edge = (q + 7'd1 == ((wss == left_lvl) ? frame : {1'b0, slot}));
  wire [DBITS-1:0]   word = {sh[DBITS-2:0], sds};
  wire [2*DBITS-1:0] pv = (NC == 1) ? {word, word} : {word, wl};
  always @(posedge clk) begin
    p_push <= 1'b0; ev_err <= 1'b0;
    bs_d <= bs;
    if (!rst_n || flush || !en) begin
      q <= frame - 7'd1; wsp <= left_lvl; locked <= (ROLE == 0); seen <= (ROLE == 0); have_l <= 1'b0; wok <= 1'b0;
      sh <= {DBITS{1'b0}}; wl <= {DBITS{1'b0}};
    end else if (rise && !seen) begin
      seen <= 1'b1; wsp <= wss;                     // slave: the reference level of ws, no edge yet
    end else if (rise) begin
      q <= qn; wsp <= wss;
      if (wedge) begin
        locked <= 1'b1;
        if (locked && !exp_edge) ev_err <= 1'b1;
      end
      if (k < DBITS) begin
        sh <= {sh[DBITS-2:0], sds};
        if (k == 7'd0) wok <= locked || wedge;          // a word counts only if it started after the lock
        if (k == DBITS - 1 && wok) begin
          if (!ch) begin wl <= word; have_l <= 1'b1; end
          if ((NC == 1 && ch == mono_r) || (NC == 2 && ch && have_l)) begin
            p_data <= pv[W-1:0]; p_push <= 1'b1; have_l <= 1'b0;
          end
        end else if (k == DBITS - 1 && !ch)
          have_l <= 1'b0;
      end
    end
  end
endmodule

`default_nettype wire
