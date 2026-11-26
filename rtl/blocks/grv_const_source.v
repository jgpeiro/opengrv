// grv_const_source - analog_const_source_x, blocks_null_source (cfg_value = 0): a constant stream.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_const_source #(
  parameter integer OW   = 16,
  parameter integer CPLX = 0,
  parameter integer OREG = 1
)(
  input  wire                   clk,
  input  wire                   rst_n,
  input  wire                   run,
  input  wire [OW*(CPLX+1)-1:0] cfg_value,
  output wire [OW*(CPLX+1)-1:0] m_tdata,
  output wire                   m_tvalid,
  input  wire                   m_tready,
  output wire                   m_tlast
);
  localparam integer LATENCY = 1 + OREG;
  wire ce, pv, pr;
  wire [1:1] v;
  grv_pctl #(.L(1)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(run), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));
  reg [OW*(CPLX+1)-1:0] o1;
  always @(posedge clk) if (ce) o1 <= cfg_value;
  grv_oreg #(.W(OW*(CPLX+1)), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o1), .s_tvalid(pv), .s_tready(pr),
    .s_tlast(1'b0), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
