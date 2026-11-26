// grv_pe_gpio_out - GPIO output endpoint (design document, section 9.5). Modes (FORMAT.MODE):
//   0 PARALLEL  the fields (I on the low pins) are written to the pins on every tick, or for every
//               sample with TIMING = 0; FORMAT.CLKO: clk_o rises PHASE clocks after the update
//   1 PWM       pin c carries component c as PWM of period 2^DBITS clocks, duty = offset-binary field;
//               a new sample at the first period boundary after each tick (TIMING = 0: every period)
//   2 SDM       pin c carries component c through a sigma-delta modulator (second order, FORMAT.ORD1:
//               first order) clocked every DIV + 1 clocks; the sample is held until the next tick
// An empty FIFO at a tick counts an underflow and repeats the last sample (CTRL.REPEAT) or outputs 0.
//   FORMAT [1:0] MODE [3] OFS [4] CLKO [5] ORD1 [15:8] PHASE [23:16] DIV
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_pe_gpio_out #(
  parameter integer DBITS   = 8,
  parameter integer NC      = 1,
  parameter integer NPIN    = 8,
  parameter integer SIGNED  = 1,
  parameter integer FRAC    = 7,
  parameter integer DEPTH   = 32,
  parameter [31:0]  CTRL0   = 32'h1,
  parameter [31:0]  TIMING0 = 32'd0,
  parameter [31:0]  FORMAT0 = 32'd0,
  parameter [31:0]  THRESH0 = 32'd0
)(
  input  wire                clk,
  input  wire                rst_n,
  input  wire                run,
  input  wire [15:0]         rb_addr,
  input  wire [31:0]         rb_wdata,
  input  wire                rb_we,
  input  wire                rb_re,
  input  wire                rb_sel,
  output wire                t_wrdy,
  output wire                t_rrdy,
  output wire [31:0]         t_rdata,
  output wire                irq,
  input  wire [DBITS*NC-1:0] s_tdata,
  input  wire                s_tvalid,
  output wire                s_tready,
  input  wire                s_tlast,
  output reg  [NPIN-1:0]     pins_o,
  output reg                 clk_o
);
  localparam integer W  = DBITS * NC;
  localparam integer AW = $clog2(DEPTH);
  localparam integer IW = DBITS + 6;      // SDM integrators
  localparam [31:0] INFO = {2'd0, DBITS[4:0] - 5'd1, 1'b1, 4'd4, AW[3:0], 2'd0, FRAC[5:0], SIGNED[0], (NC == 2), DBITS[5:0]};

  wire [31:0] ctrl, thresh, timing, format, k0, k1, k2, k3;
  wire        flush;
  wire [15:0] level;
  wire        en = ctrl[0] && run;
  wire [1:0]  mode = format[1:0];
  wire        ofs = format[3], clko = format[4], ord1 = format[5];
  wire [7:0]  phase = format[15:8], div = format[23:16];
  wire        f_ready, f_valid;
  wire [W-1:0] f_data;
  reg         f_pop, ev_unf;
  assign s_tready = f_ready || ctrl[3];
  grv_fifo_fl #(.W(W), .DEPTH(DEPTH)) u_fifo (.clk(clk), .rst_n(rst_n), .flush(flush),
    .s_data(s_tdata), .s_valid(s_tvalid && f_ready), .s_ready(f_ready),
    .m_data(f_data), .m_valid(f_valid), .m_ready(f_pop), .level(level));

  grv_pe_regs #(.DIR(1), .INFO(INFO), .CTRL0(CTRL0), .THRESH0(THRESH0), .TIMING0(TIMING0), .FORMAT0(FORMAT0))
  u_regs (.clk(clk), .rst_n(rst_n), .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re),
    .rb_sel(rb_sel), .t_wrdy(t_wrdy), .t_rrdy(t_rrdy), .t_rdata(t_rdata), .irq(irq),
    .ctrl(ctrl), .thresh(thresh), .timing(timing), .format(format), .k0(k0), .k1(k1), .k2(k2), .k3(k3),
    .flush(flush), .level(level), .full(!f_ready), .busy(en), .ev_xfer(f_pop),
    .ev_ovf(s_tvalid && !f_ready && ctrl[3]), .ev_unf(ev_unf), .ev_err(1'b0));

  wire tick;
  wire paced = (timing >= 32'd256);
  grv_pace u_pace (.clk(clk), .rst_n(rst_n), .en(en), .timing(timing), .tick(tick));

  // the sample currently output (two's complement components)
  reg  [W-1:0] cur;
  reg          pend;           // a tick is waiting for the next PWM period
  reg  [DBITS-1:0] pc;         // PWM counter
  wire         pwm_bound = (pc == {DBITS{1'b1}});
  // take a new sample?
  wire want = !en ? 1'b0 :
              (mode == 2'd1) ? (pwm_bound && (paced ? (pend || tick) : 1'b1)) :
              paced ? tick : (f_valid && !f_pop);
  reg [31:0] pos;
  reg [8:0]  cdly;
  reg        cact;
  reg [7:0]  dc;               // SDM clock divider
  wire       sdm_step = (dc == 8'd0);

  // second-order (or first-order) sigma-delta modulators, one per component
  reg signed [IW-1:0] i1 [0:NC-1];
  reg signed [IW-1:0] i2 [0:NC-1];
  reg        [NC-1:0] sdo;
  localparam signed [IW-1:0] FS   = 1 <<< (DBITS - 1);
  localparam signed [IW-1:0] IMAX = (1 <<< (IW - 1)) - 1;
  localparam signed [IW-1:0] IMIN = -(1 <<< (IW - 1));
  function signed [IW-1:0] sat(input signed [IW:0] v);
    sat = (v > IMAX) ? IMAX : (v < IMIN) ? IMIN : v[IW-1:0];
  endfunction

  function [DBITS-1:0] obin(input [DBITS-1:0] v);
    begin
      obin = v;
      obin[DBITS-1] = ~v[DBITS-1];
    end
  endfunction

  integer c;
  reg signed [IW-1:0] x, y, n1, n2;
  reg [NPIN-1:0] pv;
  always @(posedge clk) begin
    f_pop <= 1'b0; ev_unf <= 1'b0;
    if (!rst_n || flush) begin
      cur <= {W{1'b0}}; pend <= 1'b0; pc <= {DBITS{1'b0}}; pins_o <= {NPIN{1'b0}}; clk_o <= 1'b0;
      cact <= 1'b0; pos <= 32'd0; dc <= 8'd0; sdo <= {NC{1'b0}};
      for (c = 0; c < NC; c = c + 1) begin i1[c] <= {IW{1'b0}}; i2[c] <= {IW{1'b0}}; end
    end else begin
      pc <= pc + 1'b1;
      if (tick && !pwm_bound) pend <= 1'b1;
      if (want) begin
        pend <= 1'b0;
        if (f_valid && !f_pop) begin cur <= f_data; f_pop <= 1'b1; end
        else begin ev_unf <= paced || mode == 2'd1; if (!ctrl[4]) cur <= {W{1'b0}}; end
        if (mode == 2'd0) begin cact <= 1'b1; cdly <= {1'b0, phase}; pos <= 32'd0; end
      end else if (pos != 32'hFFFF_FFFF) pos <= pos + 1'b1;
      // PARALLEL clock output: rises PHASE clocks after the update, high for half the period (or 1 clock)
      if (cact) begin
        if (cdly == 9'd0) begin cact <= 1'b0; clk_o <= clko; end
        else cdly <= cdly - 1'b1;
      end else if (clk_o && (pos >= {9'd0, phase} + {9'd0, timing[31:9]} || !paced)) clk_o <= 1'b0;
      // SDM
      dc <= sdm_step ? div : dc - 1'b1;
      if (sdm_step) begin
        for (c = 0; c < NC; c = c + 1) begin
          x  = {{(IW-DBITS){cur[c * DBITS + DBITS - 1]}}, cur[c * DBITS +: DBITS]};
          y  = sdo[c] ? FS : -FS;
          n1 = sat({i1[c][IW-1], i1[c]} + {x[IW-1], x} - {y[IW-1], y});
          n2 = sat({i2[c][IW-1], i2[c]} + {n1[IW-1], n1} - {y[IW-1], y});
          i1[c] <= n1;
          i2[c] <= ord1 ? {IW{1'b0}} : n2;
          sdo[c] <= ord1 ? (n1 >= 0) : (n2 >= 0);
        end
      end
      // pins
      pv = {NPIN{1'b0}};
      case (mode)
        2'd0: begin
          for (c = 0; c < NPIN && c < W; c = c + 1) pv[c] = cur[c];
          if (ofs) for (c = 0; c < NC; c = c + 1) if (c * DBITS + DBITS - 1 < NPIN) pv[c * DBITS + DBITS - 1] = ~cur[c * DBITS + DBITS - 1];
        end
        2'd1: for (c = 0; c < NC && c < NPIN; c = c + 1)
                pv[c] = (pc < obin(cur[c * DBITS +: DBITS]));
        2'd2: for (c = 0; c < NC && c < NPIN; c = c + 1) pv[c] = sdo[c];
        default: ;
      endcase
      if (en) pins_o <= pv;
    end
  end
endmodule

`default_nettype wire
