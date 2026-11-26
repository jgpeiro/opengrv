// grv_costas - digital_costas_loop_cc (order 2 or 4), as GNU Radio:
//   y = x * exp(-j phase)                     (grv_sincos, exact product resized: SHIFT)
//   order 2: e = yI * yQ ; order 4: e = sgn(yI)*yQ - sgn(yQ)*yI   (sgn(0) = -1)
//   e -> EW bits, EF fraction bits (shift SHE, floor), clipped to +-2^EF (= +-1.0)
//   freq += (e * kb) >>> SB ; phase += freq + ((e * ka) >>> SA) ; then freq clamped to +-FMAX
// phase and freq in units of 2*pi / 2^32. One sample every 8 clocks.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_costas #(
  parameter integer IW    = 16,
  parameter integer OW    = 16,
  parameter integer SHIFT = 17,
  parameter integer ORDER = 2,
  parameter integer EW    = 18,
  parameter integer EF    = 15,
  parameter integer SHE   = 15,
  parameter integer KW    = 24,
  parameter integer SA    = 15,
  parameter integer SB    = 15,
  parameter [31:0]  FMAX  = 32'd683565276,
  parameter integer ROUND = 1,
  parameter integer SAT   = 1,
  parameter integer OREG  = 1
)(
  input  wire            clk,
  input  wire            rst_n,
  input  wire [2*IW-1:0] s_tdata,
  input  wire            s_tvalid,
  output wire            s_tready,
  input  wire            s_tlast,
  input  wire [KW-1:0]   cfg_ka,
  input  wire [KW-1:0]   cfg_kb,
  output wire [2*OW-1:0] m_tdata,
  output wire            m_tvalid,
  input  wire            m_tready,
  output wire            m_tlast,
  output wire [31:0]     st_freq,
  output wire [31:0]     st_phase,
  output wire            ovf
);
  localparam integer PW = IW + 18;
  localparam integer QW = 2 * OW + 2;
  localparam integer KP = EW + KW;
  localparam [3:0] S_IDLE = 4'd0, S_W1 = 4'd1, S_W2 = 4'd2, S_P = 4'd3, S_Y = 4'd4, S_E = 4'd5,
                   S_K = 4'd6, S_L = 4'd7, S_OUT = 4'd8;
  reg  [3:0] st;
  reg        lt, ovq;
  wire       o_r;
  reg  [31:0] ph, fr;
  reg  signed [IW-1:0] xr, xi;
  reg  signed [PW-1:0] p_rc, p_is, p_ic, p_rs;
  reg  [OW-1:0] yr, yi;
  reg  signed [EW-1:0] e;
  reg  signed [KP-1:0] ea, eb;
  assign s_tready = (st == S_IDLE);
  assign st_freq = fr;
  assign st_phase = ph;
  wire signed [17:0] co, si;
  grv_sincos u_sc (.clk(clk), .ce(1'b1), .phase(ph[31:20]), .cos_o(co), .sin_o(si));
  wire [OW-1:0] rr, ri;
  wire          ovr, ovi;
  wire signed [PW:0] sum_r = p_rc + p_is;
  wire signed [PW:0] sum_i = p_ic - p_rs;
  grv_resize #(.GW(PW+1), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_rr (.x(sum_r), .y(rr), .ovf(ovr));
  grv_resize #(.GW(PW+1), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_ri (.x(sum_i), .y(ri), .ovf(ovi));
  // phase detector
  wire signed [OW-1:0] syr = yr;
  wire signed [OW-1:0] syi = yi;
  wire signed [QW-1:0] e2  = syr * syi;
  wire signed [QW-1:0] e4  = ((syr > 0) ? $signed({{(QW-OW){syi[OW-1]}}, syi}) : -$signed({{(QW-OW){syi[OW-1]}}, syi}))
                           - ((syi > 0) ? $signed({{(QW-OW){syr[OW-1]}}, syr}) : -$signed({{(QW-OW){syr[OW-1]}}, syr}));
  wire [EW-1:0] er;
  grv_resize #(.GW(QW), .OW(EW), .SHIFT(SHE), .ROUND(0), .SAT(1)) u_re (.x((ORDER == 2) ? e2 : e4), .y(er), .ovf());
  wire signed [EW-1:0] ers = er;
  wire signed [EW-1:0] one = $signed({{(EW-1){1'b0}}, 1'b1}) <<< EF;
  wire signed [EW-1:0] ec  = (ers > one) ? one : (ers < -one) ? -one : ers;
  // loop
  wire signed [31:0] fn  = $signed(fr) + (eb >>> SB);
  wire signed [31:0] phn = $signed(ph) + fn + (ea >>> SA);
  wire signed [31:0] fmx = FMAX;
  always @(posedge clk) begin
    ovq <= 1'b0;
    if (!rst_n) begin
      st <= S_IDLE; ph <= 32'd0; fr <= 32'd0;
    end else case (st)
      S_IDLE: if (s_tvalid) begin
        xr <= s_tdata[0 +: IW]; xi <= s_tdata[IW +: IW]; lt <= s_tlast; st <= S_W1;
      end
      S_W1: st <= S_W2;
      S_W2: begin
        p_rc <= xr * co; p_is <= xi * si; p_ic <= xi * co; p_rs <= xr * si; st <= S_P;
      end
      S_P: begin yr <= rr; yi <= ri; ovq <= ovr | ovi; st <= S_Y; end
      S_Y: begin e <= ec; st <= S_E; end
      S_E: begin ea <= e * $signed(cfg_ka); eb <= e * $signed(cfg_kb); st <= S_K; end
      S_K: begin
        fr <= (fn > fmx) ? fmx : (fn < -fmx) ? -fmx : fn;
        ph <= phn;
        st <= S_OUT;
      end
      default: if (o_r) st <= S_IDLE;
    endcase
  end
  assign ovf = ovq;
  grv_oreg #(.W(2*OW), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata({yi, yr}), .s_tvalid(st == S_OUT),
    .s_tready(o_r), .s_tlast(lt), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
