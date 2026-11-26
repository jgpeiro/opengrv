// tb_gpio - GPIO endpoints. TEST 0: PARALLEL output (paced, clock out) -> STROBE input on that clock.
// TEST 1: PERIODIC input with clock out, pins driven here after each clock edge. TEST 2: CHANGE input
// with glitches shorter than FILTER. TEST 3: PWM output. TEST 4: SDM output against a reference model.
`timescale 1ns/1ps
module tb_gpio;
  parameter integer TEST = 0, DB = 8, NC = 1, N = 100, SEED = 1, OFS = 0, ORD1 = 0, DIV = 0;
  localparam integer W = DB * NC;
  reg clk = 0, rst_n = 0, run = 0;
  always #5 clk = ~clk;
  reg [15:0] rb_addr; reg [31:0] rb_wdata; reg rb_we = 0, rb_re = 0; reg [1:0] rb_sel = 0;
  wire [31:0] rd0, rd1;
  function [31:0] rdata_of(input integer t); rdata_of = t ? rd1 : rd0; endfunction
  `include "rb_tasks.vh"
  localparam [31:0] OMODE = (TEST == 3) ? 1 : (TEST == 4) ? 2 : 0;
  localparam [31:0] OFMT = OMODE | (OFS << 3) | (1 << 4) | (ORD1 << 5) | (2 << 8) | (DIV << 16);
  localparam [31:0] OTIM = (TEST == 0) ? 20 * 256 : (TEST == 4) ? 37 * 256 : 0;
  localparam [31:0] IMODE = (TEST == 0) ? 1 : (TEST == 2) ? 2 : 0;
  localparam [31:0] IFMT = IMODE | (OFS << 3) | (1 << 4) | (3 << 8) | (4 << 16);
  localparam integer NP = (TEST >= 3) ? NC : W;
  reg  [W-1:0] s_d; reg s_v = 0; wire s_r;
  wire [NP-1:0] pins;
  wire oclk, iclk;
  wire [W-1:0] m_d; wire m_v;
  reg  [W-1:0] drive;
  grv_pe_gpio_out #(.DBITS(DB), .NC(NC), .NPIN(NP), .DEPTH(16), .CTRL0(32'h0), .TIMING0(OTIM), .FORMAT0(OFMT))
    u_o (.clk(clk), .rst_n(rst_n), .run(run), .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re),
         .rb_sel(rb_sel[0]), .t_wrdy(), .t_rrdy(), .t_rdata(rd0), .irq(), .s_tdata(s_d), .s_tvalid(s_v), .s_tready(s_r),
         .s_tlast(1'b0), .pins_o(pins), .clk_o(oclk));
  wire [W-1:0] ipins = (TEST == 0) ? pins : drive;
  grv_pe_gpio_in #(.DBITS(DB), .NC(NC), .DEPTH(16), .CTRL0(32'h1), .TIMING0(32 * 256), .FORMAT0(IFMT))
    u_i (.clk(clk), .rst_n(rst_n), .run(run), .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re),
         .rb_sel(rb_sel[1]), .t_wrdy(), .t_rrdy(), .t_rdata(rd1), .irq(), .m_tdata(m_d), .m_tvalid(m_v), .m_tready(1'b1),
         .m_tlast(), .pins_i(ipins), .stb_i(oclk), .clk_o(iclk));
  reg [W-1:0] ex [0:N-1];
  integer i, sent = 0, got = 0, err = 0, seed = SEED;
  initial begin
    for (i = 0; i < N; i = i + 1) begin
      ex[i] = {$random(seed), $random(seed)};
      if (TEST == 2 && i > 0) while (ex[i] == ex[i - 1]) ex[i] = $random(seed);
      if (TEST == 2 && i == 0) while (ex[0] == 0) ex[0] = $random(seed);
    end
    drive = 0;
    repeat (5) @(posedge clk); @(negedge clk); rst_n = 1; run = 1;
    if (TEST == 0 || TEST >= 3) begin repeat (60) @(posedge clk); rb_write(0, 16'h00, 32'h1); end
  end
  // feed the output endpoint
  always @(posedge clk) if (rst_n) begin
    if (s_v && s_r) begin sent = sent + 1; s_v <= 0; end
    if ((!s_v || s_r) && sent < N) begin s_v <= 1; s_d <= ex[sent]; end
  end
  // TEST 1: pins follow the clock of the input endpoint
  reg ic_d = 0; integer di = 0;
  always @(posedge clk) if (TEST == 1) begin
    ic_d <= iclk;
    if (iclk && !ic_d && di < N) begin drive <= ex[di]; di = di + 1; end
  end
  // TEST 2: values with glitches
  initial if (TEST == 2) begin : chg
    integer j;
    @(posedge rst_n); repeat (20) @(posedge clk);
    for (j = 0; j < N; j = j + 1) begin
      @(posedge clk); drive <= ~ex[j]; @(posedge clk); drive <= ex[j] ^ 1;  // glitches shorter than FILTER
      @(posedge clk); drive <= ex[j];
      repeat (15 + ($random(seed) & 7)) @(posedge clk);
    end
  end
  // input endpoint output
  // pins driven here (TEST 1, 2) are offset binary when OFS: the endpoint flips each MSB
  function [W-1:0] xo(input [W-1:0] v);
    integer q;
    begin
      xo = v;
      if (TEST != 0 && OFS) for (q = 0; q < NC; q = q + 1) xo[q * DB + DB - 1] = ~v[q * DB + DB - 1];
    end
  endfunction
  reg first_chg = 1'b1;
  always @(posedge clk) if (m_v && TEST == 2 && first_chg) first_chg <= 1'b0;   // the value at enable
  else if (m_v && TEST <= 2) begin
    if (got < N && m_d !== xo(ex[got]) && !(TEST == 1 && got == 0)) begin
      if (err < 5) $display("MISMATCH %0d: %h expected %h", got, m_d, xo(ex[got])); err = err + 1;
    end
    got = got + 1;
  end
  // TEST 3, 4: the sample loaded into the output endpoint, and the pins
  reg [W-1:0] cur_d; integer li = 0; reg ld_d;
  integer c, x, y, i1 [0:1], i2 [0:1], n1, n2, dc = 0;
  reg [1:0] sdo;
  localparam integer FS = 1 << (DB - 1), IW = DB + 6;
  localparam integer IMAX = (1 << (IW - 1)) - 1, IMIN = -(1 << (IW - 1));
  function integer sat(input integer v); sat = (v > IMAX) ? IMAX : (v < IMIN) ? IMIN : v; endfunction
  function integer sx(input [DB-1:0] v); sx = v[DB-1] ? v - (1 << DB) : v; endfunction
  initial begin i1[0] = 0; i1[1] = 0; i2[0] = 0; i2[1] = 0; sdo = 0; end
  always @(posedge clk) if (rst_n && TEST >= 3) begin
    if (u_o.f_pop) begin
      if (u_o.f_data !== ex[li]) begin if (err < 5) $display("LOAD MISMATCH %0d", li); err = err + 1; end
      li = li + 1;
    end
    if (TEST == 4) begin
      if (dc == 0) begin
        for (c = 0; c < NC; c = c + 1) begin
          x = sx(u_o.cur[c * DB +: DB]); y = sdo[c] ? FS : -FS;
          n1 = sat(i1[c] + x - y); n2 = sat(i2[c] + n1 - y);
          i1[c] = n1; i2[c] = ORD1 ? 0 : n2; sdo[c] = ORD1 ? (n1 >= 0) : (n2 >= 0);
        end
        dc = DIV;
      end else dc = dc - 1;
    end
  end
  always @(posedge clk) if (rst_n && TEST == 4 && u_o.en) begin
    #1; if (u_o.sdo[NC-1:0] !== sdo[NC-1:0]) begin if (err < 5) $display("SDM MISMATCH at %0t", $time); err = err + 1; end
  end
  // TEST 3: duty of each period = offset-binary field of the sample loaded at its start
  integer hc [0:1], pcnt = 0;
  reg [W-1:0] pcur;
  initial begin hc[0] = 0; hc[1] = 0; end
  always @(posedge clk) if (rst_n && TEST == 3 && u_o.en) begin
    if (u_o.pc == 1) begin
      if (pcnt > 1) for (c = 0; c < NC; c = c + 1)
        if (hc[c] !== ((pcur[c * DB +: DB] ^ (1 << (DB - 1))) & ((1 << DB) - 1))) begin
          if (err < 5) $display("PWM MISMATCH period %0d comp %0d: %0d high, field %h", pcnt, c, hc[c], pcur); err = err + 1;
        end
      for (c = 0; c < NC; c = c + 1) hc[c] = 0;
      pcur = u_o.cur; pcnt = pcnt + 1;
    end
    for (c = 0; c < NC; c = c + 1) hc[c] = hc[c] + pins[c];
  end
  initial begin : finish
    integer t;
    for (t = 0; t < 1000000 && !((TEST <= 2 && got >= N) || (TEST >= 3 && li >= N)); t = t + 1) @(posedge clk);
    if (TEST <= 2 && got < N) begin $display("TIMEOUT %0d of %0d", got, N); err = err + 1; end
    if (TEST >= 3 && li < N) begin $display("TIMEOUT %0d of %0d", li, N); err = err + 1; end
    if (err == 0) $display("PASS"); else $display("FAIL %0d", err);
    $finish;
  end
endmodule
