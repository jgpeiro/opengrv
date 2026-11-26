// grv_multiply_const - blocks_multiply_const_xx / _vxx: x * k with a runtime constant.
// Real or complex input (ICPLX), real or complex constant (KCPLX); the output is complex if
// either is. Exact product, then resize. Latency 3 + OREG.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_multiply_const #(
  parameter integer IW    = 16,
  parameter integer ICPLX = 0,
  parameter integer KW    = 18,
  parameter integer KCPLX = 0,
  parameter integer OW    = 16,
  parameter integer SHIFT = 15,
  parameter integer ROUND = 1,
  parameter integer SAT   = 1,
  parameter integer OREG  = 1
)(
  input  wire                                clk,
  input  wire                                rst_n,
  input  wire [IW*(ICPLX+1)-1:0]             s_tdata,
  input  wire                                s_tvalid,
  output wire                                s_tready,
  input  wire                                s_tlast,
  input  wire [KW*(KCPLX+1)-1:0]             cfg_k,
  output wire [OW*((ICPLX|KCPLX)+1)-1:0]     m_tdata,
  output wire                                m_tvalid,
  input  wire                                m_tready,
  output wire                                m_tlast,
  output wire                                ovf
);
  localparam integer OC = ((ICPLX != 0) || (KCPLX != 0)) ? 1 : 0;
  localparam integer NC = OC + 1;
  localparam integer PW = IW + KW;
  localparam integer GW = PW + 1;
  localparam integer LATENCY = 3 + OREG;

  wire ce, pv, pr;
  wire [3:1] v;
  grv_pctl #(.L(3)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(s_tvalid), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));
  assign s_tready = ce;

  wire signed [IW-1:0] xr = s_tdata[0 +: IW];
  wire signed [IW-1:0] xi = (ICPLX != 0) ? s_tdata[IW*ICPLX +: IW] : {IW{1'b0}};
  wire signed [KW-1:0] kr = cfg_k[0 +: KW];
  wire signed [KW-1:0] ki = (KCPLX != 0) ? cfg_k[KW*KCPLX +: KW] : {KW{1'b0}};
  reg  signed [PW-1:0] p_rr, p_ii, p_ri, p_ir;
  reg  signed [GW-1:0] re, im;
  always @(posedge clk) if (ce) begin
    p_rr <= xr * kr;
    p_ii <= xi * ki;
    p_ri <= xr * ki;
    p_ir <= xi * kr;
    re   <= p_rr - p_ii;
    im   <= p_ri + p_ir;
  end
  wire [OW-1:0] rr, ri;
  wire          ovr, ovi;
  grv_resize #(.GW(GW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_rr (.x(re), .y(rr), .ovf(ovr));
  grv_resize #(.GW(GW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_ri (.x(im), .y(ri), .ovf(ovi));
  reg [OW*NC-1:0] o3;
  reg [2:0]       l;
  reg             ov3;
  always @(posedge clk) if (ce) begin
    o3  <= (OC != 0) ? {ri, rr} : rr;
    l   <= {l[1:0], s_tlast};
    ov3 <= v[2] & (ovr | (ovi & (OC != 0)));
  end
  assign ovf = ov3 & ce & v[3];

  grv_oreg #(.W(OW*NC), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o3), .s_tvalid(pv), .s_tready(pr),
    .s_tlast(l[2]), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
