// tb_ctrl - self-checking test of the control plane: grv_axil_dec, grv_regs, grv_ep_src,
// grv_ep_snk (stream and capture), grv_probes, with random AXI4-Lite handshake delays.
`timescale 1ns/1ps
`default_nettype none
module tb_ctrl;
  reg clk = 0, rst_n = 0;
  always #5 clk = ~clk;
  integer errors = 0, seed = 7;

  // AXI master signals
  reg  [15:0] awaddr, araddr;
  reg         awvalid = 0, wvalid = 0, arvalid = 0, bready = 0, rready = 0;
  reg  [31:0] wdata;
  reg  [3:0]  wstrb = 4'hF;
  wire        awready, wready, bvalid, arready, rvalid;
  wire [1:0]  bresp, rresp;
  wire [31:0] rdata;

  // ------------------------------------------------ DUT: a small control plane
  localparam NT = 1 + 1 + 2 + 1;
  wire [15:0] rb_addr; wire [31:0] rb_wdata; wire rb_we, rb_re, rb_force; wire [NT-1:0] rb_sel;
  wire [NT-1:0] t_wrdy, t_rrdy; wire [32*NT-1:0] t_rdata;
  wire [15:0] timeout;
  wire run, grst_n, cfg_upd, irq, irq_s0, irq_k0, irq_k1;
  wire [63:0] live;
  grv_axil_dec #(.NS(1), .NK(2), .NP(1)) u_dec (.clk(clk), .rst_n(rst_n), .timeout(timeout),
    .s_axil_awaddr(awaddr), .s_axil_awvalid(awvalid), .s_axil_awready(awready), .s_axil_wdata(wdata),
    .s_axil_wstrb(wstrb), .s_axil_wvalid(wvalid), .s_axil_wready(wready), .s_axil_bresp(bresp),
    .s_axil_bvalid(bvalid), .s_axil_bready(bready), .s_axil_araddr(araddr), .s_axil_arvalid(arvalid),
    .s_axil_arready(arready), .s_axil_rdata(rdata), .s_axil_rresp(rresp), .s_axil_rvalid(rvalid),
    .s_axil_rready(rready), .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re),
    .rb_force(rb_force), .rb_sel(rb_sel), .t_wrdy(t_wrdy), .t_rrdy(t_rrdy), .t_rdata(t_rdata));
  grv_regs #(.NPW(2), .PINIT({32'd22, 32'd11}), .PLIVE(2'b10), .HASH(32'hCAFE0001)) u_regs (
    .clk(clk), .rst_n(rst_n), .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re),
    .rb_sel(rb_sel[0]), .t_wrdy(t_wrdy[0]), .t_rrdy(t_rrdy[0]), .t_rdata(t_rdata[0 +: 32]),
    .run(run), .graph_rst_n(grst_n), .cfg_upd(cfg_upd), .cfg_live(live), .irq_snk({14'd0, irq_k1, irq_k0}),
    .irq_src({15'd0, irq_s0}), .irq_pe(16'd0), .irq_dma(16'd0), .dma_win_lo(), .dma_win_hi(), .ovf_in(64'd0), .err_in(64'd0), .timeout(timeout), .irq(irq));
  wire [15:0] l_d; wire l_v, l_r, l_l;
  grv_ep_src #(.W(16), .CW(16), .NC(1), .DEPTH(32)) u_src (.clk(clk), .rst_n(grst_n), .run(run),
    .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re), .rb_force(rb_force), .rb_sel(rb_sel[1]),
    .t_wrdy(t_wrdy[1]), .t_rrdy(t_rrdy[1]), .t_rdata(t_rdata[32 +: 32]), .irq(irq_s0),
    .m_tdata(l_d), .m_tvalid(l_v), .m_tready(l_r), .m_tlast(l_l));
  // a random stall between the two endpoints
  reg stall = 0;
  always @(posedge clk) stall <= ($random(seed) & 3) == 0;
  grv_ep_snk #(.W(16), .CW(16), .NC(1), .DEPTH(64)) u_snk0 (.clk(clk), .rst_n(grst_n),
    .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re), .rb_force(rb_force), .rb_sel(rb_sel[2]),
    .t_wrdy(t_wrdy[2]), .t_rrdy(t_rrdy[2]), .t_rdata(t_rdata[64 +: 32]), .irq(irq_k0),
    .s_tdata(l_d), .s_tvalid(l_v && !stall), .s_tready(l_r_raw), .s_tlast(l_l));
  wire l_r_raw;
  assign l_r = l_r_raw && !stall;
  // ramp source for the capture sink and the probe
  reg  [15:0] ramp = 0;
  reg         ramp_clr = 0;
  wire        k1_r;
  always @(posedge clk) if (ramp_clr) ramp <= 0; else if (run && k1_r) ramp <= ramp + 1'b1;
  grv_ep_snk #(.W(16), .CW(16), .NC(1), .DEPTH(16), .CAPD(64)) u_snk1 (.clk(clk), .rst_n(grst_n),
    .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re), .rb_force(rb_force), .rb_sel(rb_sel[3]),
    .t_wrdy(t_wrdy[3]), .t_rrdy(t_rrdy[3]), .t_rdata(t_rdata[96 +: 32]), .irq(irq_k1),
    .s_tdata(ramp), .s_tvalid(run), .s_tready(k1_r), .s_tlast(ramp[3:0] == 4'hF));
  grv_probes #(.NP(1)) u_pr (.clk(clk), .rst_n(grst_n), .rb_addr(rb_addr), .rb_re(rb_re), .rb_sel(rb_sel[4]),
    .t_wrdy(t_wrdy[4]), .t_rrdy(t_rrdy[4]), .t_rdata(t_rdata[128 +: 32]),
    .s_tdata({{48{ramp[15]}}, ramp}), .s_tvalid(run), .s_tready());
  integer upd_count = 0;
  always @(posedge clk) if (cfg_upd) upd_count = upd_count + 1;

  // ------------------------------------------------ AXI master tasks with random delays
  task wr(input [15:0] a, input [31:0] d, output [1:0] resp);
    begin
      repeat ($random(seed) & 3) @(posedge clk);
      awaddr <= a; wdata <= d; awvalid <= 1; wvalid <= 1;
      @(posedge clk);
      while (!(awready && wready)) @(posedge clk);
      awvalid <= 0; wvalid <= 0;
      repeat ($random(seed) & 3) @(posedge clk);
      bready <= 1;
      @(posedge clk);
      while (!bvalid) @(posedge clk);
      resp = bresp;
      bready <= 0;
    end
  endtask
  task rd(input [15:0] a, output [31:0] d, output [1:0] resp);
    begin
      repeat ($random(seed) & 3) @(posedge clk);
      araddr <= a; arvalid <= 1;
      @(posedge clk);
      while (!arready) @(posedge clk);
      arvalid <= 0;
      repeat ($random(seed) & 3) @(posedge clk);
      rready <= 1;
      @(posedge clk);
      while (!rvalid) @(posedge clk);
      d = rdata; resp = rresp;
      rready <= 0;
    end
  endtask
  reg [1:0] r; reg [31:0] d;
  task W(input [15:0] a, input [31:0] v); begin wr(a, v, r); if (r != 0) begin errors = errors + 1; $display("ERR write %h resp %d", a, r); end end endtask
  task R(input [15:0] a); begin rd(a, d, r); if (r != 0) begin errors = errors + 1; $display("ERR read %h resp %d", a, r); end end endtask
  task CHK(input [15:0] a, input [31:0] m, input [31:0] e);
    begin R(a); if ((d & m) !== e) begin errors = errors + 1; $display("ERR %h: %h expected %h", a, d & m, e); end end
  endtask

  integer i, n;
  reg [15:0] exp, e0, e1;
  initial begin
    repeat (5) @(posedge clk); rst_n <= 1; repeat (3) @(posedge clk);
    // 1. identification, scratch
    CHK(16'h0000, 32'hFFFFFFFF, 32'h47525631);
    CHK(16'h0008, 32'hFFFFFFFF, 32'hCAFE0001);
    W(16'h003C, 32'h12345678); CHK(16'h003C, 32'hFFFFFFFF, 32'h12345678);
    // 2. parameters: P0 shadowed, P1 live
    W(16'h0100, 32'd111); W(16'h0104, 32'd222);
    if (live[31:0] !== 32'd11 || live[63:32] !== 32'd222) begin errors = errors + 1; $display("ERR live before commit %0d %0d", live[31:0], live[63:32]); end
    W(16'h0014, 32'h4);                          // COMMIT
    @(posedge clk);
    if (live[31:0] !== 32'd111 || upd_count != 1) begin errors = errors + 1; $display("ERR commit %0d %0d", live[31:0], upd_count); end
    CHK(16'h0100, 32'hFFFFFFFF, 32'd111);
    // 3. stream loop: src0 -> snk0
    W(16'h200C, 32'h1);                          // snk0 EN
    W(16'h100C, 32'h1);                          // src0 EN
    W(16'h0014, 32'h1);                          // RUN
    for (i = 0; i < 40; i = i + 1) W(16'h1000 + ((i % 17) == 0 ? 16'h00 : 16'h40 + 4 * (i % 16)), 32'd1000 + i * 37);
    n = 0;
    while (n < 40) begin
      R(16'h2008);
      if (d[15:0] != 0) begin
        R(16'h2000);
        exp = 1000 + n * 37;
        if (d[15:0] !== exp) begin errors = errors + 1; $display("ERR stream sample %0d: %0d expected %0d", n, d[15:0], exp); end
        n = n + 1;
      end
    end
    CHK(16'h2018, 32'hFFFFFFFF, 32'd40);         // COUNT
    // 4. packed transfers: 2 samples per word both ways
    W(16'h100C, 32'h9); W(16'h200C, 32'h9);
    for (i = 0; i < 12; i = i + 1) begin e0 = 500 + 2*i; e1 = 501 + 2*i; W(16'h1000, {e1, e0}); end
    n = 0;
    while (n < 12) begin
      R(16'h2008);
      if (d[15:0] >= 2) begin
        R(16'h2000);
        e0 = 500 + 2*n; e1 = 501 + 2*n;
        if (d !== {e1, e0}) begin errors = errors + 1; $display("ERR packed word %0d: %h", n, d); end
        n = n + 1;
      end
    end
    // 5. overflow and timeout on the source (output disabled)
    W(16'h100C, 32'h0);                          // EN = 0, WAIT = 0
    for (i = 0; i < 34; i = i + 1) W(16'h1000, i);
    CHK(16'h1008, 32'h0004FFFF, 32'h00040020);   // OVF set, level 32
    W(16'h0024, 32'd20);                         // TIMEOUT 20 clocks
    W(16'h100C, 32'h4);                          // WAIT
    wr(16'h1000, 32'd9, r);
    if (r !== 2'b10) begin errors = errors + 1; $display("ERR expected SLVERR on timeout, got %d", r); end
    CHK(16'h1008, 32'h00100000, 32'h00100000);   // TIMEOUT flag
    W(16'h1008, 32'h00140000);                   // clear flags
    CHK(16'h1008, 32'h00140000, 32'h0);
    W(16'h100C, 32'h2);                          // FLUSH
    CHK(16'h1008, 32'h0001FFFF, 32'h00010000);
    // 6. capture with pre-trigger: rising through 300, 10 samples, 3 before
    W(16'h3020, 32'd0);
    W(16'h2120, 32'd300);                        // TRIG_LEVEL
    W(16'h2114, {16'd3, 16'd10});                // CAPLEN 10, PRE 3
    ramp_clr <= 1;
    W(16'h210C, {19'd0, 1'b0, 3'd1, 1'b1, 2'd1, 6'd1});   // TRIG rising, ARM, CAPTURE, EN
    ramp_clr <= 0;
    n = 0;
    R(16'h2108);
    while (!d[21]) begin R(16'h2108); n = n + 1; if (n > 5000) begin errors = errors + 1; $display("ERR capture not done"); d[21] = 1; end end
    for (i = 0; i < 10; i = i + 1) begin
      R(16'h2100);
      if (d[15:0] !== 297 + i) begin errors = errors + 1; $display("ERR capture %0d: %0d", i, d[15:0]); end
    end
    R(16'h2128);
    n = d;
    R(16'hA000 + 4 * ((n + 4) % 64));
    if (d[15:0] !== 301) begin errors = errors + 1; $display("ERR capture window: %0d", d[15:0]); end
    // 7. probe follows the ramp
    R(16'h3000); n = d; repeat (20) @(posedge clk); R(16'h3000);
    if (d == n) begin errors = errors + 1; $display("ERR probe does not change"); end
    // 8. responses: unmapped, partial write
    rd(16'h5000, d, r); if (r !== 2'b11) begin errors = errors + 1; $display("ERR DECERR expected, got %d", r); end
    wstrb <= 4'h3; wr(16'h003C, 32'h0, r); wstrb <= 4'hF;
    if (r !== 2'b10) begin errors = errors + 1; $display("ERR SLVERR on partial write expected, got %d", r); end
    // 9. interrupt: snk0 level >= 4
    W(16'h200C, 32'h11); W(16'h2010, 32'd4); W(16'h100C, 32'h1);
    W(16'h001C, 32'h1); W(16'h0014, 32'h101);
    if (irq) begin errors = errors + 1; $display("ERR irq too early"); end
    for (i = 0; i < 4; i = i + 1) W(16'h1000, i);
    repeat (40) @(posedge clk);
    if (!irq) begin errors = errors + 1; $display("ERR irq missing"); end
    CHK(16'h0020, 32'h1, 32'h1);
    if (errors == 0) $display("PASS tb_ctrl");
    else $display("FAIL tb_ctrl: %0d errors", errors);
    $finish;
  end
  initial begin #3000000; $display("FAIL tb_ctrl: timeout"); $finish; end
endmodule
`default_nettype wire
