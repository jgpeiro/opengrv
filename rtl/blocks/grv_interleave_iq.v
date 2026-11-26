// grv_interleave_iq - blocks_complex_to_interleaved_short / _char: each complex sample gives two
// real samples, I then Q, both resized. VEC = 1 sets tlast on every Q (vector output), otherwise
// the input tlast goes with Q. One input per two output clocks.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_interleave_iq #(
  parameter integer IW    = 16,
  parameter integer OW    = 16,
  parameter integer SHIFT = 0,
  parameter integer ROUND = 1,
  parameter integer SAT   = 1,
  parameter integer VEC   = 0,
  parameter integer OREG  = 1
)(
  input  wire            clk,
  input  wire            rst_n,
  input  wire [2*IW-1:0] s_tdata,
  input  wire            s_tvalid,
  output wire            s_tready,
  input  wire            s_tlast,
  output wire [OW-1:0]   m_tdata,
  output wire            m_tvalid,
  input  wire            m_tready,
  output wire            m_tlast,
  output wire            ovf
);
  wire [OW-1:0] ri, rq;
  wire          oi, oq;
  grv_resize #(.GW(IW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_i (.x(s_tdata[0 +: IW]), .y(ri), .ovf(oi));
  grv_resize #(.GW(IW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_q (.x(s_tdata[IW +: IW]), .y(rq), .ovf(oq));
  reg [OW-1:0] hi, hq;
  reg          hv, ph, hl;
  wire         o_r;
  wire         take = s_tvalid && s_tready;
  assign s_tready = !hv || (ph && o_r);
  assign ovf = take && (oi || oq);
  always @(posedge clk) begin
    if (!rst_n) begin
      hv <= 1'b0; ph <= 1'b0;
    end else begin
      if (hv && o_r) begin
        if (ph) hv <= 1'b0;
        ph <= !ph;
      end
      if (take) begin
        hv <= 1'b1; ph <= 1'b0;
      end
    end
    if (take) begin hi <= ri; hq <= rq; hl <= s_tlast; end
  end
  grv_oreg #(.W(OW), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(ph ? hq : hi), .s_tvalid(hv), .s_tready(o_r),
    .s_tlast(ph && (VEC != 0 || hl)), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
