// grv_agc - analog_agc_xx: y = resize(x * g) ; g += ((ref - |y|) * rate) >>> RSH ;
// g <= max when MAXEN and g > max. |y| for complex samples: (30*max(|I|,|Q|) + 15*min) >>> 5
// (15/16 max + 15/32 min, error within -6.25 % .. +4.8 %). g: signed GW bits, reset value G0.
// One sample every 6 clocks.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_agc #(
  parameter integer IW    = 16,
  parameter integer CPLX  = 1,
  parameter integer GW    = 24,
  parameter integer G0    = 65536,
  parameter integer OW    = 16,
  parameter integer SHIFT = 16,
  parameter integer RW    = 18,
  parameter integer RSH   = 20,
  parameter integer MAXEN = 1,
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
  input  wire [RW-1:0]          cfg_rate,
  input  wire [OW-1:0]          cfg_ref,
  input  wire [GW-1:0]          cfg_max,
  output wire [OW*(CPLX+1)-1:0] m_tdata,
  output wire                   m_tvalid,
  input  wire                   m_tready,
  output wire                   m_tlast,
  output wire [GW-1:0]          st_gain,
  output wire                   ovf
);
  localparam integer NC = CPLX + 1;
  localparam integer PW = IW + GW;
  localparam integer MW = OW + 7;
  localparam integer EW = MW + RW + 2;
  localparam [2:0] S_IDLE = 3'd0, S_Y = 3'd1, S_E = 3'd2, S_G = 3'd3, S_UPD = 3'd4, S_OUT = 3'd5;
  reg  [2:0] st;
  reg        lt;
  wire       o_r;
  reg  signed [GW-1:0] g;
  reg  signed [PW-1:0] pr_, pi_;
  reg  [OW*NC-1:0]     y;
  reg  signed [MW-1:0] mag;
  reg  signed [EW-1:0] e;
  reg                  ovq;
  assign s_tready = (st == S_IDLE);
  assign st_gain = g;
  wire signed [IW-1:0] xr = s_tdata[0 +: IW];
  wire signed [IW-1:0] xi = s_tdata[IW*CPLX +: IW];
  wire [OW-1:0] yr, yi;
  wire          ovr, ovi;
  grv_resize #(.GW(PW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_rr (.x(pr_), .y(yr), .ovf(ovr));
  grv_resize #(.GW(PW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_ri (.x(pi_), .y(yi), .ovf(ovi));
  wire signed [OW:0] ar = yr[OW-1] ? -$signed({yr[OW-1], yr}) : $signed({yr[OW-1], yr});
  wire signed [OW:0] ai = yi[OW-1] ? -$signed({yi[OW-1], yi}) : $signed({yi[OW-1], yi});
  wire signed [OW:0] mx = (ar > ai) ? ar : ai;
  wire signed [OW:0] mn = (ar > ai) ? ai : ar;
  wire signed [MW-1:0] m_c = ($signed({{(MW-OW-1){1'b0}}, mx}) * 30 + $signed({{(MW-OW-1){1'b0}}, mn}) * 15) >>> 5;
  wire signed [MW-1:0] m_r = $signed({{(MW-OW-1){1'b0}}, ar});
  wire signed [MW-1:0] err = $signed({{(MW-OW){cfg_ref[OW-1]}}, cfg_ref}) - mag;
  wire signed [GW+1:0] gn  = g + (e >>> RSH);
  wire signed [GW+1:0] gmx = $signed({2'b00, cfg_max});
  always @(posedge clk) begin
    ovq <= 1'b0;
    if (!rst_n) begin
      st <= S_IDLE; g <= G0;
    end else case (st)
      S_IDLE: if (s_tvalid) begin
        pr_ <= xr * g;
        pi_ <= xi * g;
        lt  <= s_tlast;
        st  <= S_Y;
      end
      S_Y: begin
        y   <= (CPLX != 0) ? {yi, yr} : yr;
        ovq <= ovr | (ovi & (CPLX != 0));
        mag <= (CPLX != 0) ? m_c : m_r;
        st  <= S_E;
      end
      S_E: begin
        e  <= err * $signed({1'b0, cfg_rate});
        st <= S_G;
      end
      S_G: begin
        g  <= (MAXEN != 0 && gn > gmx) ? cfg_max : gn[GW-1:0];
        st <= S_OUT;
      end
      default: if (o_r) st <= S_IDLE;
    endcase
  end
  assign ovf = ovq;
  grv_oreg #(.W(OW*NC), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(y), .s_tvalid(st == S_OUT), .s_tready(o_r),
    .s_tlast(lt), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
