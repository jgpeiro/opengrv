// grv_pe_gpio_in - GPIO input endpoint (design document, section 9.5). NPIN = DBITS * NC pins, I on the
// low pins. Modes (FORMAT.MODE):
//   0 PERIODIC  sample on every tick of the pacing timer, PHASE clocks after the tick (plus the two
//               synchroniser clocks); FORMAT.CLKO drives clk_o high on the tick for half the period
//   1 STROBE    sample on the rising (FORMAT.EDGE = 0) or falling edge of stb; strobe through three
//               flops, data through two, so the sample is the one at the pins at the edge
//   2 CHANGE    sample when the pins, stable for FILTER clocks, differ from the last sample
//   FORMAT [1:0] MODE [2] EDGE [3] OFS [4] CLKO [15:8] PHASE [23:16] FILTER
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_pe_gpio_in #(
  parameter integer DBITS   = 8,
  parameter integer NC      = 1,
  parameter integer SIGNED  = 1,
  parameter integer FRAC    = 7,
  parameter integer DEPTH   = 32,
  parameter [31:0]  CTRL0   = 32'h1,
  parameter [31:0]  TIMING0 = 32'd0,
  parameter [31:0]  FORMAT0 = 32'd0,
  parameter [31:0]  THRESH0 = 32'd1
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
  input  wire [DBITS*NC-1:0] pins_i,
  input  wire                stb_i,
  output reg                 clk_o
);
  localparam integer W  = DBITS * NC;
  localparam integer AW = $clog2(DEPTH);
  localparam [31:0] INFO = {2'd0, DBITS[4:0] - 5'd1, 1'b0, 4'd4, AW[3:0], 2'd0, FRAC[5:0], SIGNED[0], (NC == 2), DBITS[5:0]};

  wire [31:0] ctrl, thresh, timing, format, k0, k1, k2, k3;
  wire        flush;
  wire [15:0] level;
  wire        en = ctrl[0] && run;
  wire [1:0]  mode = format[1:0];
  wire        edge_f = format[2], ofs = format[3], clko = format[4];
  wire [7:0]  phase = format[15:8], filt = format[23:16];

  reg  [W-1:0] p_data;
  reg          p_push;
  wire         f_ready, f_valid;
  wire [W-1:0] f_data;
  grv_fifo_fl #(.W(W), .DEPTH(DEPTH)) u_fifo (.clk(clk), .rst_n(rst_n), .flush(flush),
    .s_data(p_data), .s_valid(p_push), .s_ready(f_ready),
    .m_data(f_data), .m_valid(f_valid), .m_ready(m_tready && en), .level(level));
  assign m_tdata  = f_data;
  assign m_tlast  = 1'b0;
  assign m_tvalid = f_valid && en;

  grv_pe_regs #(.DIR(0), .INFO(INFO), .CTRL0(CTRL0), .THRESH0(THRESH0), .TIMING0(TIMING0), .FORMAT0(FORMAT0))
  u_regs (.clk(clk), .rst_n(rst_n), .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re),
    .rb_sel(rb_sel), .t_wrdy(t_wrdy), .t_rrdy(t_rrdy), .t_rdata(t_rdata), .irq(irq),
    .ctrl(ctrl), .thresh(thresh), .timing(timing), .format(format), .k0(k0), .k1(k1), .k2(k2), .k3(k3),
    .flush(flush), .level(level), .full(!f_ready), .busy(1'b0), .ev_xfer(m_tvalid && m_tready),
    .ev_ovf(p_push && !f_ready), .ev_unf(1'b0), .ev_err(1'b0));

  wire [W-1:0] d2;
  wire         s2;
  grv_sync #(.N(W + 1)) u_sync (.clk(clk), .rst_n(rst_n), .d({stb_i, pins_i}), .q({s2, d2}));
  reg s3;
  wire tick;
  grv_pace u_pace (.clk(clk), .rst_n(rst_n), .en(en && mode == 2'd0), .timing(timing), .tick(tick));

  // offset binary -> two's complement per component
  function [W-1:0] conv(input [W-1:0] v, input o);
    integer c;
    begin
      conv = v;
      for (c = 0; c < NC; c = c + 1) conv[c * DBITS + DBITS - 1] = v[c * DBITS + DBITS - 1] ^ o;
    end
  endfunction

  reg [31:0]  pos;          // clocks since the tick
  reg [8:0]   dly;          // countdown to the PERIODIC sample
  reg         dact;
  reg [W-1:0] cand, last;
  reg [7:0]   fcnt;
  reg         first;
  always @(posedge clk) begin
    p_push <= 1'b0;
    if (!rst_n || flush) begin
      s3 <= 1'b0; pos <= 32'hFFFF_FFFF; dact <= 1'b0; clk_o <= 1'b0; first <= 1'b1; fcnt <= 8'd0;
      cand <= {W{1'b0}}; last <= {W{1'b0}};
    end else begin
      s3 <= s2;
      // clock output and PERIODIC sampling
      if (tick) pos <= 32'd0; else if (pos != 32'hFFFF_FFFF) pos <= pos + 1'b1;
      clk_o <= en && clko && (mode == 2'd0) && (tick || (pos + 1'b1 < {9'd0, timing[31:9]}));
      if (tick) begin dly <= {1'b0, phase} + 9'd2; dact <= 1'b1; end
      else if (dact) begin
        if (dly == 9'd0) begin dact <= 1'b0; p_data <= conv(d2, ofs); p_push <= 1'b1; end
        else dly <= dly - 1'b1;
      end
      // STROBE
      if (en && mode == 2'd1 && (edge_f ? (!s2 && s3) : (s2 && !s3))) begin
        p_data <= conv(d2, ofs); p_push <= 1'b1;
      end
      // CHANGE
      if (!en || mode != 2'd2) begin
        first <= 1'b1; fcnt <= 8'd0; cand <= d2;
      end else begin
        if (d2 != cand) begin cand <= d2; fcnt <= 8'd0; end
        else if (fcnt != filt) fcnt <= fcnt + 1'b1;
        else if (first || cand != last) begin
          last <= cand; first <= 1'b0; p_data <= conv(cand, ofs); p_push <= 1'b1;
        end
      end
    end
  end
endmodule

`default_nettype wire
