// grv_xlating_fir - freq_xlating_fir_filter_xxx: mixer at the input rate (exp(j p[n]),
// cfg_freq = -center_freq / samp_rate * 2^32), resized to MW bits (SHIFT_MIX), then a
// decimating grv_fir with real or complex taps. Equal to GNU Radio's rotated-taps form up to the
// phase of the NCO at the start.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_xlating_fir #(
  parameter integer IW        = 16,
  parameter integer ICPLX     = 1,
  parameter integer MW        = 16,
  parameter integer SHIFT_MIX = 17,
  parameter integer CW        = 18,
  parameter integer CCPLX     = 0,
  parameter integer NTAPS     = 8,
  parameter [NTAPS*CW*(CCPLX+1)-1:0] COEFS = {NTAPS*CW*(CCPLX+1){1'b0}},
  parameter integer DECIM     = 1,
  parameter integer LANES     = 0,
  parameter integer SYM       = 0,
  parameter integer OW        = 16,
  parameter integer SHIFT     = 17,
  parameter integer ROUND     = 1,
  parameter integer SAT       = 1,
  parameter integer OREG      = 1
)(
  input  wire                    clk,
  input  wire                    rst_n,
  input  wire [IW*(ICPLX+1)-1:0] s_tdata,
  input  wire                    s_tvalid,
  output wire                    s_tready,
  input  wire                    s_tlast,
  input  wire [31:0]             cfg_freq,
  output wire [2*OW-1:0]         m_tdata,
  output wire                    m_tvalid,
  input  wire                    m_tready,
  output wire                    m_tlast,
  output wire                    ovf
);
  wire [2*MW-1:0] md;
  wire            mv, mr, ml, mo, fo;
  grv_mixer #(.IW(IW), .ICPLX(ICPLX), .OW(MW), .SHIFT(SHIFT_MIX), .ROUND(ROUND), .SAT(SAT), .OREG(0)) u_mix (
    .clk(clk), .rst_n(rst_n), .s_tdata(s_tdata), .s_tvalid(s_tvalid), .s_tready(s_tready), .s_tlast(s_tlast),
    .cfg_freq(cfg_freq), .m_tdata(md), .m_tvalid(mv), .m_tready(mr), .m_tlast(ml), .ovf(mo));
  grv_fir #(.IW(MW), .ICPLX(1), .CW(CW), .CCPLX(CCPLX), .NTAPS(NTAPS), .COEFS(COEFS), .L(1), .M(DECIM),
    .LANES(LANES), .SYM(SYM), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT), .OREG(OREG)) u_fir (
    .clk(clk), .rst_n(rst_n), .s_tdata(md), .s_tvalid(mv), .s_tready(mr), .s_tlast(ml),
    .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast), .ovf(fo));
  assign ovf = mo | fo;
endmodule

`default_nettype wire
