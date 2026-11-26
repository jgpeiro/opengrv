// grv_sync - two-flop synchroniser for N asynchronous inputs (pins), with a reset value.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_sync #(
  parameter integer N    = 1,
  parameter [N-1:0] INIT = {N{1'b0}}
)(
  input  wire         clk,
  input  wire         rst_n,
  input  wire [N-1:0] d,
  output wire [N-1:0] q
);
  (* ASYNC_REG = "TRUE" *) reg [N-1:0] s1, s2;
  always @(posedge clk) begin
    if (!rst_n) begin
      s1 <= INIT;
      s2 <= INIT;
    end else begin
      s1 <= d;
      s2 <= s1;
    end
  end
  assign q = s2;
endmodule

`default_nettype wire
