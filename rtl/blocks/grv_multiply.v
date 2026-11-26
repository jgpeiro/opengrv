// grv_multiply - blocks_multiply_xx (2 inputs), blocks_multiply_conjugate_cc (CONJ=1: a * conj(b)).
// Exact product (complex: 4 products), then resize. Latency 3 + OREG.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_multiply #(
  parameter integer IW    = 16,
  parameter integer CPLX  = 0,
  parameter integer CONJ  = 0,
  parameter integer OW    = 16,
  parameter integer SHIFT = 15,
  parameter integer ROUND = 1,
  parameter integer SAT   = 1,
  parameter integer OREG  = 1
)(
  input  wire                     clk,
  input  wire                     rst_n,
  input  wire [2*IW*(CPLX+1)-1:0] s_tdata,
  input  wire [1:0]               s_tvalid,
  output wire [1:0]               s_tready,
  input  wire [1:0]               s_tlast,
  output wire [OW*(CPLX+1)-1:0]   m_tdata,
  output wire                     m_tvalid,
  input  wire                     m_tready,
  output wire                     m_tlast,
  output wire                     ovf
);
  localparam integer NC = CPLX + 1;
  localparam integer PW = 2 * IW;
  localparam integer GW = PW + 1;
  localparam integer LATENCY = 3 + OREG;

  wire all_v = &s_tvalid;
  wire ce, pv, pr;
  wire [3:1] v;
  grv_pctl #(.L(3)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(all_v), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));
  assign s_tready = {2{ce && all_v}};

  wire signed [IW-1:0] ar = s_tdata[0 +: IW];
  wire signed [IW-1:0] ai = s_tdata[IW*(NC-1) +: IW];
  wire signed [IW-1:0] br = s_tdata[IW*NC +: IW];
  wire signed [IW-1:0] bi = s_tdata[IW*NC + IW*(NC-1) +: IW];
  reg  signed [PW-1:0] p_rr, p_ii, p_ri, p_ir;
  reg  signed [GW-1:0] re, im;
  always @(posedge clk) if (ce) begin
    p_rr <= ar * br;
    p_ii <= ai * bi;
    p_ri <= ar * bi;
    p_ir <= ai * br;
    if (CPLX == 0) begin
      re <= p_rr;
      im <= {GW{1'b0}};
    end else if (CONJ == 0) begin
      re <= p_rr - p_ii;
      im <= p_ri + p_ir;
    end else begin
      re <= p_rr + p_ii;
      im <= p_ir - p_ri;
    end
  end
  wire [OW-1:0] rr, ri;
  wire          ovr, ovi;
  grv_resize #(.GW(GW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_rr (.x(re), .y(rr), .ovf(ovr));
  grv_resize #(.GW(GW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_ri (.x(im), .y(ri), .ovf(ovi));
  reg [OW*NC-1:0] o3;
  reg [2:0]       l;
  reg             ov3;
  always @(posedge clk) if (ce) begin
    o3  <= (CPLX != 0) ? {ri, rr} : rr;
    l   <= {l[1:0], s_tlast[0]};
    ov3 <= v[2] & (ovr | (ovi & (CPLX != 0)));
  end
  assign ovf = ov3 & ce & v[3];

  grv_oreg #(.W(OW*NC), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o3), .s_tvalid(pv), .s_tready(pr),
    .s_tlast(l[2]), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
