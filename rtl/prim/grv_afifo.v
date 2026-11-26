// grv_afifo - asynchronous FIFO: Gray-coded pointers, two-flop synchronisers, first-word
// fall-through output register in the read domain.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_afifo #(
  parameter integer W     = 16,
  parameter integer DEPTH = 16          // power of two, >= 4
)(
  input  wire         s_clk,
  input  wire         s_rst_n,
  input  wire [W-1:0] s_tdata,
  input  wire         s_tvalid,
  output wire         s_tready,
  input  wire         s_tlast,
  output wire [$clog2(DEPTH):0] s_level,   // write-domain fill level (pessimistic)
  input  wire         m_clk,
  input  wire         m_rst_n,
  output reg  [W-1:0] m_tdata,
  output reg          m_tvalid,
  input  wire         m_tready,
  output reg          m_tlast,
  output wire [$clog2(DEPTH):0] m_level    // read-domain fill level (pessimistic)
);
  localparam integer AW = $clog2(DEPTH);

  function [AW:0] bin2gray(input [AW:0] b);
    bin2gray = b ^ (b >> 1);
  endfunction
  function [AW:0] gray2bin(input [AW:0] g);
    integer i;
    begin
      gray2bin[AW] = g[AW];
      for (i = AW - 1; i >= 0; i = i - 1) gray2bin[i] = gray2bin[i + 1] ^ g[i];
    end
  endfunction

  reg [W:0] mem [0:DEPTH-1];

  // write domain
  reg  [AW:0] wp, wp_g;
  reg  [AW:0] rg_s1, rg_s2;
  wire [AW:0] rp_w = gray2bin(rg_s2);
  wire        full = (wp - rp_w) == DEPTH;
  assign s_tready = !full;
  assign s_level  = wp - rp_w;
  wire wr = s_tvalid && !full;
  always @(posedge s_clk) if (wr) mem[wp[AW-1:0]] <= {s_tlast, s_tdata};
  always @(posedge s_clk) begin
    if (!s_rst_n) begin
      wp <= 0; wp_g <= 0; rg_s1 <= 0; rg_s2 <= 0;
    end else begin
      if (wr) begin
        wp   <= wp + 1'b1;
        wp_g <= bin2gray(wp + 1'b1);
      end
      rg_s1 <= rp_g;
      rg_s2 <= rg_s1;
    end
  end

  // read domain
  reg  [AW:0] rp, rp_g;
  reg  [AW:0] wg_s1, wg_s2;
  wire [AW:0] wp_r  = gray2bin(wg_s2);
  wire        empty = (wp_r == rp);
  wire        ld    = !empty && (!m_tvalid || m_tready);
  assign m_level = (wp_r - rp) + m_tvalid;
  always @(posedge m_clk) if (ld) {m_tlast, m_tdata} <= mem[rp[AW-1:0]];
  always @(posedge m_clk) begin
    if (!m_rst_n) begin
      rp <= 0; rp_g <= 0; wg_s1 <= 0; wg_s2 <= 0; m_tvalid <= 1'b0;
    end else begin
      if (ld) begin
        rp   <= rp + 1'b1;
        rp_g <= bin2gray(rp + 1'b1);
      end
      if (ld) m_tvalid <= 1'b1;
      else if (m_tready) m_tvalid <= 1'b0;
      wg_s1 <= wp_g;
      wg_s2 <= wg_s1;
    end
  end
endmodule

`default_nettype wire
