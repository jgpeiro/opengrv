// grv_skid - register slice: registered tdata / tvalid / tlast and a registered tready, with a
// skid register that catches the sample arriving in the clock in which the output stalls.
// Throughput one sample per clock, latency one clock.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_skid #(
  parameter integer W = 16
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
  output reg          m_tlast
);
  reg [W-1:0] sk_d;
  reg         sk_l;
  reg         sk_v;

  assign s_tready = !sk_v;
  wire s_x  = s_tvalid && !sk_v;
  wire o_en = !m_tvalid || m_tready;

  always @(posedge clk) begin
    if (!rst_n) begin
      m_tvalid <= 1'b0;
      sk_v     <= 1'b0;
    end else if (o_en) begin
      if (sk_v) begin
        m_tvalid <= 1'b1;
        sk_v     <= 1'b0;
      end else begin
        m_tvalid <= s_x;
      end
    end else if (s_x) begin
      sk_v <= 1'b1;
    end
  end

  always @(posedge clk) begin
    if (o_en) begin
      if (sk_v) begin
        m_tdata <= sk_d;
        m_tlast <= sk_l;
      end else if (s_x) begin
        m_tdata <= s_tdata;
        m_tlast <= s_tlast;
      end
    end else if (s_x) begin
      sk_d <= s_tdata;
      sk_l <= s_tlast;
    end
  end
endmodule

`default_nettype wire
