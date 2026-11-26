// grv_iir1 - single_pole_iir_filter_xx: s += (((x << G) - s) * alpha) >>> AF ; y = resize(s).
// alpha = cfg_alpha (unsigned, AW bits, AF fraction bits). The state s carries G guard bits.
// Feedback: one sample every 3 clocks. Also the average of grv_squelch.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_iir1 #(
  parameter integer IW    = 16,
  parameter integer CPLX  = 0,
  parameter integer G     = 8,
  parameter integer AW    = 18,
  parameter integer AF    = 17,
  parameter integer OW    = 16,
  parameter integer SHIFT = 8,
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
  input  wire [AW-1:0]          cfg_alpha,
  output wire [OW*(CPLX+1)-1:0] m_tdata,
  output wire                   m_tvalid,
  input  wire                   m_tready,
  output wire                   m_tlast,
  output wire                   ovf
);
  localparam integer NC = CPLX + 1;
  localparam integer SW = IW + G + 2;
  localparam integer PW = SW + AW + 1;
  localparam [1:0] S_IDLE = 2'd0, S_MUL = 2'd1, S_UPD = 2'd2, S_OUT = 2'd3;
  reg [1:0] st;
  reg       lt;
  wire      o_r;
  assign s_tready = (st == S_IDLE);
  wire [OW*NC-1:0] r;
  wire [NC-1:0]    ov;
  reg  [OW*NC-1:0] o;
  reg              ovq;
  genvar c;
  generate
    for (c = 0; c < NC; c = c + 1) begin : g_c
      reg  signed [SW-1:0] s, d;
      reg  signed [PW-1:0] p;
      wire signed [SW-1:0] xs = $signed(s_tdata[c*IW +: IW]) <<< G;
      wire signed [SW-1:0] sn = s + (p >>> AF);
      always @(posedge clk) begin
        if (!rst_n) s <= {SW{1'b0}};
        else begin
          if (st == S_IDLE && s_tvalid) d <= xs - s;
          if (st == S_MUL) p <= d * $signed({1'b0, cfg_alpha});
          if (st == S_UPD) s <= sn;
        end
      end
      grv_resize #(.GW(SW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_r (.x(sn), .y(r[c*OW +: OW]), .ovf(ov[c]));
    end
  endgenerate
  always @(posedge clk) begin
    ovq <= 1'b0;
    if (!rst_n) st <= S_IDLE;
    else case (st)
      S_IDLE: if (s_tvalid) begin st <= S_MUL; lt <= s_tlast; end
      S_MUL:  st <= S_UPD;
      S_UPD:  begin o <= r; ovq <= |ov; st <= S_OUT; end
      default: if (o_r) st <= S_IDLE;
    endcase
  end
  assign ovf = ovq;
  grv_oreg #(.W(OW*NC), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o), .s_tvalid(st == S_OUT), .s_tready(o_r),
    .s_tlast(lt), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
