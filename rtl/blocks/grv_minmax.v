// grv_minmax - blocks_max_xx / blocks_min_xx (vlen 1): element-wise maximum or minimum of NI
// real streams. Latency 1 + OREG.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_minmax #(
  parameter integer NI   = 2,
  parameter integer IW   = 16,
  parameter integer MAX  = 1,
  parameter integer OREG = 1
)(
  input  wire             clk,
  input  wire             rst_n,
  input  wire [NI*IW-1:0] s_tdata,
  input  wire [NI-1:0]    s_tvalid,
  output wire [NI-1:0]    s_tready,
  input  wire [NI-1:0]    s_tlast,
  output wire [IW-1:0]    m_tdata,
  output wire             m_tvalid,
  input  wire             m_tready,
  output wire             m_tlast
);
  wire all_v = &s_tvalid;
  wire ce, pv, pr;
  wire [1:1] v;
  grv_pctl #(.L(1)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(all_v), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));
  assign s_tready = {NI{ce && all_v}};
  reg signed [IW-1:0] best;
  integer k;
  always @(*) begin
    best = s_tdata[0 +: IW];
    for (k = 1; k < NI; k = k + 1)
      if ((MAX != 0) ? ($signed(s_tdata[k*IW +: IW]) > best) : ($signed(s_tdata[k*IW +: IW]) < best))
        best = s_tdata[k*IW +: IW];
  end
  reg [IW-1:0] o1;
  reg          l1;
  always @(posedge clk) if (ce) begin o1 <= best; l1 <= s_tlast[0]; end
  grv_oreg #(.W(IW), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o1), .s_tvalid(pv), .s_tready(pr),
    .s_tlast(l1), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
