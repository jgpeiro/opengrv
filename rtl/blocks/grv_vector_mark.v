// grv_vector_mark - blocks_stream_to_vector (MODE 0: tlast on every VLEN-th sample) and
// blocks_vector_to_stream (MODE 1: tlast cleared). Latency 0 + OREG.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_vector_mark #(
  parameter integer W    = 16,
  parameter integer MODE = 0,
  parameter integer VLEN = 4,
  parameter integer OREG = 1
)(
  input  wire         clk,
  input  wire         rst_n,
  input  wire [W-1:0] s_tdata,
  input  wire         s_tvalid,
  output wire         s_tready,
  input  wire         s_tlast,
  output wire [W-1:0] m_tdata,
  output wire         m_tvalid,
  input  wire         m_tready,
  output wire         m_tlast
);
  localparam integer CW = (VLEN > 1) ? $clog2(VLEN) : 1;
  reg [CW-1:0] c;
  always @(posedge clk)
    if (!rst_n) c <= 0;
    else if (s_tvalid && s_tready) c <= (c == VLEN - 1) ? {CW{1'b0}} : c + 1'b1;
  wire l = (MODE == 0) ? (c == VLEN - 1) : 1'b0;
  grv_oreg #(.W(W), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(s_tdata), .s_tvalid(s_tvalid), .s_tready(s_tready),
    .s_tlast(l), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
