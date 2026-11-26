// grv_add_const - blocks_add_const_vxx: (x <<< XSH) + (k <<< KSH), resized. Real or complex.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_add_const #(
  parameter integer IW    = 16,
  parameter integer CPLX  = 0,
  parameter integer KW    = 16,
  parameter integer XSH   = 0,
  parameter integer KSH   = 0,
  parameter integer OW    = 16,
  parameter integer SHIFT = 0,
  parameter integer ROUND = 1,
  parameter integer SAT   = 1,
  parameter integer OREG  = 1
)(
  input  wire                   clk,
  input  wire                   rst_n,
  input  wire [IW*(CPLX+1)-1:0] s_tdata,
  input  wire                   s_tvalid,
  output wire                   s_tready,
  input  wire                   s_tlast,
  input  wire [KW*(CPLX+1)-1:0] cfg_k,
  output wire [OW*(CPLX+1)-1:0] m_tdata,
  output wire                   m_tvalid,
  input  wire                   m_tready,
  output wire                   m_tlast,
  output wire                   ovf
);
  localparam integer NC = CPLX + 1;
  localparam integer GW = ((IW + XSH > KW + KSH) ? IW + XSH : KW + KSH) + 1;
  localparam integer LATENCY = 2 + OREG;
  wire ce, pv, pr;
  wire [2:1] v;
  grv_pctl #(.L(2)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(s_tvalid), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));
  assign s_tready = ce;
  wire [OW*NC-1:0] r;
  wire [NC-1:0]    ov;
  genvar c;
  generate
    for (c = 0; c < NC; c = c + 1) begin : g_c
      wire signed [GW-1:0] xe = $signed(s_tdata[c*IW +: IW]) <<< XSH;
      wire signed [GW-1:0] ke = $signed(cfg_k[c*KW +: KW]) <<< KSH;
      reg  signed [GW-1:0] s1;
      always @(posedge clk) if (ce) s1 <= xe + ke;
      grv_resize #(.GW(GW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_r (.x(s1), .y(r[c*OW +: OW]), .ovf(ov[c]));
    end
  endgenerate
  reg [OW*NC-1:0] o2;
  reg [1:0]       l;
  reg             ov2;
  always @(posedge clk) if (ce) begin
    o2 <= r; l <= {l[0], s_tlast}; ov2 <= v[1] & |ov;
  end
  assign ovf = ov2 & ce & v[2];
  grv_oreg #(.W(OW*NC), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o2), .s_tvalid(pv), .s_tready(pr),
    .s_tlast(l[1]), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
