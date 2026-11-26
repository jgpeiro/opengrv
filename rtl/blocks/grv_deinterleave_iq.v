// grv_deinterleave_iq - blocks_interleaved_short_to_complex / _char_to_complex: pairs of real
// samples (I, Q; Q, I with SWAP) become one complex sample, both components resized. tlast from
// the second sample of the pair.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_deinterleave_iq #(
  parameter integer IW    = 16,
  parameter integer OW    = 16,
  parameter integer SWAP  = 0,
  parameter integer SHIFT = 0,
  parameter integer ROUND = 1,
  parameter integer SAT   = 1,
  parameter integer OREG  = 1
)(
  input  wire            clk,
  input  wire            rst_n,
  input  wire [IW-1:0]   s_tdata,
  input  wire            s_tvalid,
  output wire            s_tready,
  input  wire            s_tlast,
  output wire [2*OW-1:0] m_tdata,
  output wire            m_tvalid,
  input  wire            m_tready,
  output wire            m_tlast,
  output wire            ovf
);
  reg [IW-1:0] first;
  reg          half;
  wire ce, pv, pr;
  wire [1:1] v;
  wire second = s_tvalid && half;
  grv_pctl #(.L(1)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(second), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));
  assign s_tready = !half || ce;
  wire [IW-1:0] xi = (SWAP != 0) ? s_tdata : first;
  wire [IW-1:0] xq = (SWAP != 0) ? first : s_tdata;
  wire [OW-1:0] ri, rq;
  wire          oi, oq;
  grv_resize #(.GW(IW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_i (.x(xi), .y(ri), .ovf(oi));
  grv_resize #(.GW(IW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_q (.x(xq), .y(rq), .ovf(oq));
  reg [2*OW-1:0] o1;
  reg            l1, ov1;
  always @(posedge clk) begin
    if (!rst_n) half <= 1'b0;
    else if (s_tvalid && s_tready) half <= !half;
    if (s_tvalid && !half) first <= s_tdata;
    if (ce) begin o1 <= {rq, ri}; l1 <= s_tlast; ov1 <= second & (oi | oq); end
  end
  assign ovf = ov1 & ce & v[1];
  grv_oreg #(.W(2*OW), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o1), .s_tvalid(pv), .s_tready(pr),
    .s_tlast(l1), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
