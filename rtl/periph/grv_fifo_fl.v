// grv_fifo_fl - synchronous first-word fall-through FIFO with flush, for the endpoints.
// Capacity DEPTH (power of two). level counts the words held, including the output register.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_fifo_fl #(
  parameter integer W     = 16,
  parameter integer DEPTH = 16
)(
  input  wire         clk,
  input  wire         rst_n,
  input  wire         flush,
  input  wire [W-1:0] s_data,
  input  wire         s_valid,
  output wire         s_ready,
  output wire [W-1:0] m_data,
  output wire         m_valid,
  input  wire         m_ready,
  output wire [15:0]  level
);
  localparam integer AW = (DEPTH > 1) ? $clog2(DEPTH) : 1;
  reg [W-1:0] mem [0:DEPTH-1];
  reg [AW:0]  wp, rp;
  wire [AW:0] cnt = wp - rp;
  assign s_ready = (cnt != DEPTH);
  assign m_valid = (cnt != 0);
  assign m_data  = mem[rp[AW-1:0]];
  wire wr = s_valid && s_ready;
  wire rd = m_valid && m_ready;
  always @(posedge clk) if (wr) mem[wp[AW-1:0]] <= s_data;
  always @(posedge clk) begin
    if (!rst_n || flush) begin
      wp <= 0;
      rp <= 0;
    end else begin
      if (wr) wp <= wp + 1'b1;
      if (rd) rp <= rp + 1'b1;
    end
  end
  assign level = cnt;
endmodule

`default_nettype wire
