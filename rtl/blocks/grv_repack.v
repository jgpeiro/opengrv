// grv_repack - blocks_repack_bits_bb (K bits in, LO bits out per byte), and with it
// blocks_pack_k_bits_bb (K=1, LO=k, MSB first), blocks_unpack_k_bits_bb (K=k, LO=1, MSB first),
// blocks_packed_to_unpacked_bb (K=8, LO=bits_per_chunk), blocks_unpacked_to_packed_bb (LO=8).
// MSB = 1: bits are taken from bit K-1 down and placed from bit LO-1 down; MSB = 0: LSB first.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_repack #(
  parameter integer K    = 8,
  parameter integer LO   = 1,
  parameter integer MSB  = 1,
  parameter integer IW   = 8,
  parameter integer OW   = 8,
  parameter integer OREG = 1
)(
  input  wire          clk,
  input  wire          rst_n,
  input  wire [IW-1:0] s_tdata,
  input  wire          s_tvalid,
  output wire          s_tready,
  input  wire          s_tlast,
  output wire [OW-1:0] m_tdata,
  output wire          m_tvalid,
  input  wire          m_tready,
  output wire          m_tlast
);
  localparam integer BW = K + LO;
  localparam integer NW = $clog2(BW + 1);
  reg  [BW-1:0] buf_q;
  reg  [NW-1:0] n;
  wire          o_r;
  wire          emit = (n >= LO) && o_r;
  wire [NW-1:0] n1   = emit ? n - LO : n;
  assign s_tready = (n1 + K <= BW);
  wire          take = s_tvalid && s_tready;
  function [K-1:0] rev_in(input [K-1:0] v);
    integer i;
    for (i = 0; i < K; i = i + 1) rev_in[i] = v[K-1-i];
  endfunction
  function [LO-1:0] rev_out(input [LO-1:0] v);
    integer i;
    for (i = 0; i < LO; i = i + 1) rev_out[i] = v[LO-1-i];
  endfunction
  wire [K-1:0]  bits = (MSB != 0) ? rev_in(s_tdata[K-1:0]) : s_tdata[K-1:0];
  wire [BW-1:0] b1   = emit ? (buf_q >> LO) : buf_q;
  always @(posedge clk) begin
    if (!rst_n) begin
      n <= 0; buf_q <= 0;
    end else begin
      buf_q <= take ? (b1 | ({{LO{1'b0}}, bits} << n1)) : b1;
      n     <= take ? n1 + K : n1;
    end
  end
  wire [LO-1:0] ob = (MSB != 0) ? rev_out(buf_q[LO-1:0]) : buf_q[LO-1:0];
  grv_oreg #(.W(OW), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata({{(OW-LO){1'b0}}, ob}), .s_tvalid(n >= LO),
    .s_tready(o_r), .s_tlast(1'b0), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
