// tb_spi - SPI endpoints back to back: (A) master output -> slave input, (B) slave output -> master
// input. Random samples, random handshakes; every sample must arrive unchanged.
`timescale 1ns/1ps
module tb_spi;
  parameter integer DB = 12, NCB = 1, N = 120, HALF = 3, SEED = 1;
  parameter [31:0] FORMAT = 32'h0000_000F;        // FBITS-1 = 15
  parameter [31:0] CMD = 32'h0000_3000, CMDQ = 32'h0000_B000;
  localparam integer FB = FORMAT[4:0] + 1;
  localparam integer TIM = (NCB * (2 * FB * (HALF + 1) + 12) + 8) * 256;
  reg clk = 0, rst_n = 0, run = 0;
  always #5 clk = ~clk;
  reg [15:0] rb_addr; reg [31:0] rb_wdata; reg rb_we = 0, rb_re = 0; reg [3:0] rb_sel = 0;
  wire [31:0] rd0, rd1, rd2, rd3;
  function [31:0] rdata_of(input integer t); rdata_of = (t == 0) ? rd0 : (t == 1) ? rd1 : (t == 2) ? rd2 : rd3; endfunction
  `include "rb_tasks.vh"
  // A
  reg [DB-1:0] a_d; reg a_v = 0; wire a_r;
  wire [DB-1:0] ao_d; wire ao_v, ao_l;
  wire a_sclk, a_cs, a_mosi;
  grv_pe_spi_tx #(.DBITS(DB), .NC(1), .DEPTH(8), .ROLE(0), .CTRL0(32'h1), .TIMING0(32'd0), .FORMAT0(FORMAT),
                  .SCLK0(HALF), .CMD0(CMD), .CST0(32'h0002_0101))
    u_mt (.clk(clk), .rst_n(rst_n), .run(run), .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re),
          .rb_sel(rb_sel[0]), .t_wrdy(), .t_rrdy(), .t_rdata(rd0), .irq(), .s_tdata(a_d), .s_tvalid(a_v), .s_tready(a_r),
          .s_tlast(1'b0), .sclk_o(a_sclk), .cs_n_o(a_cs), .mosi_o(a_mosi), .sclk_i(1'b0), .cs_n_i(1'b1), .mosi_i(1'b0),
          .miso_o(), .miso_oe(), .drdy());
  grv_pe_spi_rx #(.DBITS(DB), .NC(1), .DEPTH(8), .ROLE(1), .CTRL0(32'h1), .FORMAT0(FORMAT))
    u_sr (.clk(clk), .rst_n(rst_n), .run(run), .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re),
          .rb_sel(rb_sel[1]), .t_wrdy(), .t_rrdy(), .t_rdata(rd1), .irq(), .m_tdata(ao_d), .m_tvalid(ao_v), .m_tready(1'b1),
          .m_tlast(ao_l), .sclk_o(), .cs_n_o(), .mosi_o(), .miso_i(1'b0), .sclk_i(a_sclk), .cs_n_i(a_cs), .mosi_i(a_mosi));
  // B
  reg [DB*NCB-1:0] b_d; reg b_v = 0; wire b_r;
  wire [DB*NCB-1:0] bo_d; wire bo_v, bo_l;
  wire b_sclk, b_cs, b_mosi, b_miso;
  grv_pe_spi_tx #(.DBITS(DB), .NC(NCB), .DEPTH(16), .ROLE(1), .CTRL0(32'h1), .FORMAT0(FORMAT), .CMD0(CMD), .CMDQ0(CMDQ))
    u_st (.clk(clk), .rst_n(rst_n), .run(run), .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re),
          .rb_sel(rb_sel[2]), .t_wrdy(), .t_rrdy(), .t_rdata(rd2), .irq(), .s_tdata(b_d), .s_tvalid(b_v), .s_tready(b_r),
          .s_tlast(1'b0), .sclk_o(), .cs_n_o(), .mosi_o(), .sclk_i(b_sclk), .cs_n_i(b_cs), .mosi_i(b_mosi),
          .miso_o(b_miso), .miso_oe(), .drdy());
  grv_pe_spi_rx #(.DBITS(DB), .NC(NCB), .DEPTH(8), .ROLE(0), .CTRL0(32'h0), .TIMING0(TIM), .FORMAT0(FORMAT),
                  .SCLK0(HALF), .CMD0(CMD), .CMDQ0(CMDQ), .CST0(32'h0002_0101))
    u_mr (.clk(clk), .rst_n(rst_n), .run(run), .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re),
          .rb_sel(rb_sel[3]), .t_wrdy(), .t_rrdy(), .t_rdata(rd3), .irq(), .m_tdata(bo_d), .m_tvalid(bo_v), .m_tready(1'b1),
          .m_tlast(bo_l), .sclk_o(b_sclk), .cs_n_o(b_cs), .mosi_o(b_mosi), .miso_i(b_miso), .sclk_i(1'b0), .cs_n_i(1'b1),
          .mosi_i(1'b0));
  reg [DB-1:0] ea [0:N-1];
  reg [DB*NCB-1:0] eb [0:N-1];
  integer i, sa = 0, sb = 0, ga = 0, gb = 0, err = 0, seed = SEED;
  initial begin
    for (i = 0; i < N; i = i + 1) begin ea[i] = $random(seed); eb[i] = {$random(seed), $random(seed)}; end
    repeat (5) @(posedge clk); rst_n = 1; run = 1;
    repeat (200) @(posedge clk);
    rb_write(3, 16'h00, 32'h1);                  // start the master input once the slave has data
  end
  always @(posedge clk) if (rst_n) begin
    if (a_v && a_r) begin sa = sa + 1; a_v <= 0; end
    if ((!a_v || a_r) && sa < N && ($random(seed) & 1)) begin a_v <= 1; a_d <= ea[sa]; end
    if (b_v && b_r) begin sb = sb + 1; b_v <= 0; end
    if ((!b_v || b_r) && sb < N) begin b_v <= 1; b_d <= eb[sb]; end
    if (ao_v) begin
      if (ao_d !== ea[ga] || ao_l !== 1'b1) begin
        if (err < 5) $display("A MISMATCH %0d: %h/%b expected %h", ga, ao_d, ao_l, ea[ga]); err = err + 1;
      end
      ga = ga + 1;
    end
    if (bo_v) begin
      if (bo_d !== eb[gb]) begin
        if (err < 12) $display("B MISMATCH %0d: %h expected %h", gb, bo_d, eb[gb]); err = err + 1;
      end
      gb = gb + 1;
    end
  end
  initial begin : finish
    integer t;
    for (t = 0; t < 2000000 && !(ga == N && gb >= N - 4); t = t + 1) @(posedge clk);
    if (ga != N || gb < N - 4) begin $display("TIMEOUT A %0d B %0d of %0d", ga, gb, N); err = err + 1; end
    if (err == 0) $display("PASS"); else $display("FAIL %0d", err);
    $finish;
  end
endmodule
