// grv_sincos - sine and cosine of a 12-bit phase (units of 2*pi/4096) from a quarter-wave ROM of
// 1024 x 17 bits (block RAM, two read ports). Outputs s18.17, |value| <= 2^17 - 1.
//   T[i] = round(sin(i*pi/2048) * (2^17-1)); quadrant q = p[11:10], index i = p[9:0]
//   q0: T[i]  q1: T[1024-i]  q2: -T[i]  q3: -T[1024-i]   (T[1024] = 2^17-1)
// Latency 2 clocks, clocked by ce.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_sincos (
  input  wire               clk,
  input  wire               ce,
  input  wire [11:0]        phase,
  output reg  signed [17:0] cos_o,
  output reg  signed [17:0] sin_o
);
  reg [16:0] tab [0:1023];
  initial begin
`include "grv_sin_tab.vh"
  end

  wire [11:0] pc = phase + 12'd1024;
  // stage 1: addresses and flags, ROM read
  wire [9:0] as = phase[10] ? (10'd0 - phase[9:0]) : phase[9:0];
  wire [9:0] ac = pc[10]    ? (10'd0 - pc[9:0])    : pc[9:0];
  reg  [16:0] rs, rc;
  reg         ms, mc, ns, nc;
  always @(posedge clk) if (ce) begin
    rs <= tab[as];
    rc <= tab[ac];
    ms <= phase[10] && (phase[9:0] == 10'd0);
    mc <= pc[10] && (pc[9:0] == 10'd0);
    ns <= phase[11];
    nc <= pc[11];
  end
  // stage 2: mirror and sign
  wire [16:0] vs = ms ? 17'h1FFFF : rs;
  wire [16:0] vc = mc ? 17'h1FFFF : rc;
  always @(posedge clk) if (ce) begin
    sin_o <= ns ? -$signed({1'b0, vs}) : $signed({1'b0, vs});
    cos_o <= nc ? -$signed({1'b0, vc}) : $signed({1'b0, vc});
  end
endmodule

`default_nettype wire
