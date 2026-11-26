// grv_i2s_clk - bit and word clocks of an I2S master (design document, section 9.4). bclk toggles
// every TIMING / 256 clocks (24.8 fixed point, at least 4 clocks), ws changes with the falling edge
// of bclk: it shows the left level for SLOT periods, then the right level for SLOT periods. mclk_o
// toggles every MDIV + 1 clocks when MCLKO is set. Stopped (bclk low, ws at the left level) while
// en is low, so the first frame after en starts with the left channel.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_i2s_clk (
  input  wire        clk,
  input  wire        rst_n,
  input  wire        en,
  input  wire [31:0] timing,       // half period of bclk, 24.8 clocks
  input  wire [5:0]  slot,         // bits per channel slot
  input  wire        left_lvl,     // ws level of the left channel
  input  wire        mclko,
  input  wire [7:0]  mdiv,
  output reg         bclk_o,
  output reg         ws_o,
  output reg         mclk_o
);
  reg [31:0] acc;
  reg [6:0]  pos;                  // bclk period in the frame, 0 .. 2 * SLOT - 1
  reg [7:0]  mc;
  wire [32:0] nacc = {1'b0, acc} + 33'd256;
  wire [6:0]  frame = {slot, 1'b0};
  wire [6:0]  npos = (pos + 7'd1 >= frame) ? 7'd0 : pos + 7'd1;
  always @(posedge clk) begin
    if (!rst_n || !en) begin
      acc <= 32'd0; pos <= 7'd0; bclk_o <= 1'b0; ws_o <= left_lvl;
    end else if (nacc >= {1'b0, timing}) begin
      acc <= nacc[31:0] - timing;
      bclk_o <= !bclk_o;
      if (bclk_o) begin            // falling edge: the next bit period starts
        pos  <= npos;
        ws_o <= (npos < {1'b0, slot}) ? left_lvl : !left_lvl;
      end
    end else
      acc <= nacc[31:0];
    if (!rst_n || !en || !mclko) begin
      mc <= 8'd0; mclk_o <= 1'b0;
    end else if (mc == mdiv) begin
      mc <= 8'd0; mclk_o <= !mclk_o;
    end else
      mc <= mc + 1'b1;
  end
endmodule

`default_nettype wire
