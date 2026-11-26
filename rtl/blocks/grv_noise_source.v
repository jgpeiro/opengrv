// grv_noise_source - analog_noise_source_x: xorshift32 generators.
// TYPE 0 uniform: w = top 18 bits of one generator (s18.17, [-1, 1)).
// TYPE 1 gaussian: w = sum of 4 generators (CLT; grvgen folds sqrt(3/4) into the amplitude).
// Complex: separate generators for I and Q. out = grv_resize(w * amp).
// Seeds: grvgen/grv/fx.py seeds(SEED, n). Each sample uses the current states, then steps them.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_noise_source #(
  parameter integer OW    = 16,
  parameter integer CPLX  = 0,
  parameter integer TYPE  = 1,
  parameter [31:0]  SEED  = 32'd0,
  parameter integer AW    = 18,
  parameter integer SHIFT = 17,
  parameter integer ROUND = 1,
  parameter integer SAT   = 1,
  parameter integer OREG  = 1
)(
  input  wire                   clk,
  input  wire                   rst_n,
  input  wire                   run,
  input  wire [AW-1:0]          cfg_amp,
  output wire [OW*(CPLX+1)-1:0] m_tdata,
  output wire                   m_tvalid,
  input  wire                   m_tready,
  output wire                   m_tlast,
  output wire                   ovf
);
  localparam integer NC = CPLX + 1;
  localparam integer NS = (TYPE != 0) ? 4 : 1;
  localparam integer NG = NS * NC;
  localparam integer PW = 20 + AW;
  localparam integer LATENCY = 3 + OREG;

  function [31:0] xs32(input [31:0] s);
    reg [31:0] t;
    begin
      t = s ^ (s << 13);
      t = t ^ (t >> 17);
      xs32 = t ^ (t << 5);
    end
  endfunction
  function [31:0] seed_k(input integer k);
    reg [31:0] s;
    begin
      s = SEED * 32'h9E3779B1 + 32'h6A09E667 * (k + 1);
      seed_k = (s == 32'd0) ? 32'h12345678 : s;
    end
  endfunction

  wire ce, pv, pr;
  wire [3:1] v;
  grv_pctl #(.L(3)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(run), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));

  wire [31:0] st [0:NG-1];
  wire signed [AW-1:0] amp = cfg_amp;
  wire [NC-1:0] ov;
  wire [OW*NC-1:0] rr;
  reg  [OW*NC-1:0] o3;
  reg              ov3;

  genvar g, c;
  generate
    for (g = 0; g < NG; g = g + 1) begin : g_gen
      reg [31:0] s;
      always @(posedge clk)
        if (!rst_n) s <= seed_k(g);
        else if (ce && run) s <= xs32(s);
      assign st[g] = s;
    end
    for (c = 0; c < NC; c = c + 1) begin : g_c
      wire signed [17:0] u0 = st[c*NS][31:14];
      wire signed [19:0] sum;
      if (NS == 4) begin : g4
        wire signed [17:0] u1 = st[c*NS+1][31:14];
        wire signed [17:0] u2 = st[c*NS+2][31:14];
        wire signed [17:0] u3 = st[c*NS+3][31:14];
        assign sum = u0 + u1 + u2 + u3;
      end else begin : g1
        assign sum = u0;
      end
      reg signed [19:0]   w1;
      reg signed [PW-1:0] m2;
      wire [OW-1:0] r;
      always @(posedge clk) if (ce) begin
        w1 <= sum;
        m2 <= w1 * amp;
      end
      grv_resize #(.GW(PW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_r (.x(m2), .y(r), .ovf(ov[c]));
      assign rr[c*OW +: OW] = r;
    end
  endgenerate
  always @(posedge clk) if (ce) begin
    o3  <= rr;
    ov3 <= v[2] & |ov;
  end
  assign ovf = ov3 & ce & v[3];

  grv_oreg #(.W(OW*NC), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o3), .s_tvalid(pv), .s_tready(pr),
    .s_tlast(1'b0), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
