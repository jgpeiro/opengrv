// grv_strobe - fractional rate generator: stb is 1 on average INC / 2^32 of the clocks
// (32-bit phase accumulator, stb = carry out).
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_strobe (
  input  wire        clk,
  input  wire        rst_n,
  input  wire [31:0] inc,
  output reg         stb
);
  reg [31:0] acc;
  always @(posedge clk)
    if (!rst_n) begin
      acc <= 32'd0;
      stb <= 1'b0;
    end else begin
      {stb, acc} <= {1'b0, acc} + {1'b0, inc};
    end
endmodule

`default_nettype wire
