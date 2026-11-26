// grv_dc_blocker - dc_blocker_xx (short form) as GNU Radio: two moving averages of length D and
// the input delayed by D-1:  y = x[n-(D-1)] - MA(MA(x))[n]. Computed exactly as
//   S1 = sum of D inputs, S2 = sum of D values of S1, y = resize((x[n-D+1]*D*D - S2) * K)
// with K / 2^SHIFT = 1 / D^2 (K = 1 when D is a power of two). Latency 6 + OREG.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_dc_blocker #(
  parameter integer IW    = 16,
  parameter integer CPLX  = 0,
  parameter integer D     = 32,
  parameter integer KW    = 18,
  parameter integer K     = 1,
  parameter integer OW    = 16,
  parameter integer SHIFT = 10,
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
  localparam integer NC  = CPLX + 1;
  localparam integer AW1 = $clog2(D);
  localparam integer S1W = IW + AW1 + 2;
  localparam integer S2W = S1W + AW1 + 1;
  localparam integer YW  = S2W + 2;
  localparam integer PW  = YW + KW;
  wire ce, pv, pr;
  wire [6:1] v;
  grv_pctl #(.L(6)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(s_tvalid), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));
  assign s_tready = ce;
  wire take = ce && s_tvalid;
  // pointers and fill flags
  reg [AW1:0] p1, p3, p2;
  reg [31:0]  n1, n2;
  always @(posedge clk) begin
    if (!rst_n) begin
      p1 <= 0; p3 <= 0; p2 <= 0; n1 <= 0; n2 <= 0;
    end else begin
      if (take) begin
        p1 <= (p1 == D - 1) ? 0 : p1 + 1'b1;
        p3 <= (p3 == D - 2) ? 0 : p3 + 1'b1;
        if (n1 < D) n1 <= n1 + 1'b1;
      end
      if (ce && v[2]) begin
        p2 <= (p2 == D - 1) ? 0 : p2 + 1'b1;
        if (n2 < D) n2 <= n2 + 1'b1;
      end
    end
  end
  reg  [6:1] l;
  reg        z1o, z3o, z2o;
  always @(posedge clk) if (ce) begin
    l   <= {l[5:1], s_tlast};
    z1o <= (n1 < D);          // x[n-D] does not exist yet
    z3o <= (n1 < D - 1);      // x[n-D+1] does not exist yet
  end
  wire [OW*NC-1:0] r;
  wire [NC-1:0]    ov;
  genvar c;
  generate
    for (c = 0; c < NC; c = c + 1) begin : g_c
      reg [IW-1:0]  m1 [0:D-1];
      reg [IW-1:0]  m3 [0:D-2];
      reg [S1W-1:0] m2 [0:D-1];
      reg signed [IW-1:0]  xo1, xd1, x1, xd2, xd3, xd4;
      reg signed [S1W-1:0] s1, s1n, s1o;
      reg signed [S2W-1:0] s2, s2n;
      reg signed [PW-1:0]  y5;
      reg z2;
      wire signed [IW-1:0] xin = s_tdata[c*IW +: IW];
      // stage 1: read x[n-D], x[n-D+1]; write x
      always @(posedge clk) if (ce) begin
        xo1 <= m1[p1[AW1-1:0]];
        xd1 <= m3[p3[AW1-1:0]];
        if (take) begin
          m1[p1[AW1-1:0]] <= xin;
          m3[p3[AW1-1:0]] <= xin;
        end
        x1 <= xin;
      end
      // stage 2: S1
      wire signed [S1W-1:0] s1next = s1 + x1 - (z1o ? $signed({IW{1'b0}}) : xo1);
      always @(posedge clk) begin
        if (!rst_n) s1 <= 0;
        else if (ce && v[1]) s1 <= s1next;
        if (ce) begin s1n <= s1next; xd2 <= z3o ? $signed({IW{1'b0}}) : xd1; end
      end
      // stage 3: read S1[n-D], write S1[n]
      always @(posedge clk) if (ce) begin
        s1o <= m2[p2[AW1-1:0]];
        if (v[2]) m2[p2[AW1-1:0]] <= s1n;
        z2  <= (n2 < D);
        xd3 <= xd2;
      end
      // stage 4: S2
      reg signed [S1W-1:0] s1n3;
      always @(posedge clk) if (ce) s1n3 <= s1n;
      wire signed [S2W-1:0] s2next = s2 + s1n3 - (z2 ? $signed({S1W{1'b0}}) : s1o);
      always @(posedge clk) begin
        if (!rst_n) s2 <= 0;
        else if (ce && v[3]) s2 <= s2next;
        if (ce) begin s2n <= s2next; xd4 <= xd3; end
      end
      // stage 5: y * K
      wire signed [YW-1:0] y = $signed(xd4) * (D * D) - s2n;
      always @(posedge clk) if (ce) y5 <= y * $signed(K);
      grv_resize #(.GW(PW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_r (.x(y5), .y(r[c*OW +: OW]), .ovf(ov[c]));
    end
  endgenerate
  reg [OW*NC-1:0] o6;
  reg             ov6;
  always @(posedge clk) if (ce) begin o6 <= r; ov6 <= v[5] & |ov; end
  assign ovf = ov6 & ce & v[6];
  grv_oreg #(.W(OW*NC), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o6), .s_tvalid(pv), .s_tready(pr),
    .s_tlast(l[6]), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
