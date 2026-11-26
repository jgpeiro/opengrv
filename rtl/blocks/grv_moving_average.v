// grv_moving_average - blocks_moving_average_xx: S[n] = sum of the last LEN inputs (zeros before
// the first), y = resize(S * K). Delay line of LEN samples with read-before-write.
// Latency 4 + OREG.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_moving_average #(
  parameter integer IW    = 16,
  parameter integer CPLX  = 0,
  parameter integer LEN   = 16,
  parameter integer KW    = 18,
  parameter integer K     = 1,
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
  localparam integer AW = (LEN > 1) ? $clog2(LEN) : 1;
  localparam integer SW = IW + $clog2(LEN + 1) + 1;
  localparam integer PW = SW + KW;
  wire ce, pv, pr;
  wire [4:1] v;
  grv_pctl #(.L(4)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(s_tvalid), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));
  assign s_tready = ce;
  wire take = ce && s_tvalid;

  reg [IW*NC-1:0] mem [0:LEN-1];
  reg [IW*NC-1:0] old1, x1;
  reg [AW-1:0]    ptr;
  reg             filled, z1;
  always @(posedge clk) if (ce) begin
    old1 <= mem[ptr];
    if (take) mem[ptr] <= s_tdata;
    x1 <= s_tdata;
    z1 <= !filled;
  end
  always @(posedge clk) begin
    if (!rst_n) begin
      ptr <= 0; filled <= 1'b0;
    end else if (take) begin
      ptr <= (ptr == LEN - 1) ? {AW{1'b0}} : ptr + 1'b1;
      if (ptr == LEN - 1) filled <= 1'b1;
    end
  end
  wire signed [KW-1:0] kk = K;
  wire [OW*NC-1:0] r;
  wire [NC-1:0]    ov;
  genvar c;
  generate
    for (c = 0; c < NC; c = c + 1) begin : g_c
      reg  signed [SW-1:0] s, s2;
      reg  signed [PW-1:0] p3;
      wire signed [SW-1:0] xn = $signed(x1[c*IW +: IW]);
      wire signed [SW-1:0] xo = z1 ? $signed({SW{1'b0}}) : $signed(old1[c*IW +: IW]);
      always @(posedge clk) begin
        if (!rst_n) s <= {SW{1'b0}};
        else if (ce && v[1]) s <= s + xn - xo;
        if (ce) begin
          s2 <= s + xn - xo;
          p3 <= s2 * kk;
        end
      end
      grv_resize #(.GW(PW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_r (.x(p3), .y(r[c*OW +: OW]), .ovf(ov[c]));
    end
  endgenerate
  reg [OW*NC-1:0] o4;
  reg [3:0]       l;
  reg             ov4;
  always @(posedge clk) if (ce) begin
    o4 <= r; l <= {l[2:0], s_tlast}; ov4 <= v[3] & |ov;
  end
  assign ovf = ov4 & ce & v[4];
  grv_oreg #(.W(OW*NC), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o4), .s_tvalid(pv), .s_tready(pr),
    .s_tlast(l[3]), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
