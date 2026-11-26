// tb_i2s - I2S endpoints back to back. TEST 0: transmitter master -> receiver slave; TEST 1: receiver
// master -> transmitter slave. An independent monitor decodes the pins by the frame format (ws edges,
// MSB offset 1 for I2S, 0 for left-justified, SLOT - DBITS for right-justified) and checks the frames
// against the samples sent; the receiver's samples are checked against them too.
`timescale 1ns/1ps
module tb_i2s;
  parameter integer TEST = 0, DB = 16, NC = 2, SLOT = 16, JUST = 0, MONO_R = 0, DUP = 0, WSINV = 0;
  parameter integer HALF = 5 * 256, N = 60, SEED = 1, DEBUG = 0;
  localparam integer W = DB * NC;
  localparam [31:0] FMT = (SLOT - 1) | (JUST << 8) | (MONO_R << 10) | (DUP << 11) | (WSINV << 13) | (1 << 16);
  localparam integer LL = ((JUST == 0) ^ WSINV) ? 0 : 1;          // ws level of the left channel
  localparam integer OFF = (JUST == 0) ? 1 : (JUST == 1) ? 0 : SLOT - DB;
  reg clk = 0, rst_n = 0, run = 0;
  always #5 clk = ~clk;
  reg [15:0] rb_addr; reg [31:0] rb_wdata; reg rb_we = 0, rb_re = 0; reg [1:0] rb_sel = 0;
  wire [31:0] rd0, rd1;
  function [31:0] rdata_of(input integer t); rdata_of = t ? rd1 : rd0; endfunction
  `include "rb_tasks.vh"

  reg  [W-1:0] s_d; reg s_v = 0; wire s_r;
  wire [W-1:0] m_d; wire m_v;
  wire t_bclk, t_ws, t_mclk, r_bclk, r_ws, r_mclk, sd;
  wire bclk = (TEST == 0) ? t_bclk : r_bclk;
  wire ws   = (TEST == 0) ? t_ws : r_ws;
  grv_pe_i2s_tx #(.DBITS(DB), .NC(NC), .DEPTH(16), .ROLE(TEST == 0 ? 0 : 1), .CTRL0(32'h1), .TIMING0(HALF),
                  .FORMAT0(FMT), .MCLK0(1))
    u_t (.clk(clk), .rst_n(rst_n), .run(run), .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re),
         .rb_sel(rb_sel[0]), .t_wrdy(), .t_rrdy(), .t_rdata(rd0), .irq(), .s_tdata(s_d), .s_tvalid(s_v), .s_tready(s_r),
         .s_tlast(1'b0), .bclk_o(t_bclk), .ws_o(t_ws), .mclk_o(t_mclk), .bclk_i(r_bclk), .ws_i(r_ws), .sd_o(sd));
  grv_pe_i2s_rx #(.DBITS(DB), .NC(NC), .DEPTH(16), .ROLE(TEST == 0 ? 1 : 0), .CTRL0(32'h1), .TIMING0(HALF),
                  .FORMAT0(FMT), .MCLK0(2))
    u_r (.clk(clk), .rst_n(rst_n), .run(run), .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re),
         .rb_sel(rb_sel[1]), .t_wrdy(), .t_rrdy(), .t_rdata(rd1), .irq(), .m_tdata(m_d), .m_tvalid(m_v), .m_tready(1'b1),
         .m_tlast(), .bclk_o(r_bclk), .ws_o(r_ws), .mclk_o(r_mclk), .bclk_i(t_bclk), .ws_i(t_ws), .sd_i(sd));

  reg [W-1:0] ex [0:N-1];
  integer i, sent = 0, seed = SEED, err = 0;
  initial begin
    for (i = 0; i < N; i = i + 1) begin
      ex[i] = {$random(seed), $random(seed)};
      while (ex[i][DB-1:0] == 0) ex[i] = $random(seed);
    end
    repeat (5) @(posedge clk); @(negedge clk); rst_n = 1; run = 1;
  end
  always @(posedge clk) if (rst_n) begin
    if (s_v && s_r) begin sent = sent + 1; s_v <= 0; end
    if ((!s_v || s_r) && sent < N) begin s_v <= 1; s_d <= ex[sent]; end
  end
  // receiver output
  reg [W-1:0] got [0:4*N];
  integer ng = 0;
  always @(posedge clk) if (m_v) begin got[ng] = m_d; ng = ng + 1; end
  // monitor: bits and ws at the rising edges of bclk
  localparam integer MAXB = 2 * SLOT * (N + 12);
  reg mb [0:MAXB]; reg mw [0:MAXB];
  integer nb = 0;
  always @(posedge bclk) if (nb < MAXB) begin mb[nb] = sd; mw[nb] = ws; nb = nb + 1; end
  // mclk runs
  integer mclk_edges = 0;
  always @(posedge ((TEST == 0) ? t_mclk : r_mclk)) mclk_edges = mclk_edges + 1;

  // expected channel words of sample s
  function [DB-1:0] wordl(input [W-1:0] s);
    wordl = (NC == 2) ? s[DB-1:0] : (!MONO_R || DUP) ? s[DB-1:0] : {DB{1'b0}};
  endfunction
  function [DB-1:0] wordr(input [W-1:0] s);
    reg [2*DB-1:0] x;
    begin x = s; wordr = (NC == 2) ? x[2*DB-1:DB] : (MONO_R || DUP) ? s[DB-1:0] : {DB{1'b0}}; end
  endfunction

  integer e, k, f, nf, first, j, rx0, s0;
  function [W-1:0] rxv(input [W-1:0] s);
    rxv = (NC == 2) ? s : (MONO_R ? wordr(s) : wordl(s));
  endfunction
  reg [DB-1:0] fl [0:2*N+20]; reg [DB-1:0] fr [0:2*N+20];
  reg [DB-1:0] w;
  reg [31:0] st;
  initial begin
    #((2 * SLOT * (N + 10)) * (2 * HALF / 256 + 1) * 10 + 20000);
    // decode frames: a slot starts at index 0 and at each ws edge
    nf = 0;
    for (e = 0; e + OFF + DB < nb; e = e + 1) begin
      if ((e == 0 && mw[0] == LL) || (e > 0 && mw[e] != mw[e - 1])) begin
        w = 0;
        for (k = 0; k < DB; k = k + 1) w = {w[DB-2:0], mb[e + OFF + k]};
        if (mw[e] == LL) fl[nf] = w;
        else begin fr[nf] = w; nf = nf + 1; end
      end
    end
    // the first frame carrying ex[0]
    first = -1;
    for (f = 0; f < nf && first < 0; f = f + 1)
      if (fl[f] == wordl(ex[0]) && fr[f] == wordr(ex[0])) first = f;
    if (first < 0) begin $display("FAIL: ex[0] = %h never on the pins (%0d frames)", ex[0], nf); err = err + 1; end
    else for (j = 0; j < N; j = j + 1) begin
      if (first + j >= nf) begin
        if (err < 5) $display("FAIL: only %0d frames after the first", nf - first);
        err = err + 1; j = N;
      end else if (fl[first + j] !== wordl(ex[j]) || fr[first + j] !== wordr(ex[j])) begin
        if (err < 5) $display("FAIL: frame %0d: L %h R %h, expected %h %h", j, fl[first + j], fr[first + j],
                              wordl(ex[j]), wordr(ex[j]));
        err = err + 1;
      end
    end
    // receiver: the same samples, in order (mono: the channel MONO_R); a slave receiver may miss the
    // first frame (it locks at the first ws edge)
    rx0 = -1; s0 = 0;
    for (j = 0; j < 3 * N && rx0 < 0; j = j + 1)
      for (k = 0; k < 2 && rx0 < 0; k = k + 1)
        if (j < ng && got[j] == rxv(ex[k])) begin rx0 = j; s0 = k; end
    if (rx0 < 0) begin $display("FAIL: receiver never got ex[0] (%0d samples, first %h)", ng, got[0]); err = err + 1; end
    else for (j = s0; j < N; j = j + 1)
      if (rx0 + j - s0 >= ng || got[rx0 + j - s0] !== rxv(ex[j])) begin
        if (err < 8) $display("FAIL: rx[%0d] = %h expected %h", j, got[rx0 + j - s0], rxv(ex[j]));
        err = err + 1;
      end
    for (j = 0; j < 30 && j < ng; j = j + 1) if (DEBUG) $display("got[%0d] = %h  ex = %h", j, got[j], ex[j]);
    rb_read(1, 16'h10, st);
    if (st[15:0] != 0) begin $display("FAIL: receiver counted %0d errors", st[15:0]); err = err + 1; end
    if (mclk_edges < 10) begin $display("FAIL: no mclk"); err = err + 1; end
    if (err == 0) $display("PASS: %0d frames, %0d received", nf - first, ng);
    else $display("FAIL: %0d errors", err);
    $finish;
  end
endmodule
