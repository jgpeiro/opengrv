// grv_vector_rom - blocks_vector_source_x: N samples of SW bits from the parameter VEC
// (sample i at VEC[i*SW +: SW]), played once or repeated; tlast every VLEN samples (0: never).
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_vector_rom #(
  parameter integer SW     = 16,
  parameter integer N      = 4,
  parameter [SW*N-1:0] VEC = {SW*N{1'b0}},
  parameter integer REPEAT = 1,
  parameter integer VLEN   = 0,
  parameter integer OREG   = 1
)(
  input  wire          clk,
  input  wire          rst_n,
  input  wire          run,
  output wire [SW-1:0] m_tdata,
  output wire          m_tvalid,
  input  wire          m_tready,
  output wire          m_tlast
);
  localparam integer AW = (N > 1) ? $clog2(N) : 1;
  localparam integer VW = (VLEN > 1) ? $clog2(VLEN) : 1;
  localparam integer LATENCY = 1 + OREG;

  reg [SW-1:0] rom [0:N-1];
  integer i;
  initial for (i = 0; i < N; i = i + 1) rom[i] = VEC[i*SW +: SW];

  reg  [AW-1:0] idx;
  reg  [VW-1:0] vc;
  reg           done;
  wire ce, pv, pr;
  wire [1:1] v;
  wire go = run && !done;
  grv_pctl #(.L(1)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(go), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));

  reg [SW-1:0] o1;
  reg          l1;
  always @(posedge clk) if (ce) begin
    o1 <= rom[idx];
    l1 <= (VLEN > 0) && (vc == VLEN - 1);
  end
  always @(posedge clk) begin
    if (!rst_n) begin
      idx <= 0; vc <= 0; done <= 1'b0;
    end else if (ce && go) begin
      if (idx == N - 1) begin
        idx  <= 0;
        done <= (REPEAT == 0);
      end else idx <= idx + 1'b1;
      if (VLEN > 0) vc <= (vc == VLEN - 1) ? {VW{1'b0}} : vc + 1'b1;
    end
  end

  grv_oreg #(.W(SW), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o1), .s_tvalid(pv), .s_tready(pr),
    .s_tlast(l1), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
