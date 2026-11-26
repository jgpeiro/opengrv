// grv_cordic_pipe - pipelined CORDIC, one result per clock, latency N + 1 (clocked by ce).
// MODE 0 (vector): xo = K*|(x,y)|, zo = atan2(y, x) as a 32-bit phase (2*pi = 2^32).
// MODE 1 (rotate): (xo, yo) = K * (x, y) rotated by the 32-bit phase z.
// Internal width XW = W + 3. Bit-exact with grvgen/grv/fx.py cordic_vec / cordic_rot.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_cordic_pipe #(
  parameter integer W    = 16,
  parameter integer N    = 18,
  parameter integer MODE = 0
)(
  input  wire              clk,
  input  wire              ce,
  input  wire [W-1:0]      x,
  input  wire [W-1:0]      y,
  input  wire [31:0]       z,
  output wire [W+2:0]      xo,
  output wire [W+2:0]      yo,
  output wire [31:0]       zo
);
  localparam integer XW = W + 3;
`include "grv_atan.vh"

  wire signed [XW-1:0] xa [0:N];
  wire signed [XW-1:0] ya [0:N];
  wire        [31:0]   za [0:N];

  wire signed [XW-1:0] xi = {{3{x[W-1]}}, x};
  wire signed [XW-1:0] yi = {{3{y[W-1]}}, y};
  reg  signed [XW-1:0] x0, y0;
  reg         [31:0]   z0;
  wire flip = (MODE == 0) ? xi[XW-1] : (z[31:30] == 2'b01 || z[31:30] == 2'b10);
  always @(posedge clk) if (ce) begin
    x0 <= flip ? -xi : xi;
    y0 <= flip ? -yi : yi;
    z0 <= (MODE == 0) ? (flip ? 32'h80000000 : 32'h0) : (flip ? z + 32'h80000000 : z);
  end
  assign xa[0] = x0;
  assign ya[0] = y0;
  assign za[0] = z0;

  genvar i;
  generate
    for (i = 0; i < N; i = i + 1) begin : g_st
      reg signed [XW-1:0] xr, yr;
      reg        [31:0]   zr;
      wire neg = (MODE == 0) ? ya[i][XW-1] : !za[i][31];   // vector: y < 0 ; rotate: z >= 0
      wire signed [XW-1:0] xs = xa[i] >>> i;
      wire signed [XW-1:0] ys = ya[i] >>> i;
      always @(posedge clk) if (ce) begin
        if (neg) begin
          xr <= xa[i] - ys;
          yr <= ya[i] + xs;
          zr <= za[i] - atan(i);
        end else begin
          xr <= xa[i] + ys;
          yr <= ya[i] - xs;
          zr <= za[i] + atan(i);
        end
      end
      assign xa[i + 1] = xr;
      assign ya[i + 1] = yr;
      assign za[i + 1] = zr;
    end
  endgenerate

  assign xo = xa[N];
  assign yo = ya[N];
  assign zo = za[N];
endmodule

`default_nettype wire
