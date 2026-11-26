// grv_cordic_vec - CORDIC vectoring blocks.
//   PRE 0: v = x                          (blocks_complex_to_mag, _to_arg, _to_magphase)
//   PRE 1: v = (x[n] * conj(x[n-1])) >>> PSH (analog_quadrature_demod_cf; x[-1] = 0)
//   CORDIC (PW-bit inputs, ITER iterations): xo = K*|v|, z = atan2 as a 32-bit phase
//   magnitude = resize(xo * KINV, MSHIFT) ; argument = resize((z >>> (32-ZB)) * C, ASHIFT)
//   OUTSEL 0: magnitude, 1: argument, 2: both (two output ports: 0 magnitude, 1 argument)
//   PIPE 1: pipelined, one sample per clock, latency ITER + 4 + OREG
//   PIPE 0: one CORDIC stage used ITER times, one sample per ITER + 5 clocks
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_cordic_vec #(
  parameter integer IW     = 16,
  parameter integer PRE    = 0,
  parameter integer PW     = 16,
  parameter integer PSH    = 0,
  parameter integer ITER   = 18,
  parameter integer PIPE   = 1,
  parameter integer OUTSEL = 0,
  parameter integer KW     = 18,
  parameter integer KINV   = 79594,
  parameter integer MSHIFT = 17,
  parameter integer ZB     = 24,
  parameter integer CW     = 20,
  parameter integer C      = 411775,
  parameter integer ASHIFT = 20,
  parameter integer OW     = 16,
  parameter integer ROUND  = 1,
  parameter integer SAT    = 1,
  parameter integer OREG   = 1
)(
  input  wire                                clk,
  input  wire                                rst_n,
  input  wire [2*IW-1:0]                     s_tdata,
  input  wire                                s_tvalid,
  output wire                                s_tready,
  input  wire                                s_tlast,
  output wire [OW*((OUTSEL==2)?2:1)-1:0]     m_tdata,
  output wire [((OUTSEL==2)?2:1)-1:0]        m_tvalid,
  input  wire [((OUTSEL==2)?2:1)-1:0]        m_tready,
  output wire [((OUTSEL==2)?2:1)-1:0]        m_tlast,
  output wire                                ovf
);
  localparam integer NO = (OUTSEL == 2) ? 2 : 1;
  localparam integer XW = PW + 3;
  localparam integer MW = XW + KW;
  localparam integer AWD = ZB + CW;
  localparam integer QW = 2 * IW + 1;

  // ---------------- pre stage (combinational part)
  wire signed [IW-1:0] xr = s_tdata[0 +: IW];
  wire signed [IW-1:0] xi = s_tdata[IW +: IW];
  reg  signed [IW-1:0] pr_r, pr_i;                 // previous sample
  wire signed [QW-1:0] q_re = xr * pr_r + xi * pr_i;
  wire signed [QW-1:0] q_im = xi * pr_r - xr * pr_i;
  wire signed [QW-1:0] q_re_s = q_re >>> PSH;
  wire signed [QW-1:0] q_im_s = q_im >>> PSH;
  wire [PW-1:0] pre_x = (PRE != 0) ? q_re_s[PW-1:0] : {{(PW-IW){xr[IW-1]}}, xr};
  wire [PW-1:0] pre_y = (PRE != 0) ? q_im_s[PW-1:0] : {{(PW-IW){xi[IW-1]}}, xi};

  // ---------------- post stage (shared)
  wire [XW-1:0] c_xo;
  wire [31:0]   c_zo;
  reg  signed [MW-1:0]  m_mag;
  reg  signed [AWD-1:0] m_arg;
  wire signed [KW-1:0]  kinv = KINV;
  wire signed [CW-1:0]  cc   = C;
  wire signed [ZB-1:0]  zs   = c_zo[31 -: ZB];
  wire [OW-1:0] r_mag, r_arg;
  wire          ov_mag, ov_arg;
  grv_resize #(.GW(MW), .OW(OW), .SHIFT(MSHIFT), .ROUND(ROUND), .SAT(SAT)) u_rm (.x(m_mag), .y(r_mag), .ovf(ov_mag));
  grv_resize #(.GW(AWD), .OW(OW), .SHIFT(ASHIFT), .ROUND(ROUND), .SAT(SAT)) u_ra (.x(m_arg), .y(r_arg), .ovf(ov_arg));
  wire [OW*NO-1:0] r_out = (OUTSEL == 0) ? r_mag : (OUTSEL == 1) ? r_arg : {r_arg, r_mag};
  wire             r_ovf = ((OUTSEL != 1) & ov_mag) | ((OUTSEL != 0) & ov_arg);

  reg  [OW*NO-1:0] o_d;
  reg              o_l;
  wire             o_v, o_r;
  reg              ovp;

  generate
    if (PIPE != 0) begin : g_pipe
      localparam integer L = ITER + 4;
      wire ce;
      wire [L:1] v;
      grv_pctl #(.L(L)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(s_tvalid), .out_ready(o_r), .ce(ce), .out_valid(o_v), .v(v));
      assign s_tready = ce;
      reg [PW-1:0] px, py;
      reg [L-1:0]  lp;
      always @(posedge clk) begin
        if (!rst_n) begin
          pr_r <= 0; pr_i <= 0;
        end else if (ce && s_tvalid) begin
          pr_r <= xr; pr_i <= xi;
        end
        if (ce) begin
          px <= pre_x;
          py <= pre_y;
          lp <= {lp[L-2:0], s_tlast};
        end
      end
      grv_cordic_pipe #(.W(PW), .N(ITER), .MODE(0)) u_c (.clk(clk), .ce(ce), .x(px), .y(py), .z(32'd0),
        .xo(c_xo), .yo(), .zo(c_zo));
      always @(posedge clk) if (ce) begin
        m_mag <= $signed(c_xo) * kinv;
        m_arg <= zs * cc;
        o_d   <= r_out;
        o_l   <= lp[L-2];
        ovp   <= v[L-1] & r_ovf;
      end
      assign ovf = ovp & ce & v[L];
    end else begin : g_iter
      localparam [2:0] S_IDLE = 3'd0, S_RUN = 3'd1, S_MUL = 3'd2, S_RES = 3'd3, S_OUT = 3'd4;
      reg [2:0]    st;
      reg [PW-1:0] px, py;
      reg          lt;
      wire         c_busy, c_done;
      assign s_tready = (st == S_IDLE);
      grv_cordic_iter #(.W(PW), .N(ITER), .MODE(0)) u_c (.clk(clk), .rst_n(rst_n), .start(st == S_RUN && !c_busy && !c_done),
        .x(px), .y(py), .z(32'd0), .busy(c_busy), .done(c_done), .xo(c_xo), .yo(), .zo(c_zo));
      reg started;
      always @(posedge clk) begin
        if (!rst_n) begin
          st <= S_IDLE; pr_r <= 0; pr_i <= 0; started <= 1'b0; ovp <= 1'b0;
        end else begin
          ovp <= 1'b0;
          case (st)
            S_IDLE: if (s_tvalid) begin
              px <= pre_x; py <= pre_y; lt <= s_tlast;
              pr_r <= xr; pr_i <= xi;
              st <= S_RUN; started <= 1'b0;
            end
            S_RUN: begin
              if (!c_busy && !started) started <= 1'b1;
              if (c_done) st <= S_MUL;
            end
            S_MUL: begin
              m_mag <= $signed(c_xo) * kinv;
              m_arg <= zs * cc;
              st <= S_RES;
            end
            S_RES: begin
              o_d <= r_out; o_l <= lt; ovp <= r_ovf; st <= S_OUT;
            end
            default: if (o_r) st <= S_IDLE;
          endcase
        end
      end
      assign o_v = (st == S_OUT);
      assign ovf = ovp;
    end
  endgenerate

  // ---------------- outputs
  generate
    if (NO == 1) begin : g_o1
      grv_oreg #(.W(OW), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o_d), .s_tvalid(o_v), .s_tready(o_r),
        .s_tlast(o_l), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
    end else begin : g_o2
      wire [2*OW-1:0] f_d;
      wire            f_v, f_l;
      wire            f_r;
      wire [4*OW-1:0] fk_d;
      grv_oreg #(.W(2*OW), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o_d), .s_tvalid(o_v), .s_tready(o_r),
        .s_tlast(o_l), .m_tdata(f_d), .m_tvalid(f_v), .m_tready(f_r), .m_tlast(f_l));
      grv_fork #(.W(2*OW), .N(2)) u_f (.clk(clk), .rst_n(rst_n), .s_tdata(f_d), .s_tvalid(f_v), .s_tready(f_r), .s_tlast(f_l),
        .m_tdata(fk_d), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
      assign m_tdata = {fk_d[3*OW +: OW], fk_d[0 +: OW]};
    end
  endgenerate
endmodule

`default_nettype wire
