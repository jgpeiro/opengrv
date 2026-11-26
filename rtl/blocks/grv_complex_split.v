// grv_complex_split - blocks_complex_to_real (MODE 0), _to_imag (1), _to_float (2: two outputs,
// 0 real and 1 imaginary). No arithmetic; latency 0 + OREG.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_complex_split #(
  parameter integer IW   = 16,
  parameter integer MODE = 2,
  parameter integer OREG = 1
)(
  input  wire                               clk,
  input  wire                               rst_n,
  input  wire [2*IW-1:0]                    s_tdata,
  input  wire                               s_tvalid,
  output wire                               s_tready,
  input  wire                               s_tlast,
  output wire [IW*((MODE==2)?2:1)-1:0]      m_tdata,
  output wire [((MODE==2)?2:1)-1:0]         m_tvalid,
  input  wire [((MODE==2)?2:1)-1:0]         m_tready,
  output wire [((MODE==2)?2:1)-1:0]         m_tlast
);
  generate
    if (MODE != 2) begin : g_one
      grv_oreg #(.W(IW), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(s_tdata[IW*MODE +: IW]), .s_tvalid(s_tvalid),
        .s_tready(s_tready), .s_tlast(s_tlast), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
    end else begin : g_two
      wire [4*IW-1:0] fd;
      wire [1:0] fv, fr, fl;
      grv_fork #(.W(2*IW), .N(2)) u_f (.clk(clk), .rst_n(rst_n), .s_tdata(s_tdata), .s_tvalid(s_tvalid), .s_tready(s_tready),
        .s_tlast(s_tlast), .m_tdata(fd), .m_tvalid(fv), .m_tready(fr), .m_tlast(fl));
      grv_oreg #(.W(IW), .OREG(OREG)) u_o0 (.clk(clk), .rst_n(rst_n), .s_tdata(fd[0 +: IW]), .s_tvalid(fv[0]), .s_tready(fr[0]),
        .s_tlast(fl[0]), .m_tdata(m_tdata[0 +: IW]), .m_tvalid(m_tvalid[0]), .m_tready(m_tready[0]), .m_tlast(m_tlast[0]));
      grv_oreg #(.W(IW), .OREG(OREG)) u_o1 (.clk(clk), .rst_n(rst_n), .s_tdata(fd[3*IW +: IW]), .s_tvalid(fv[1]), .s_tready(fr[1]),
        .s_tlast(fl[1]), .m_tdata(m_tdata[IW +: IW]), .m_tvalid(m_tvalid[1]), .m_tready(m_tready[1]), .m_tlast(m_tlast[1]));
    end
  endgenerate
endmodule

`default_nettype wire
