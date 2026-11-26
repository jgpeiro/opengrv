// grv_logic - blocks_and_xx, _or_xx, _xor_xx (NI inputs), blocks_not_xx, blocks_and_const_xx.
//   OP 0 and, 1 or, 2 xor, 3 not (input 0), 4 and with cfg_k. Latency 1 + OREG.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_logic #(
  parameter integer NI   = 2,
  parameter integer W    = 16,
  parameter integer OP   = 0,
  parameter integer OREG = 1
)(
  input  wire            clk,
  input  wire            rst_n,
  input  wire [NI*W-1:0] s_tdata,
  input  wire [NI-1:0]   s_tvalid,
  output wire [NI-1:0]   s_tready,
  input  wire [NI-1:0]   s_tlast,
  input  wire [W-1:0]    cfg_k,
  output wire [W-1:0]    m_tdata,
  output wire            m_tvalid,
  input  wire            m_tready,
  output wire            m_tlast
);
  wire all_v = &s_tvalid;
  wire ce, pv, pr;
  wire [1:1] v;
  grv_pctl #(.L(1)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(all_v), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));
  assign s_tready = {NI{ce && all_v}};
  reg [W-1:0] r;
  integer k;
  always @(*) begin
    r = s_tdata[0 +: W];
    for (k = 1; k < NI; k = k + 1)
      case (OP)
        0: r = r & s_tdata[k*W +: W];
        1: r = r | s_tdata[k*W +: W];
        2: r = r ^ s_tdata[k*W +: W];
        default: r = r;
      endcase
    if (OP == 3) r = ~s_tdata[0 +: W];
    if (OP == 4) r = s_tdata[0 +: W] & cfg_k;
  end
  reg [W-1:0] o1;
  reg         l1;
  always @(posedge clk) if (ce) begin o1 <= r; l1 <= s_tlast[0]; end
  grv_oreg #(.W(W), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o1), .s_tvalid(pv), .s_tready(pr),
    .s_tlast(l1), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
