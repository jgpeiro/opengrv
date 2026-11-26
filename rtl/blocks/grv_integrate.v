// grv_integrate - blocks_integrate_xx: the sum of every D consecutive inputs is one output,
// resized. tlast from the last input of the group. Latency 2 + OREG.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_integrate #(
  parameter integer IW    = 16,
  parameter integer CPLX  = 0,
  parameter integer D     = 4,
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
  output wire [OW*(CPLX+1)-1:0] m_tdata,
  output wire                   m_tvalid,
  input  wire                   m_tready,
  output wire                   m_tlast,
  output wire                   ovf
);
  localparam integer NC = CPLX + 1;
  localparam integer GW = IW + $clog2(D + 1) + 1;
  localparam integer CW = (D > 1) ? $clog2(D) : 1;
  reg  [CW-1:0] cnt;
  wire          last_in = (cnt == D - 1);
  wire ce, pv, pr;
  wire [2:1] v;
  grv_pctl #(.L(2)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(s_tvalid && last_in), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));
  assign s_tready = last_in ? ce : 1'b1;
  wire take = s_tvalid && s_tready;
  always @(posedge clk)
    if (!rst_n) cnt <= 0;
    else if (take) cnt <= last_in ? {CW{1'b0}} : cnt + 1'b1;
  wire [OW*NC-1:0] r;
  wire [NC-1:0]    ov;
  genvar c;
  generate
    for (c = 0; c < NC; c = c + 1) begin : g_c
      reg  signed [GW-1:0] acc, s1;
      wire signed [GW-1:0] x = $signed(s_tdata[c*IW +: IW]);
      always @(posedge clk) begin
        if (!rst_n) acc <= {GW{1'b0}};
        else if (take) acc <= last_in ? {GW{1'b0}} : acc + x;
        if (ce) s1 <= acc + x;
      end
      grv_resize #(.GW(GW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_r (.x(s1), .y(r[c*OW +: OW]), .ovf(ov[c]));
    end
  endgenerate
  reg [OW*NC-1:0] o2;
  reg [1:0]       l;
  reg             ov2;
  always @(posedge clk) if (ce) begin o2 <= r; l <= {l[0], s_tlast}; ov2 <= v[1] & |ov; end
  assign ovf = ov2 & ce & v[2];
  grv_oreg #(.W(OW*NC), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o2), .s_tvalid(pv), .s_tready(pr),
    .s_tlast(l[1]), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
