// grv_sig_source - analog_sig_source_x: NCO, quarter-wave sine ROM, waveform, amplitude, offset.
// Real: WAVE 0 const, 1 sin, 2 cos, 3 square (0 / amp), 4 triangle (0 .. amp), 5 saw (0 .. amp).
// Complex: WAVE 0 const (amp + j0), 1 / 2 exp(j phase). Phase advances once per sample:
// out[n] uses phase PHASE0 + n * cfg_freq (32 bits = 2*pi).
//   w (s18.17) -> acc = w * amp + (offset <<< OFSH) -> grv_resize(SHIFT) -> OW
// GRC: analog_sig_source_x, grv_nco_source
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_sig_source #(
  parameter integer OW     = 16,
  parameter integer CPLX   = 0,
  parameter integer WAVE   = 2,
  parameter integer AW     = 18,
  parameter integer OFW    = 18,
  parameter integer OFSH   = 0,
  parameter [31:0]  PHASE0 = 32'd0,
  parameter integer SHIFT  = 17,
  parameter integer ROUND  = 1,
  parameter integer SAT    = 1,
  parameter integer OREG   = 1
)(
  input  wire                   clk,
  input  wire                   rst_n,
  input  wire                   run,
  input  wire [31:0]            cfg_freq,
  input  wire [AW-1:0]          cfg_amp,
  input  wire [OFW-1:0]         cfg_offset,
  input  wire [OFW-1:0]         cfg_offset_q,
  output wire [OW*(CPLX+1)-1:0] m_tdata,
  output wire                   m_tvalid,
  input  wire                   m_tready,
  output wire                   m_tlast,
  output wire                   ovf
);
  localparam integer NC = CPLX + 1;
  localparam integer PW = 18 + AW;
  localparam integer GW = ((PW > OFW + OFSH) ? PW : OFW + OFSH) + 1;
  localparam integer LATENCY = 5 + OREG;

  wire ce, pv, pr;
  wire [5:1] v;
  grv_pctl #(.L(5)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(run), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));

  reg [31:0] ph, p1, p2;
  always @(posedge clk) begin
    if (!rst_n) ph <= PHASE0;
    else if (ce && run) ph <= ph + cfg_freq;
    if (ce) begin
      p1 <= ph;
      p2 <= p1;
    end
  end
  wire signed [17:0] s_cos, s_sin;
  grv_sincos u_sc (.clk(clk), .ce(ce), .phase(ph[31:20]), .cos_o(s_cos), .sin_o(s_sin));

  // stage 3: waveform value and product
  wire signed [17:0] ps   = p2[31:14];
  wire signed [18:0] wtri0 = ps[17] ? {ps[17], ps} + 19'sd131072 : 19'sd131072 - {ps[17], ps};
  wire signed [17:0] wtri  = (wtri0 > 19'sd131071) ? 18'sd131071 : wtri0[17:0];
  wire signed [17:0] wsaw  = (ps >>> 1) + 18'sd65536;
  wire signed [17:0] wsqr  = p2[31] ? 18'sd0 : 18'sd131071;
  reg  signed [17:0] wi, wq;
  always @(*) begin
    wq = 18'sd0;
    case (WAVE)
      0: wi = 18'sd131071;
      1: begin wi = (CPLX != 0) ? s_cos : s_sin; wq = s_sin; end
      2: begin wi = s_cos; wq = s_sin; end
      3: wi = wsqr;
      4: wi = wtri;
      default: wi = wsaw;
    endcase
  end
  wire signed [AW-1:0] amp = cfg_amp;
  reg  signed [PW-1:0] mi, mq;
  always @(posedge clk) if (ce) begin
    mi <= wi * amp;
    mq <= wq * amp;
  end
  // stage 4: offset
  wire signed [GW-1:0] oi = $signed(cfg_offset) <<< OFSH;
  wire signed [GW-1:0] oq = $signed(cfg_offset_q) <<< OFSH;
  reg  signed [GW-1:0] ai, aq;
  always @(posedge clk) if (ce) begin
    ai <= mi + oi;
    aq <= mq + oq;
  end
  // stage 5: resize
  wire [OW-1:0] ri, rq;
  wire          ovi, ovq;
  grv_resize #(.GW(GW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_ri (.x(ai), .y(ri), .ovf(ovi));
  grv_resize #(.GW(GW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_rq (.x(aq), .y(rq), .ovf(ovq));
  reg [OW*NC-1:0] o5;
  reg             ov5;
  always @(posedge clk) if (ce) begin
    o5  <= (CPLX != 0) ? {rq, ri} : ri;
    ov5 <= v[4] & (ovi | (ovq & (CPLX != 0)));
  end
  assign ovf = ov5 & ce & v[5];

  grv_oreg #(.W(OW*NC), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o5), .s_tvalid(pv), .s_tready(pr),
    .s_tlast(1'b0), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
