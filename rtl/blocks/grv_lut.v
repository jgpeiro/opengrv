// grv_lut - table lookup: digital_chunks_to_symbols_xx (D outputs per input: TABLE[in*D + d]),
// digital_map_bb (D = 1), digital_binary_slicer_fb (SLICER = 1: out = (x >= 0)).
// TABLE: N entries of OW*NCO bits; the index wraps modulo N. Latency 1 + OREG.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_lut #(
  parameter integer IW     = 8,
  parameter integer SLICER = 0,
  parameter integer D      = 1,
  parameter integer N      = 2,
  parameter integer OW     = 16,
  parameter integer OCPLX  = 0,
  parameter [N*OW*(OCPLX+1)-1:0] TABLE = {N*OW*(OCPLX+1){1'b0}},
  parameter integer OREG   = 1
)(
  input  wire                    clk,
  input  wire                    rst_n,
  input  wire [IW-1:0]           s_tdata,
  input  wire                    s_tvalid,
  output wire                    s_tready,
  input  wire                    s_tlast,
  output wire [OW*(OCPLX+1)-1:0] m_tdata,
  output wire                    m_tvalid,
  input  wire                    m_tready,
  output wire                    m_tlast
);
  localparam integer EW = OW * (OCPLX + 1);
  localparam integer AW = (N > 1) ? $clog2(N) : 1;
  localparam integer DW = (D > 1) ? $clog2(D) : 1;
  reg [EW-1:0] rom [0:N-1];
  integer i;
  initial for (i = 0; i < N; i = i + 1) rom[i] = TABLE[i*EW +: EW];
  reg  [DW-1:0] d;
  wire          lastd = (d == D - 1);
  wire ce, pv, pr;
  wire [1:1] v;
  grv_pctl #(.L(1)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(s_tvalid), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));
  assign s_tready = ce && lastd;
  always @(posedge clk)
    if (!rst_n) d <= 0;
    else if (ce && s_tvalid) d <= lastd ? {DW{1'b0}} : d + 1'b1;
  wire [31:0] raw = {{(32-IW){1'b0}}, s_tdata} * D + d;
  wire [31:0] idx = ((N & (N - 1)) == 0) ? (raw & (N - 1)) : (raw % N);
  reg [EW-1:0] o1;
  reg          l1;
  always @(posedge clk) if (ce) begin
    o1 <= (SLICER != 0) ? {{(EW-1){1'b0}}, !s_tdata[IW-1]} : rom[idx[AW-1:0]];
    l1 <= s_tlast && lastd;
  end
  grv_oreg #(.W(EW), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o1), .s_tvalid(pv), .s_tready(pr),
    .s_tlast(l1), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
