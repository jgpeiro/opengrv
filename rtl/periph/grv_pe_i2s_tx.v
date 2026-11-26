// grv_pe_i2s_tx - I2S transmitter endpoint, master or slave (design document, section 9.4). The frame
// format is the one of grv_pe_i2s_rx. A stereo stream is complex (I = left, Q = right); a mono stream
// goes to the left channel (FORMAT.MONO_R: the right one), and the other channel carries 0 or, with
// FORMAT.DUP, the same sample. sd_o changes after the falling edge of bclk. A new sample is taken when
// the left MSB is due; an empty FIFO counts an underflow and sends the last sample again (CTRL.REPEAT)
// or 0. The I2S frame rate paces the stream: the master's from TIMING, the slave's from its master.
//   FORMAT [4:0] SLOT - 1 [9:8] JUST [10] MONO_R [11] DUP [13] WSINV [16] MCLKO
//   TIMING half period of bclk (master), 24.8 clocks;  K0 [7:0] MDIV: mclk half period - 1 clocks
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_pe_i2s_tx #(
  parameter integer DBITS   = 16,
  parameter integer NC      = 2,
  parameter integer SIGNED  = 1,
  parameter integer FRAC    = 15,
  parameter integer DEPTH   = 32,
  parameter integer ROLE    = 0,          // 0 master, 1 slave
  parameter [31:0]  CTRL0   = 32'h1,
  parameter [31:0]  TIMING0 = 32'd0,
  parameter [31:0]  FORMAT0 = 32'h0000_001F,
  parameter [31:0]  THRESH0 = 32'd0,
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
  input  wire [DBITS*NC-1:0] s_tdata,
  input  wire                s_tvalid,
  output wire                s_tready,
  input  wire                s_tlast,
  output wire                bclk_o,
  output wire                ws_o,
  output wire                mclk_o,
  input  wire                bclk_i,
  input  wire                ws_i,
  output reg                 sd_o
);
  localparam integer W  = DBITS * NC;
  localparam integer AW = $clog2(DEPTH);
  localparam [31:0] INFO = {2'd0, DBITS[4:0] - 5'd1, 1'b1, 4'd5, AW[3:0], 2'd0, FRAC[5:0], SIGNED[0], (NC == 2), DBITS[5:0]};

  wire [31:0] ctrl, thresh, timing, format, k0, k1, k2, k3;
  wire        flush;
  wire [15:0] level;
  wire        en = ctrl[0] && run;
  wire [5:0]  slot = {1'b0, format[4:0]} + 6'd1;
  wire [1:0]  just = format[9:8];
  wire        mono_r = format[10], dup = format[11];
  wire        left_lvl = (just == 2'd0) ^ format[13] ? 1'b0 : 1'b1;

  wire         f_ready, f_valid;
  wire [W-1:0] f_data;
  reg          f_pop, ev_unf;
  assign s_tready = f_ready || ctrl[3];
  grv_fifo_fl #(.W(W), .DEPTH(DEPTH)) u_fifo (.clk(clk), .rst_n(rst_n), .flush(flush),
    .s_data(s_tdata), .s_valid(s_tvalid && f_ready), .s_ready(f_ready),
    .m_data(f_data), .m_valid(f_valid), .m_ready(f_pop), .level(level));

  grv_pe_regs #(.DIR(1), .INFO(INFO), .CTRL0(CTRL0), .THRESH0(THRESH0), .TIMING0(TIMING0), .FORMAT0(FORMAT0),
                .K00(MCLK0))
  u_regs (.clk(clk), .rst_n(rst_n), .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re),
    .rb_sel(rb_sel), .t_wrdy(t_wrdy), .t_rrdy(t_rrdy), .t_rdata(t_rdata), .irq(irq),
    .ctrl(ctrl), .thresh(thresh), .timing(timing), .format(format), .k0(k0), .k1(k1), .k2(k2), .k3(k3),
    .flush(flush), .level(level), .full(!f_ready), .busy(en), .ev_xfer(f_pop),
    .ev_ovf(s_tvalid && !f_ready && ctrl[3]), .ev_unf(ev_unf), .ev_err(1'b0));

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
  wire bs, wss;
  grv_sync #(.N(2)) u_sync (.clk(clk), .rst_n(rst_n),
    .d({ROLE == 0 ? mb : bclk_i, ROLE == 0 ? mw : ws_i}), .q({bs, wss}));

  // at each falling edge of bclk: the bit position of the next rising edge, and its bit
  reg          bs_d, wsp, locked, seen, en_d;
  reg  [6:0]   q;
  reg  [W-1:0] cur;
  // master: the first bit is due before the first edge of bclk, at position 0 (ws at the left level)
  wire         vfall = (ROLE == 0) && en && !en_d;
  wire         fall = (!bs && bs_d) || vfall;
  wire [6:0]   frame = {slot, 1'b0};
  wire         wedge = (wss != wsp) && !vfall;
  wire [6:0]   qn = vfall ? 7'd0 : wedge ? ((wss == left_lvl) ? 7'd0 : {1'b0, slot}) :
                    ((q + 7'd1 >= frame) ? 7'd0 : q + 7'd1);
  wire [6:0]   off = (just == 2'd0) ? 7'd1 : (just == 2'd1) ? 7'd0 : {1'b0, slot} - DBITS[6:0];
  wire [6:0]   qd = (qn >= off) ? qn - off : qn + frame - off;
  wire         ch = (qd >= {1'b0, slot});
  wire [6:0]   k  = ch ? qd - {1'b0, slot} : qd;
  wire         load = (locked || wedge) && !ch && k == 7'd0;
  wire [W-1:0] nxt = !load ? cur : f_valid ? f_data : ctrl[4] ? cur : {W{1'b0}};
  // channel words of a sample
  wire [3*DBITS-1:0] sx = {{(3 * DBITS - W){1'b0}}, nxt};
  wire [DBITS-1:0] smp = sx[DBITS-1:0];
  wire [DBITS-1:0] wl = (NC == 2) ? sx[DBITS-1:0] : (!mono_r || dup) ? smp : {DBITS{1'b0}};
  wire [DBITS-1:0] wr = (NC == 2) ? sx[2*DBITS-1:DBITS] : (mono_r || dup) ? smp : {DBITS{1'b0}};
  wire [DBITS-1:0] wd = ch ? wr : wl;
  wire [6:0]   kb = DBITS[6:0] - 7'd1 - k;
  always @(posedge clk) begin
    f_pop <= 1'b0; ev_unf <= 1'b0;
    bs_d <= bs; en_d <= en;
    if (!rst_n || flush || !en) begin
      q <= frame - 7'd1; wsp <= left_lvl; locked <= (ROLE == 0); seen <= (ROLE == 0); sd_o <= 1'b0; cur <= {W{1'b0}};
      if (!rst_n) en_d <= 1'b0;
    end else if (fall && !seen) begin
      seen <= 1'b1; wsp <= wss;                     // slave: the reference level of ws, no edge yet
    end else if (fall) begin
      q <= qn; wsp <= vfall ? left_lvl : wss;
      if (wedge) locked <= 1'b1;
      if (load) begin
        cur <= nxt;
        if (f_valid) f_pop <= 1'b1; else ev_unf <= 1'b1;
      end
      sd_o <= ((locked || wedge) && k < DBITS) ? wd[kb[4:0]] : 1'b0;
    end
  end
endmodule

`default_nettype wire
