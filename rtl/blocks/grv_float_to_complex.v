// grv_float_to_complex - blocks_float_to_complex: I from input 0, Q from input 1 (0 when NI = 1).
// Each input is aligned (left shift SH0 / SH1) and resized. Latency 1 + OREG.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_float_to_complex #(
  parameter integer NI    = 2,
  parameter integer IW    = 16,
  parameter integer SH0   = 0,
  parameter integer SH1   = 0,
  parameter integer OW    = 16,
  parameter integer SHIFT = 0,
  parameter integer ROUND = 1,
  parameter integer SAT   = 1,
  parameter integer OREG  = 1
)(
  input  wire             clk,
  input  wire             rst_n,
  input  wire [NI*IW-1:0] s_tdata,
  input  wire [NI-1:0]    s_tvalid,
  output wire [NI-1:0]    s_tready,
  input  wire [NI-1:0]    s_tlast,
  output wire [2*OW-1:0]  m_tdata,
  output wire             m_tvalid,
  input  wire             m_tready,
  output wire             m_tlast,
  output wire             ovf
);
  localparam integer GW = IW + ((SH0 > SH1) ? SH0 : SH1) + 1;
  wire all_v = &s_tvalid;
  wire ce, pv, pr;
  wire [1:1] v;
  grv_pctl #(.L(1)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(all_v), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));
  assign s_tready = {NI{ce && all_v}};
  wire signed [GW-1:0] a = $signed(s_tdata[0 +: IW]) <<< SH0;
  wire signed [GW-1:0] b = (NI > 1) ? ($signed(s_tdata[(NI-1)*IW +: IW]) <<< SH1) : $signed({GW{1'b0}});
  wire [OW-1:0] ra, rb;
  wire          oa, ob;
  grv_resize #(.GW(GW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_a (.x(a), .y(ra), .ovf(oa));
  grv_resize #(.GW(GW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_b (.x(b), .y(rb), .ovf(ob));
  reg [2*OW-1:0] o1;
  reg            l1, ov1;
  always @(posedge clk) if (ce) begin o1 <= {rb, ra}; l1 <= s_tlast[0]; ov1 <= all_v & (oa | ob); end
  assign ovf = ov1 & ce & v[1];
  grv_oreg #(.W(2*OW), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o1), .s_tvalid(pv), .s_tready(pr),
    .s_tlast(l1), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
