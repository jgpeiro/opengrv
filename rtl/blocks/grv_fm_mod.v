// grv_fm_mod - analog_frequency_modulator_fc (PM = 0: phase += (x * k) >>> KSH, then exp) and
// analog_phase_modulator_fc (PM = 1: phase = (x * k) >>> KSH). exp(j phase) from grv_sincos,
// resized from s18.17 (SHIFT). k = cfg_k (signed KW bits). Latency 4 + OREG.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_fm_mod #(
  parameter integer IW    = 16,
  parameter integer KW    = 18,
  parameter integer KSH   = 0,
  parameter integer PM    = 0,
  parameter integer OW    = 16,
  parameter integer SHIFT = 2,
  parameter integer ROUND = 1,
  parameter integer SAT   = 1,
  parameter integer OREG  = 1
)(
  input  wire            clk,
  input  wire            rst_n,
  input  wire [IW-1:0]   s_tdata,
  input  wire            s_tvalid,
  output wire            s_tready,
  input  wire            s_tlast,
  input  wire [KW-1:0]   cfg_k,
  output wire [2*OW-1:0] m_tdata,
  output wire            m_tvalid,
  input  wire            m_tready,
  output wire            m_tlast,
  output wire            ovf
);
  localparam integer PW = IW + KW;
  wire ce, pv, pr;
  wire [4:1] v;
  grv_pctl #(.L(4)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(s_tvalid), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));
  assign s_tready = ce;
  reg  signed [PW-1:0] p1;
  reg  [31:0] ph;
  reg  [3:0]  l;
  wire signed [PW+31:0] pe = p1;
  wire signed [PW+31:0] ps = pe >>> KSH;
  wire [31:0] inc = ps[31:0];
  wire [31:0] phn = (PM != 0) ? inc : ph + inc;
  always @(posedge clk) begin
    if (ce) begin
      p1 <= $signed(s_tdata) * $signed(cfg_k);
      l  <= {l[2:0], s_tlast};
    end
    if (!rst_n) ph <= 32'd0;
    else if (ce && v[1]) ph <= phn;
  end
  wire signed [17:0] co, si;
  grv_sincos u_sc (.clk(clk), .ce(ce), .phase(phn[31:20]), .cos_o(co), .sin_o(si));
  wire [OW-1:0] rr, ri;
  wire          ovr, ovi;
  grv_resize #(.GW(18), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_rr (.x(co), .y(rr), .ovf(ovr));
  grv_resize #(.GW(18), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_ri (.x(si), .y(ri), .ovf(ovi));
  reg [2*OW-1:0] o4;
  reg            ov4;
  always @(posedge clk) if (ce) begin o4 <= {ri, rr}; ov4 <= v[3] & (ovr | ovi); end
  assign ovf = ov4 & ce & v[4];
  grv_oreg #(.W(2*OW), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o4), .s_tvalid(pv), .s_tready(pr),
    .s_tlast(l[3]), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
