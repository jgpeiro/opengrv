// tb_uart - UART transmitter endpoint looped back into the receiver endpoint. Random samples with
// random tlast, random handshakes; the receiver must give the same samples (and, with GAP framing,
// the same tlast). With TEXT the line is decoded here and compared with the expected hexadecimal text.
`timescale 1ns/1ps
module tb_uart;
  parameter integer W = 16, NC = 1, N = 200, TIMING = 2560, SEED = 1;
  parameter [31:0] FORMAT = 32'h0000_0000;
  reg clk = 0, rst_n = 0, run = 0;
  always #5 clk = ~clk;
  reg [15:0] rb_addr; reg [31:0] rb_wdata; reg rb_we = 0, rb_re = 0; reg [1:0] rb_sel = 0;
  wire [31:0] rd0, rd1;
  function [31:0] rdata_of(input integer t); rdata_of = t ? rd1 : rd0; endfunction
  `include "rb_tasks.vh"
  reg [W-1:0] s_d; reg s_v = 0, s_l; wire s_r;
  wire [W-1:0] m_d; wire m_v, m_l; reg m_r = 0;
  wire txd, rts_n;
  wire text = FORMAT[6], gapf = (FORMAT[15:8] != 0), flow = FORMAT[4];
  grv_pe_uart_tx #(.W(W), .CW(W / NC), .NC(NC), .DEPTH(16), .VEC(1), .CTRL0(32'h1), .TIMING0(TIMING), .FORMAT0(FORMAT))
    u_tx (.clk(clk), .rst_n(rst_n), .run(run), .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re),
          .rb_sel(rb_sel[0]), .t_wrdy(), .t_rrdy(), .t_rdata(rd0), .irq(), .s_tdata(s_d), .s_tvalid(s_v), .s_tready(s_r),
          .s_tlast(s_l), .txd(txd), .cts_n(flow ? rts_n : 1'b0));
  grv_pe_uart_rx #(.W(W), .CW(W / NC), .NC(NC), .DEPTH(16), .CTRL0(32'h1), .TIMING0(TIMING), .FORMAT0(FORMAT))
    u_rx (.clk(clk), .rst_n(rst_n), .run(run), .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re),
          .rb_sel(rb_sel[1]), .t_wrdy(), .t_rrdy(), .t_rdata(rd1), .irq(), .m_tdata(m_d), .m_tvalid(m_v), .m_tready(m_r),
          .m_tlast(m_l), .rxd(txd), .rts_n(rts_n));
  reg [W-1:0] exp_d [0:N-1]; reg exp_l [0:N-1];
  integer i, sent = 0, got = 0, err = 0, seed = SEED;
  // stimulus
  initial begin
    for (i = 0; i < N; i = i + 1) begin
      exp_d[i] = {$random(seed), $random(seed)};
      exp_l[i] = ($random(seed) & 3) == 0 || i == N - 1;
    end
    repeat (5) @(posedge clk); rst_n = 1; run = 1;
  end
  always @(posedge clk) if (rst_n) begin
    if (s_v && s_r) begin sent = sent + 1; s_v <= 0; end
    if ((!s_v || s_r) && sent < N && ($random(seed) & 1)) begin
      s_v <= 1; s_d <= exp_d[sent]; s_l <= exp_l[sent];
    end
    m_r <= flow ? (($random(seed) & 15) == 0) : (($random(seed) & 3) != 0);
    if (m_v && m_r && !text) begin
      if (m_d !== exp_d[got] || (gapf && m_l !== exp_l[got])) begin
        if (err < 5) $display("MISMATCH %0d: %h/%b expected %h/%b", got, m_d, m_l, exp_d[got], exp_l[got]);
        err = err + 1;
      end
      got = got + 1;
    end
  end
  // line decoder for TEXT mode
  localparam integer BT = TIMING / 256;
  integer nchar = 0, ci = 0, k, si = 0, di = 0;
  reg [7:0] c;
  reg [8*80:1] dummy;
  function [7:0] hexc(input [3:0] d); hexc = (d < 10) ? 8'h30 + d : 8'h37 + d; endfunction
  initial if (text) begin
    @(posedge rst_n);
    forever begin
      @(negedge txd);
      #(BT * 10 / 2);
      for (k = 0; k < 8; k = k + 1) begin #(BT * 10); c[k] = txd; end
      #(BT * 10);
      if (FORMAT[1:0] != 0) #(BT * 10);
      // expected character
      if (di < (W + 3) / 4) begin
        if (c !== hexc(exp_d[si] >> (4 * ((W + 3) / 4 - 1 - di)))) begin
          if (err < 5) $display("TEXT MISMATCH sample %0d digit %0d: %h", si, di, c); err = err + 1;
        end
        di = di + 1;
      end else begin
        if (c !== (exp_l[si] ? 8'h0A : 8'h20)) begin
          if (err < 5) $display("TEXT SEPARATOR MISMATCH sample %0d: %h", si, c); err = err + 1;
        end
        di = 0; si = si + 1;
      end
    end
  end
  initial begin : finish
    integer t;
    for (t = 0; t < 4000000; t = t + 1) begin
      @(posedge clk);
      if (!text && got == N) t = 4000000;
      if (text && si == N) t = 4000000;
    end
    if (!text && got != N) begin $display("TIMEOUT: %0d of %0d samples", got, N); err = err + 1; end
    if (text && si != N) begin $display("TIMEOUT: %0d of %0d text samples", si, N); err = err + 1; end
    if (err == 0) $display("PASS"); else $display("FAIL %0d", err);
    $finish;
  end
endmodule
