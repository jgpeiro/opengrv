// grv_regs - global registers (0x0000 .. 0x00FF) and runtime parameters (0x0100 + 4n).
// Parameters: shadow registers written by the CPU, live registers loaded all at once by
// CTRL.COMMIT (cfg_upd pulses in the same clock as the live values change); PLIVE[n] = 1 makes
// parameter word n live on write. Interrupt: level, see the design document (section 8.10).
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_regs #(
  parameter integer NPW     = 1,
  parameter [32*NPW-1:0] PINIT = {32*NPW{1'b0}},
  parameter [NPW-1:0]   PLIVE  = {NPW{1'b0}},
  parameter [31:0]  VERSION = 32'h0001_0001,
  parameter [31:0]  HASH    = 32'h0,
  parameter [31:0]  CONFIG  = 32'h0,
  parameter [31:0]  CLK_HZ  = 32'd54000000,
  parameter [31:0]  CONFIG2 = 32'h0,
  parameter [31:0]  WINLO0  = 32'h0000_0000,
  parameter [31:0]  WINHI0  = 32'hFFFF_FFFF
)(
  input  wire              clk,
  input  wire              rst_n,
  // register bus
  input  wire [15:0]       rb_addr,
  input  wire [31:0]       rb_wdata,
  input  wire              rb_we,
  input  wire              rb_re,
  input  wire              rb_sel,
  output wire              t_wrdy,
  output wire              t_rrdy,
  output reg  [31:0]       t_rdata,
  // graph
  output wire              run,
  output wire              graph_rst_n,
  output reg               cfg_upd,
  output reg  [32*NPW-1:0] cfg_live,
  input  wire [15:0]       irq_snk,
  input  wire [15:0]       irq_src,
  input  wire [15:0]       irq_pe,
  input  wire [15:0]       irq_dma,
  output reg  [31:0]       dma_win_lo,
  output reg  [31:0]       dma_win_hi,
  input  wire [63:0]       ovf_in,
  input  wire [63:0]       err_in,
  output wire [15:0]       timeout,
  output wire              irq
);
  reg [31:0]       ctrl;
  reg [31:0]       irq_en, irq2_en;
  reg [15:0]       tmo;
  reg [63:0]       ovf_map, err_map;
  reg [31:0]       scratch;
  reg [32*NPW-1:0] shadow;
  reg              srst;
  assign t_wrdy = 1'b1;
  assign t_rrdy = 1'b1;
  assign run = ctrl[0];
  assign graph_rst_n = rst_n && !srst;
  assign timeout = tmo;
  wire [31:0] irq_st = {irq_src, irq_snk};
  wire [31:0] irq2_st = {irq_dma, irq_pe};
  wire ovf_any = |ovf_map;
  wire err_any = |err_map;
  assign irq = ctrl[8] && ((|(irq_st & irq_en)) || (|(irq2_st & irq2_en)) || (ctrl[9] && ovf_any) || (ctrl[10] && err_any));

  wire w = rb_sel && rb_we;
  wire [11:0] a = rb_addr[11:0];
  wire        is_param = (a >= 12'h100);
  wire [31:0] pidx = (a - 12'h100) >> 2;
  integer k;
  always @(posedge clk) begin
    cfg_upd <= 1'b0;
    srst    <= 1'b0;
    if (!rst_n) begin
      ctrl <= 32'd0; irq_en <= 32'd0; tmo <= 16'd1024; ovf_map <= 64'd0; err_map <= 64'd0;
      scratch <= 32'd0; shadow <= PINIT; cfg_live <= PINIT;
      irq2_en <= 32'd0; dma_win_lo <= WINLO0; dma_win_hi <= WINHI0;
    end else begin
      ovf_map <= ovf_map | ovf_in;
      err_map <= err_map | err_in;
      if (w && !is_param) case (a[7:0])
        8'h14: begin
          ctrl <= rb_wdata & 32'h0000_0701;
          if (rb_wdata[1]) srst <= 1'b1;
          if (rb_wdata[2]) begin cfg_live <= shadow; cfg_upd <= 1'b1; end
        end
        8'h1C: irq_en <= rb_wdata;
        8'h24: tmo <= rb_wdata[15:0];
        8'h28: ovf_map[31:0]  <= (ovf_map[31:0]  | ovf_in[31:0])  & ~rb_wdata;
        8'h2C: ovf_map[63:32] <= (ovf_map[63:32] | ovf_in[63:32]) & ~rb_wdata;
        8'h30: err_map[31:0]  <= (err_map[31:0]  | err_in[31:0])  & ~rb_wdata;
        8'h34: err_map[63:32] <= (err_map[63:32] | err_in[63:32]) & ~rb_wdata;
        8'h3C: scratch <= rb_wdata;
        8'h40: irq2_en <= rb_wdata;
        8'h48: dma_win_lo <= rb_wdata;
        8'h4C: dma_win_hi <= rb_wdata;
        default: ;
      endcase
      if (w && is_param && pidx < NPW) begin
        shadow[32*pidx +: 32] <= rb_wdata;
        if (PLIVE[pidx]) cfg_live[32*pidx +: 32] <= rb_wdata;
      end
    end
  end
  always @(posedge clk) if (rb_sel && rb_re) begin
    if (is_param) t_rdata <= (pidx < NPW) ? shadow[32*pidx +: 32] : 32'd0;
    else case (a[7:0])
      8'h00: t_rdata <= 32'h4752_5631;
      8'h04: t_rdata <= VERSION;
      8'h08: t_rdata <= HASH;
      8'h0C: t_rdata <= CONFIG;
      8'h10: t_rdata <= CLK_HZ;
      8'h14: t_rdata <= ctrl;
      8'h18: t_rdata <= {27'd0, 1'b0, err_any, ovf_any, 1'b0, ctrl[0]};
      8'h1C: t_rdata <= irq_en;
      8'h20: t_rdata <= irq_st;
      8'h24: t_rdata <= {16'd0, tmo};
      8'h28: t_rdata <= ovf_map[31:0];
      8'h2C: t_rdata <= ovf_map[63:32];
      8'h30: t_rdata <= err_map[31:0];
      8'h34: t_rdata <= err_map[63:32];
      8'h38: t_rdata <= CONFIG2;
      8'h3C: t_rdata <= scratch;
      8'h40: t_rdata <= irq2_en;
      8'h44: t_rdata <= irq2_st;
      8'h48: t_rdata <= dma_win_lo;
      8'h4C: t_rdata <= dma_win_hi;
      default: t_rdata <= 32'd0;
    endcase
  end
endmodule

`default_nettype wire
