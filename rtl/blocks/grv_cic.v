// grv_cic - CIC filters (library blocks grv_cic_decim, grv_cic_interp). N stages, ratio R,
// differential delay MD. Integrators update together, each adding the previous value of the
// stage before it:  i0 += x ; ik += i(k-1)   (registered chain, GW-bit wrap-around arithmetic).
// DECIM 1: integrators at the input rate, every R-th input goes through the N combs
//          (y = v - v[-MD]) and is resized. DECIM 0: combs at the input rate, each comb output
//          followed by R-1 zeros into the integrators, one output per integrator step.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_cic #(
  parameter integer DECIM = 1,
  parameter integer IW    = 16,
  parameter integer CPLX  = 0,
  parameter integer N     = 3,
  parameter integer R     = 8,
  parameter integer MD    = 1,
  parameter integer GW    = 26,
  parameter integer OW    = 16,
  parameter integer SHIFT = 9,
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
  localparam integer RW = (R > 1) ? $clog2(R) : 1;
  wire [OW*NC-1:0] r;
  wire [NC-1:0]    ov;
  genvar c, k;
  generate
    if (DECIM != 0) begin : g_dec
      reg  [RW-1:0] cnt;
      wire last_in = (cnt == R - 1);
      wire ce, pv, pr;
      wire [N+1:1] v;
      grv_pctl #(.L(N + 1)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(s_tvalid && last_in), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));
      assign s_tready = last_in ? ce : 1'b1;
      wire take = s_tvalid && s_tready;
      always @(posedge clk)
        if (!rst_n) cnt <= 0;
        else if (take) cnt <= last_in ? {RW{1'b0}} : cnt + 1'b1;
      reg [N:0] l;
      always @(posedge clk) if (ce) l <= {l[N-1:0], s_tlast};
      for (c = 0; c < NC; c = c + 1) begin : g_c
        wire [GW-1:0] iv [0:N];               // integrator values (iv[0] = input)
        wire [GW-1:0] in_new [1:N];
        assign iv[0] = {{(GW-IW){s_tdata[c*IW+IW-1]}}, s_tdata[c*IW +: IW]};
        for (k = 1; k <= N; k = k + 1) begin : g_i
          reg [GW-1:0] a;
          always @(posedge clk)
            if (!rst_n) a <= {GW{1'b0}};
            else if (take) a <= a + iv[k-1];
          assign iv[k] = a;
          assign in_new[k] = a + iv[k-1];
        end
        // comb chain at the output rate: stage k register cv[k]
        wire [GW-1:0] cv [0:N];
        reg  [GW-1:0] c0;
        always @(posedge clk) if (ce) c0 <= in_new[N];
        assign cv[0] = c0;
        for (k = 1; k <= N; k = k + 1) begin : g_cb
          reg [GW-1:0] dl [0:MD-1];
          reg [GW-1:0] y;
          integer q;
          always @(posedge clk) begin
            if (!rst_n) begin
              for (q = 0; q < MD; q = q + 1) dl[q] <= {GW{1'b0}};
            end else if (ce && v[k]) begin
              dl[0] <= cv[k-1];
              for (q = 1; q < MD; q = q + 1) dl[q] <= dl[q-1];
            end
            if (ce) y <= cv[k-1] - dl[MD-1];
          end
          assign cv[k] = y;
        end
        grv_resize #(.GW(GW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_r (.x(cv[N]), .y(r[c*OW +: OW]), .ovf(ov[c]));
      end
      reg [OW*NC-1:0] o;
      reg             ol, ovq;
      wire o_v, o_r;
      grv_pctl #(.L(1)) u_oc (.clk(clk), .rst_n(rst_n), .in_valid(pv), .out_ready(o_r), .ce(), .out_valid(o_v), .v());
      assign pr = !o_v || o_r;
      always @(posedge clk) if (pr) begin o <= r; ol <= l[N]; ovq <= pv & |ov; end
      assign ovf = ovq & o_v & o_r;
      grv_oreg #(.W(OW*NC), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o), .s_tvalid(o_v), .s_tready(o_r),
        .s_tlast(ol), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
    end else begin : g_int
      // combs at the input rate
      wire ce, pv, pr;
      wire [N:1] v;
      grv_pctl #(.L(N)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(s_tvalid), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));
      assign s_tready = ce;
      reg [N:0] l;
      always @(posedge clk) if (ce) l <= {l[N-1:0], s_tlast};
      // upsampler and integrators: one step per output
      reg  [RW-1:0] ph;
      wire          step;
      wire          lastp = (ph == R - 1);
      assign pr = step && lastp;
      for (c = 0; c < NC; c = c + 1) begin : g_c
        wire [GW-1:0] cv [0:N];
        assign cv[0] = {{(GW-IW){s_tdata[c*IW+IW-1]}}, s_tdata[c*IW +: IW]};
        for (k = 1; k <= N; k = k + 1) begin : g_cb
          reg [GW-1:0] dl [0:MD-1];
          reg [GW-1:0] y;
          integer q;
          wire vin;
          if (k == 1) begin : g_v0
            assign vin = s_tvalid;
          end else begin : g_vk
            assign vin = v[k-1];
          end
          always @(posedge clk) begin
            if (!rst_n) begin
              for (q = 0; q < MD; q = q + 1) dl[q] <= {GW{1'b0}};
            end else if (ce && vin) begin
              dl[0] <= cv[k-1];
              for (q = 1; q < MD; q = q + 1) dl[q] <= dl[q-1];
            end
            if (ce) y <= cv[k-1] - dl[MD-1];
          end
          assign cv[k] = y;
        end
        wire [GW-1:0] u = (ph == 0) ? cv[N] : {GW{1'b0}};
        wire [GW-1:0] iv [0:N];
        assign iv[0] = u;
        for (k = 1; k <= N; k = k + 1) begin : g_i
          reg [GW-1:0] a;
          always @(posedge clk)
            if (!rst_n) a <= {GW{1'b0}};
            else if (step) a <= a + iv[k-1];
          assign iv[k] = a;
        end
        wire [GW-1:0] onew = iv[N] + iv[N-1];
        grv_resize #(.GW(GW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_r (.x(onew), .y(r[c*OW +: OW]), .ovf(ov[c]));
      end
      wire o_ce, o_v, o_r;
      grv_pctl #(.L(1)) u_oc (.clk(clk), .rst_n(rst_n), .in_valid(pv), .out_ready(o_r), .ce(o_ce), .out_valid(o_v), .v());
      assign step = o_ce && pv;
      always @(posedge clk)
        if (!rst_n) ph <= 0;
        else if (step) ph <= lastp ? {RW{1'b0}} : ph + 1'b1;
      reg [OW*NC-1:0] o;
      reg             ol, ovq;
      always @(posedge clk) if (o_ce) begin o <= r; ol <= lastp & l[N-1]; ovq <= pv & |ov; end
      assign ovf = ovq & o_v & o_r;
      grv_oreg #(.W(OW*NC), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o), .s_tvalid(o_v), .s_tready(o_r),
        .s_tlast(ol), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
    end
  endgenerate
endmodule

`default_nettype wire
