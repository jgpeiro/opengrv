// grv_fifo - synchronous FIFO with first-word fall-through output.
// The memory has one write port and one synchronous read port (block RAM or LUT RAM); the head of
// the queue is held in an output register. Capacity DEPTH + 1, latency 2 clocks.
// s_tready depends only on registers (no path from m_tready).
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_fifo #(
  parameter integer W     = 16,
  parameter integer DEPTH = 16          // power of two
)(
  input  wire         clk,
  input  wire         rst_n,
  input  wire [W-1:0] s_tdata,
  input  wire         s_tvalid,
  output wire         s_tready,
  input  wire         s_tlast,
  output reg  [W-1:0] m_tdata,
  output reg          m_tvalid,
  input  wire         m_tready,
  output reg          m_tlast,
  output wire [$clog2(DEPTH+1):0] level
);
  localparam integer AW = (DEPTH > 1) ? $clog2(DEPTH) : 1;

  reg [W:0]  mem [0:DEPTH-1];
  reg [AW:0] wp, rp;
  wire [AW:0] cnt   = wp - rp;
  wire        full  = (cnt == DEPTH);
  wire        empty = (cnt == 0);
  assign s_tready = !full;
  wire wr  = s_tvalid && !full;
  wire ld  = !empty && (!m_tvalid || m_tready);

  always @(posedge clk)
    if (wr) mem[wp[AW-1:0]] <= {s_tlast, s_tdata};

  always @(posedge clk)
    if (ld) {m_tlast, m_tdata} <= mem[rp[AW-1:0]];

  always @(posedge clk) begin
    if (!rst_n) begin
      wp <= 0;
      rp <= 0;
      m_tvalid <= 1'b0;
    end else begin
      if (wr) wp <= wp + 1'b1;
      if (ld) rp <= rp + 1'b1;
      if (ld) m_tvalid <= 1'b1;
      else if (m_tready) m_tvalid <= 1'b0;
    end
  end

  assign level = cnt + m_tvalid;
endmodule

`default_nettype wire
