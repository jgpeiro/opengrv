// grv_throttle - blocks_throttle: passes at most one sample per token; a token is made on average
// every 2^32 / cfg_inc clocks (grv_strobe). Data unchanged; latency 1 + OREG.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_throttle #(
  parameter integer W    = 16,
  parameter integer OREG = 1
)(
  input  wire         clk,
  input  wire         rst_n,
  input  wire [W-1:0] s_tdata,
  input  wire         s_tvalid,
  output wire         s_tready,
  input  wire         s_tlast,
  input  wire [31:0]  cfg_inc,
  output wire [W-1:0] m_tdata,
  output wire         m_tvalid,
  input  wire         m_tready,
  output wire         m_tlast
);
  wire stb;
  reg  tok;
  grv_strobe u_s (.clk(clk), .rst_n(rst_n), .inc(cfg_inc), .stb(stb));
  wire ce, pv, pr;
  wire [1:1] v;
  grv_pctl #(.L(1)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(s_tvalid && tok), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));
  assign s_tready = ce && tok;
  always @(posedge clk)
    if (!rst_n) tok <= 1'b0;
    else if (stb) tok <= 1'b1;
    else if (s_tvalid && s_tready) tok <= 1'b0;
  reg [W-1:0] o1;
  reg         l1;
  always @(posedge clk) if (ce) begin o1 <= s_tdata; l1 <= s_tlast; end
  grv_oreg #(.W(W), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o1), .s_tvalid(pv), .s_tready(pr),
    .s_tlast(l1), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
