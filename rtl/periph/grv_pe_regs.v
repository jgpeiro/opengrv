// grv_pe_regs - registers common to the peripheral endpoints (design document, table 29), plus four
// kind-specific words at 0x20 .. 0x2C.
//   0x00 CTRL    [0] EN [1] FLUSH (W1) [2] IRQ_EN [3] DROP [4] REPEAT
//   0x04 STATUS  [15:0] LEVEL [16] EMPTY [17] FULL [18] OVF [19] UNF [20] ERR [21] BUSY [24] IRQ (W1C 18 .. 20)
//   0x08 THRESH  interrupt while LEVEL >= THRESH (inputs) or LEVEL <= THRESH (outputs)
//   0x0C COUNT   samples transferred
//   0x10 ERRCNT  [15:0] errors [31:16] lost samples, saturating; any write clears
//   0x14 INFO    INFO parameter
//   0x18 TIMING  24.8 clocks
//   0x1C FORMAT
//   0x20 .. 0x2C K0 .. K3
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_pe_regs #(
  parameter integer DIR     = 0,          // 0 input (graph source), 1 output (graph sink)
  parameter [31:0]  INFO    = 32'd0,
  parameter [31:0]  CTRL0   = 32'd1,
  parameter [31:0]  THRESH0 = 32'd1,
  parameter [31:0]  TIMING0 = 32'd0,
  parameter [31:0]  FORMAT0 = 32'd0,
  parameter [31:0]  K00     = 32'd0,
  parameter [31:0]  K10     = 32'd0,
  parameter [31:0]  K20     = 32'd0,
  parameter [31:0]  K30     = 32'd0
)(
  input  wire        clk,
  input  wire        rst_n,
  input  wire [15:0] rb_addr,
  input  wire [31:0] rb_wdata,
  input  wire        rb_we,
  input  wire        rb_re,
  input  wire        rb_sel,
  output wire        t_wrdy,
  output wire        t_rrdy,
  output reg  [31:0] t_rdata,
  output wire        irq,
  // to the endpoint
  output reg  [31:0] ctrl,
  output reg  [31:0] thresh,
  output reg  [31:0] timing,
  output reg  [31:0] format,
  output reg  [31:0] k0, k1, k2, k3,
  output reg         flush,
  // from the endpoint
  input  wire [15:0] level,
  input  wire        full,
  input  wire        busy,
  input  wire        ev_xfer,
  input  wire        ev_ovf,
  input  wire        ev_unf,
  input  wire        ev_err
);
  reg        f_ovf, f_unf, f_err;
  reg [31:0] count;
  reg [15:0] nerr, nlost;
  assign t_wrdy = 1'b1;
  assign t_rrdy = 1'b1;
  wire lvl_cond = (DIR == 0) ? ({16'd0, level} >= thresh) : ({16'd0, level} <= thresh);
  wire cond = lvl_cond || f_ovf || f_unf || f_err;
  assign irq = ctrl[2] && cond;
  wire w = rb_sel && rb_we;
  wire [7:0] a = rb_addr[7:0];
  always @(posedge clk) begin
    flush <= 1'b0;
    if (!rst_n) begin
      ctrl <= CTRL0; thresh <= THRESH0; timing <= TIMING0; format <= FORMAT0;
      k0 <= K00; k1 <= K10; k2 <= K20; k3 <= K30;
      f_ovf <= 1'b0; f_unf <= 1'b0; f_err <= 1'b0; count <= 32'd0; nerr <= 16'd0; nlost <= 16'd0;
    end else begin
      if (ev_xfer) count <= count + 1'b1;
      if (ev_ovf) f_ovf <= 1'b1;
      if (ev_unf) f_unf <= 1'b1;
      if (ev_err) f_err <= 1'b1;
      if (ev_err && nerr != 16'hFFFF) nerr <= nerr + 1'b1;
      if ((ev_ovf || ev_unf) && nlost != 16'hFFFF) nlost <= nlost + 1'b1;
      if (w) case (a)
        8'h00: begin ctrl <= rb_wdata & 32'h0000_001D; flush <= rb_wdata[1]; end
        8'h04: begin
          if (rb_wdata[18]) f_ovf <= 1'b0;
          if (rb_wdata[19]) f_unf <= 1'b0;
          if (rb_wdata[20]) f_err <= 1'b0;
        end
        8'h08: thresh <= rb_wdata;
        8'h10: begin nerr <= 16'd0; nlost <= 16'd0; end
        8'h18: timing <= rb_wdata;
        8'h1C: format <= rb_wdata;
        8'h20: k0 <= rb_wdata;
        8'h24: k1 <= rb_wdata;
        8'h28: k2 <= rb_wdata;
        8'h2C: k3 <= rb_wdata;
        default: ;
      endcase
    end
  end
  always @(posedge clk) if (rb_sel && rb_re) case (a)
    8'h00: t_rdata <= ctrl;
    8'h04: t_rdata <= {7'd0, cond, 2'd0, busy, f_err, f_unf, f_ovf, full, (level == 16'd0), level};
    8'h08: t_rdata <= thresh;
    8'h0C: t_rdata <= count;
    8'h10: t_rdata <= {nlost, nerr};
    8'h14: t_rdata <= INFO;
    8'h18: t_rdata <= timing;
    8'h1C: t_rdata <= format;
    8'h20: t_rdata <= k0;
    8'h24: t_rdata <= k1;
    8'h28: t_rdata <= k2;
    8'h2C: t_rdata <= k3;
    default: t_rdata <= 32'd0;
  endcase
endmodule

`default_nettype wire
