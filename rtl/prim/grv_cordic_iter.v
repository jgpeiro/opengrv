// grv_cordic_iter - iterative CORDIC: one stage used N times. start (when !busy) latches the
// pre-rotated inputs; done pulses N + 1 clocks later with the results, which stay until the next
// start. Same arithmetic as grv_cordic_pipe.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_cordic_iter #(
  parameter integer W    = 16,
  parameter integer N    = 18,
  parameter integer MODE = 0
)(
  input  wire              clk,
  input  wire              rst_n,
  input  wire              start,
  input  wire [W-1:0]      x,
  input  wire [W-1:0]      y,
  input  wire [31:0]       z,
  output wire              busy,
  output reg               done,
  output wire [W+2:0]      xo,
  output wire [W+2:0]      yo,
  output wire [31:0]       zo
);
  localparam integer XW = W + 3;
`include "grv_atan.vh"

  reg signed [XW-1:0] xr, yr;
  reg        [31:0]   zr;
  reg        [5:0]    it;
  reg                 run;
  assign busy = run;
  assign xo = xr;
  assign yo = yr;
  assign zo = zr;

  wire signed [XW-1:0] xi = {{3{x[W-1]}}, x};
  wire signed [XW-1:0] yi = {{3{y[W-1]}}, y};
  wire flip = (MODE == 0) ? xi[XW-1] : (z[31:30] == 2'b01 || z[31:30] == 2'b10);
  wire neg  = (MODE == 0) ? yr[XW-1] : !zr[31];
  wire signed [XW-1:0] xs = xr >>> it;
  wire signed [XW-1:0] ys = yr >>> it;

  always @(posedge clk) begin
    done <= 1'b0;
    if (!rst_n) begin
      run <= 1'b0;
    end else if (start && !run) begin
      xr  <= flip ? -xi : xi;
      yr  <= flip ? -yi : yi;
      zr  <= (MODE == 0) ? (flip ? 32'h80000000 : 32'h0) : (flip ? z + 32'h80000000 : z);
      it  <= 6'd0;
      run <= 1'b1;
    end else if (run) begin
      if (neg) begin
        xr <= xr - ys;
        yr <= yr + xs;
        zr <= zr - atan(it);
      end else begin
        xr <= xr + ys;
        yr <= yr - xs;
        zr <= zr + atan(it);
      end
      it <= it + 1'b1;
      if (it == N - 1) begin
        run  <= 1'b0;
        done <= 1'b1;
      end
    end
  end
endmodule

`default_nettype wire
