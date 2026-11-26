// grv_repeat - blocks_repeat: every input sample is output N times; tlast on the last copy.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_repeat #(
  parameter integer W    = 16,
  parameter integer N    = 2,
  parameter integer OREG = 1
)(
  input  wire         clk,
  input  wire         rst_n,
  input  wire [W-1:0] s_tdata,
  input  wire         s_tvalid,
  output wire         s_tready,
  input  wire         s_tlast,
  output wire [W-1:0] m_tdata,
  output wire         m_tvalid,
  input  wire         m_tready,
  output wire         m_tlast
);
  localparam integer CW = (N > 1) ? $clog2(N) : 1;
  reg [W-1:0]  hd;
  reg          hl, hv;
  reg [CW-1:0] rep;
  wire o_r;
  wire lastc = (rep == N - 1);
  assign s_tready = !hv || (o_r && lastc);
  always @(posedge clk) begin
    if (!rst_n) begin
      hv <= 1'b0; rep <= 0;
    end else begin
      if (hv && o_r) begin
        rep <= lastc ? {CW{1'b0}} : rep + 1'b1;
        if (lastc) hv <= 1'b0;
      end
      if (s_tvalid && s_tready) begin
        hv <= 1'b1; rep <= 0;
      end
    end
    if (s_tvalid && s_tready) begin hd <= s_tdata; hl <= s_tlast; end
  end
  grv_oreg #(.W(W), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(hd), .s_tvalid(hv), .s_tready(o_r),
    .s_tlast(hl && lastc), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
