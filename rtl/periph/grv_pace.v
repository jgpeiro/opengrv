// grv_pace - pacing timer of the peripheral endpoints. TIMING is a number of clocks in 24.8 fixed
// point; the timer ticks once per TIMING / 256 clocks on average (evenly spaced when the fraction is
// zero, one clock of jitter otherwise). TIMING < 256 (less than one clock) or a disabled timer gives
// no ticks. The first tick comes one period after the timer is enabled.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_pace (
  input  wire        clk,
  input  wire        rst_n,
  input  wire        en,
  input  wire [31:0] timing,
  output wire        tick
);
  reg  [32:0] acc;
  wire [32:0] nxt = acc + 33'd256;
  wire        ok  = en && (timing >= 32'd256);
  assign tick = ok && (nxt >= {1'b0, timing});
  always @(posedge clk) begin
    if (!rst_n || !ok) acc <= 33'd0;
    else acc <= tick ? nxt - {1'b0, timing} : nxt;
  end
endmodule

`default_nettype wire
