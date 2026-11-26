// grv_mixer - blocks_rotator_cc and the mixer of grv_xlating_fir: y[n] = x[n] * exp(j*p[n]),
// p[0] = 0, p[n+1] = p[n] + cfg_freq (32 bits = 2*pi). Real or complex input, complex output.
// exp from grv_sincos (s18.17); exact product resized (SHIFT). Latency 5 + OREG.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_mixer #(
  parameter integer IW    = 16,
  parameter integer ICPLX = 1,
  parameter integer OW    = 16,
  parameter integer SHIFT = 17,
  parameter integer ROUND = 1,
  parameter integer SAT   = 1,
  parameter integer OREG  = 1
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
  localparam integer PW = IW + 18;
  localparam integer GW = PW + 1;
  wire ce, pv, pr;
  wire [5:1] v;
  grv_pctl #(.L(5)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(s_tvalid), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));
  assign s_tready = ce;
  reg [31:0] ph;
  always @(posedge clk)
    if (!rst_n) ph <= 32'd0;
    else if (ce && s_tvalid) ph <= ph + cfg_freq;
  wire signed [17:0] co, si;
  grv_sincos u_sc (.clk(clk), .ce(ce), .phase(ph[31:20]), .cos_o(co), .sin_o(si));
  reg [IW*(ICPLX+1)-1:0] x1, x2;
  reg [4:0] l;
  always @(posedge clk) if (ce) begin x1 <= s_tdata; x2 <= x1; l <= {l[3:0], s_tlast}; end
  wire signed [IW-1:0] xr = x2[0 +: IW];
  wire signed [IW-1:0] xi = (ICPLX != 0) ? x2[IW*ICPLX +: IW] : {IW{1'b0}};
  reg  signed [PW-1:0] p_rc, p_is, p_rs, p_ic;
  reg  signed [GW-1:0] re, im;
  always @(posedge clk) if (ce) begin
    p_rc <= xr * co;
    p_is <= xi * si;
    p_rs <= xr * si;
    p_ic <= xi * co;
    re   <= p_rc - p_is;
    im   <= p_rs + p_ic;
  end
  wire [OW-1:0] rr, ri;
  wire          ovr, ovi;
  grv_resize #(.GW(GW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_rr (.x(re), .y(rr), .ovf(ovr));
  grv_resize #(.GW(GW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_ri (.x(im), .y(ri), .ovf(ovi));
  reg [2*OW-1:0] o5;
  reg            ov5;
  always @(posedge clk) if (ce) begin o5 <= {ri, rr}; ov5 <= v[4] & (ovr | ovi); end
  assign ovf = ov5 & ce & v[5];
  grv_oreg #(.W(2*OW), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o5), .s_tvalid(pv), .s_tready(pr),
    .s_tlast(l[4]), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
