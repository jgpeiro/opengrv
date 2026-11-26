// grv_threshold - blocks_threshold_ff: out = ONE once x > hi, 0 once x < lo (hysteresis),
// initial state INIT. Latency 1 + OREG.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_threshold #(
  parameter integer IW   = 16,
  parameter integer OW   = 16,
  parameter integer ONE  = 16384,
  parameter integer INIT = 0,
  parameter integer OREG = 1
)(
  input  wire          clk,
  input  wire          rst_n,
  input  wire [IW-1:0] s_tdata,
  input  wire          s_tvalid,
  output wire          s_tready,
  input  wire          s_tlast,
  input  wire [IW-1:0] cfg_lo,
  input  wire [IW-1:0] cfg_hi,
  output wire [OW-1:0] m_tdata,
  output wire          m_tvalid,
  input  wire          m_tready,
  output wire          m_tlast
);
  wire ce, pv, pr;
  wire [1:1] v;
  grv_pctl #(.L(1)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(s_tvalid), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));
  assign s_tready = ce;
  reg  st;
  wire x_hi = $signed(s_tdata) > $signed(cfg_hi);
  wire x_lo = $signed(s_tdata) < $signed(cfg_lo);
  wire nst  = x_hi ? 1'b1 : (x_lo ? 1'b0 : st);
  wire [OW-1:0] one = ONE;
  reg [OW-1:0] o1;
  reg          l1;
  always @(posedge clk) begin
    if (!rst_n) st <= (INIT != 0);
    else if (ce && s_tvalid) st <= nst;
    if (ce) begin o1 <= nst ? one : {OW{1'b0}}; l1 <= s_tlast; end
  end
  grv_oreg #(.W(OW), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o1), .s_tvalid(pv), .s_tready(pr),
    .s_tlast(l1), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
