// grv_convert - stream format conversion: optional multiplication by a constant K, then
// grv_resize (round, shift, saturate). Real or complex (both components alike).
// GRC: blocks_float_to_short, _to_char, _to_int, _to_uchar, blocks_short_to_float, char_to_float,
//      int_to_float, uchar_to_float, blocks_short_to_char, blocks_char_to_short, grv_quantize;
//      also inserted by grvgen where a consumer cannot align its input.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_convert #(
  parameter integer IW      = 16,
  parameter integer CPLX    = 0,
  parameter integer ISIGNED = 1,
  parameter integer OW      = 16,
  parameter integer OSIGNED = 1,
  parameter integer MULK    = 0,     // 1: multiply by K first
  parameter integer KW      = 18,
  parameter integer K       = 1,
  parameter integer SHIFT   = 0,
  parameter integer ROUND   = 1,
  parameter integer SAT     = 1,
  parameter integer OREG    = 1
)(
  input  wire                    clk,
  input  wire                    rst_n,
  input  wire [IW*(CPLX+1)-1:0]  s_tdata,
  input  wire                    s_tvalid,
  output wire                    s_tready,
  input  wire                    s_tlast,
  output wire [OW*(CPLX+1)-1:0]  m_tdata,
  output wire                    m_tvalid,
  input  wire                    m_tready,
  output wire                    m_tlast,
  output wire                    ovf
);
  localparam integer NC = CPLX + 1;
  localparam integer PW = IW + 1 + (MULK != 0 ? KW : 0);
  localparam integer LATENCY = 2 + OREG;

  wire ce, pv, pr;
  wire [2:1] v;
  grv_pctl #(.L(2)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(s_tvalid), .out_ready(pr),
                           .ce(ce), .out_valid(pv), .v(v));
  assign s_tready = ce;

  reg  [PW*NC-1:0] p1;
  reg  [OW*NC-1:0] o2;
  reg  [1:0]       l;
  reg              ov2;
  wire [OW*NC-1:0] o1;
  wire [NC-1:0]    ovs;
  wire signed [KW-1:0] kc = K;

  genvar c;
  generate
    for (c = 0; c < NC; c = c + 1) begin : g_c
      wire [IW-1:0] xc = s_tdata[c*IW +: IW];
      wire signed [IW:0] xs = (ISIGNED != 0) ? {xc[IW-1], xc} : {1'b0, xc};
      always @(posedge clk) if (ce) begin
        if (MULK != 0) p1[c*PW +: PW] <= xs * kc;
        else           p1[c*PW +: PW] <= {{(PW-IW-1){xs[IW]}}, xs};
      end
      grv_resize #(.GW(PW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT), .ISIGNED(1), .OSIGNED(OSIGNED))
        u_rs (.x(p1[c*PW +: PW]), .y(o1[c*OW +: OW]), .ovf(ovs[c]));
    end
  endgenerate

  always @(posedge clk) if (ce) begin
    o2  <= o1;
    l   <= {l[0], s_tlast};
    ov2 <= |ovs & v[1];
  end
  assign ovf = ov2 & ce & v[2];

  generate
    if (OREG != 0) begin : g_oreg
      grv_skid #(.W(OW*NC)) u_skid (.clk(clk), .rst_n(rst_n), .s_tdata(o2), .s_tvalid(pv), .s_tready(pr),
        .s_tlast(l[1]), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
    end else begin : g_noreg
      assign m_tdata = o2; assign m_tvalid = pv; assign pr = m_tready; assign m_tlast = l[1];
    end
  endgenerate
endmodule

`default_nettype wire
