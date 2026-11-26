// tb_dma - DMA engine: channel 0 (MM2S) reads buffers from memory into a stream, channel 1 (S2MM)
// writes that stream back to memory. Both share grv_dma_bus, which shares the memory with a random
// "CPU" through grv_mem_arb; the memory answers after a random delay.
//   MODE 0 SINGLE -> SINGLE      1 DESC -> DESC (different block lengths)   2 RING+FLOW both, CPU here
//   3 FRAME tlast -> DESC + EOFL (packets)  4 address window error  5 MM2S RING replay -> SINGLE
`timescale 1ns/1ps
module tb_dma;
  parameter integer MODE = 0, CW = 16, NC = 1, CB = 2, MSBA = 0, N = 96, LAT = 3, SEED = 1, BURST = 0, GAP = 0;
  localparam integer W = CW * NC, EB = NC * CB, EPW = (EB >= 4) ? 1 : 4 / EB;
  localparam [31:0] BASE = 32'h1000_0000;
  reg clk = 0, rst_n = 0, run = 0;
  always #5 clk = ~clk;
  reg [15:0] rb_addr; reg [31:0] rb_wdata; reg rb_we = 0, rb_re = 0; reg [1:0] rb_sel = 0;
  wire [31:0] rd0, rd1;
  function [31:0] rdata_of(input integer t); rdata_of = t ? rd1 : rd0; endfunction
  `include "rb_tasks.vh"

  // ------------------------------------------------ DUT
  wire [W-1:0] st_d; wire st_v, st_l; wire st_r;
  reg  stall;
  wire [1:0]  rq_valid, rq_gnt, rq_done, rq_prio;
  wire [63:0] rq_addr, rq_wdata;
  wire [7:0]  rq_wstrb, rq_burst;
  wire [31:0] rq_rdata; wire rq_err; wire [1:0] rq_ecode;
  reg  [31:0] win_lo = 32'h0, win_hi = 32'hFFFF_FFFF;
  wire        d_valid, d_ready; wire [31:0] d_addr, d_wdata, d_rdata; wire [3:0] d_wstrb;
  grv_dma_ch #(.DIR(0), .W(W), .CW(CW), .NC(NC), .CB(CB), .DEPTH(16)) u_c0 (.clk(clk), .rst_n(rst_n), .run(run),
    .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re), .rb_sel(rb_sel[0]), .t_wrdy(), .t_rrdy(),
    .t_rdata(rd0), .irq(), .s_tdata({W{1'b0}}), .s_tvalid(1'b0), .s_tready(), .s_tlast(1'b0),
    .m_tdata(st_d), .m_tvalid(st_v), .m_tready(st_r), .m_tlast(st_l),
    .rq_valid(rq_valid[0]), .rq_addr(rq_addr[31:0]), .rq_wdata(rq_wdata[31:0]), .rq_wstrb(rq_wstrb[3:0]),
    .rq_burst(rq_burst[3:0]), .rq_prio(rq_prio[0]), .rq_gnt(rq_gnt[0]), .rq_done(rq_done[0]), .rq_rdata(rq_rdata),
    .rq_err(rq_err), .rq_ecode(rq_ecode));
  assign st_r = !stall;
  grv_dma_ch #(.DIR(1), .W(W), .CW(CW), .NC(NC), .CB(CB), .DEPTH(16)) u_c1 (.clk(clk), .rst_n(rst_n), .run(run),
    .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re), .rb_sel(rb_sel[1]), .t_wrdy(), .t_rrdy(),
    .t_rdata(rd1), .irq(), .s_tdata(st_d), .s_tvalid(st_v && !stall), .s_tready(), .s_tlast(st_l),
    .m_tdata(), .m_tvalid(), .m_tready(1'b0), .m_tlast(),
    .rq_valid(rq_valid[1]), .rq_addr(rq_addr[63:32]), .rq_wdata(rq_wdata[63:32]), .rq_wstrb(rq_wstrb[7:4]),
    .rq_burst(rq_burst[7:4]), .rq_prio(rq_prio[1]), .rq_gnt(rq_gnt[1]), .rq_done(rq_done[1]), .rq_rdata(rq_rdata),
    .rq_err(rq_err), .rq_ecode(rq_ecode));
  // the S2MM channel must accept whenever the stream is valid (no DROP here): stall the source otherwise
  always @* stall = st_v && !u_c1.s_tready;
  grv_dma_bus #(.NCH(2)) u_bus (.clk(clk), .rst_n(rst_n), .rq_valid(rq_valid), .rq_addr(rq_addr), .rq_wdata(rq_wdata),
    .rq_wstrb(rq_wstrb), .rq_burst(rq_burst), .rq_prio(rq_prio), .rq_gnt(rq_gnt), .rq_done(rq_done),
    .rq_rdata(rq_rdata), .rq_err(rq_err), .rq_ecode(rq_ecode), .win_lo(win_lo), .win_hi(win_hi), .timeout(16'd200),
    .m_mem_valid(d_valid), .m_mem_addr(d_addr), .m_mem_wdata(d_wdata), .m_mem_wstrb(d_wstrb),
    .m_mem_ready(d_ready), .m_mem_rdata(d_rdata));
  // CPU and arbiter
  reg c_valid = 0; reg [31:0] c_addr, c_wdata; reg [3:0] c_wstrb; wire c_ready; wire [31:0] c_rdata;
  wire m_valid; wire [31:0] m_addr, m_wdata; wire [3:0] m_wstrb; reg m_ready = 0; reg [31:0] m_rdata;
  grv_mem_arb #(.MAXWAIT(8)) u_arb (.clk(clk), .rst_n(rst_n), .c_valid(c_valid), .c_addr(c_addr), .c_wdata(c_wdata),
    .c_wstrb(c_wstrb), .c_ready(c_ready), .c_rdata(c_rdata), .d_valid(d_valid), .d_addr(d_addr), .d_wdata(d_wdata),
    .d_wstrb(d_wstrb), .d_ready(d_ready), .d_rdata(d_rdata), .m_valid(m_valid), .m_addr(m_addr), .m_wdata(m_wdata),
    .m_wstrb(m_wstrb), .m_ready(m_ready), .m_rdata(m_rdata));

  // ------------------------------------------------ memory: 64 KB at BASE, random delay
  reg [31:0] mem [0:16383];
  integer lat = 0, seed = SEED, k;
  reg [31:0] pa; reg [3:0] ps; reg pv = 0;
  always @(posedge clk) begin
    m_ready <= 1'b0;
    if (m_valid && !m_ready) begin
      if (!pv) begin pv <= 1; lat = 1 + ($random(seed) & 255) % LAT; pa <= m_addr; end
      else begin
        if (m_addr !== pa) begin $display("PROTOCOL: address changed while waiting"); $finish; end
        lat = lat - 1;
        if (lat <= 0) begin
          m_ready <= 1'b1; pv <= 0;
          k = (m_addr - BASE) >> 2;
          if (k < 0 || k > 16383) m_rdata <= 32'hDEAD_BEEF;
          else begin
            m_rdata <= mem[k];
            if (m_wstrb[0]) mem[k][7:0]   <= m_wdata[7:0];
            if (m_wstrb[1]) mem[k][15:8]  <= m_wdata[15:8];
            if (m_wstrb[2]) mem[k][23:16] <= m_wdata[23:16];
            if (m_wstrb[3]) mem[k][31:24] <= m_wdata[31:24];
          end
        end
      end
    end
  end
  // random CPU traffic in 0x0000 .. 0x00FF of the memory
  always @(posedge clk) if (rst_n) begin
    if (c_valid && c_ready) c_valid <= 1'b0;
    else if (!c_valid && ($random(seed) & 3) == 0) begin
      c_valid <= 1'b1; c_addr <= BASE + (($random(seed) & 63) << 2); c_wdata <= $random(seed);
      c_wstrb <= ($random(seed) & 1) ? 4'hF : 4'h0;
    end
  end

  // ------------------------------------------------ element helpers
  function [8*EB-1:0] rnd_elem(input integer dummy);
    integer c, b;
    reg [8*CB-1:0] v;
    reg [CW-1:0] x;
    begin
      for (c = 0; c < NC; c = c + 1) begin
        x = $random(seed);
        for (b = 0; b < 8 * CB; b = b + 1)
          if (MSBA) v[b] = (b >= 8 * CB - CW) ? x[b - (8 * CB - CW)] : 1'b0;
          else v[b] = (b < CW) ? x[b] : x[CW - 1];
        rnd_elem[c * 8 * CB +: 8 * CB] = v;
      end
    end
  endfunction
  function [8*EB-1:0] get_elem(input [31:0] addr, input integer i);   // element i of the buffer at addr
    integer b, by;
    begin
      for (b = 0; b < EB; b = b + 1) begin
        by = (addr - BASE) + i * EB + b;
        get_elem[8 * b +: 8] = mem[by >> 2][8 * (by & 3) +: 8];
      end
    end
  endfunction
  task put_elem(input [31:0] addr, input integer i, input [8*EB-1:0] e);
    integer b, by;
    begin
      for (b = 0; b < EB; b = b + 1) begin
        by = (addr - BASE) + i * EB + b;
        mem[by >> 2][8 * (by & 3) +: 8] = e[8 * b +: 8];
      end
    end
  endtask

  // ------------------------------------------------ test
  localparam [31:0] A = BASE + 32'h1000, B = BASE + 32'h6000, D0 = BASE + 32'hB000, D1 = BASE + 32'hB100;
  reg [8*EB-1:0] ref_e [0:4*N-1];
  integer i, j, err = 0, nref = 0, t;
  reg [31:0] v, v2;
  localparam [31:0] CT = (BURST << 12) | (GAP << 16);
  task wait_done(input integer ch);
    begin
      v = 0;
      for (t = 0; t < 200000 && !v[1] && !v[3]; t = t + 1) begin repeat (8) @(posedge clk); rb_read(ch, 16'h04, v); end
      if (!v[1]) begin $display("channel %0d not done: status %h", ch, v); err = err + 1; end
    end
  endtask
  task check_buf(input [31:0] addr, input integer first, input integer n);
    integer q;
    begin
      for (q = 0; q < n; q = q + 1)
        if (get_elem(addr, q) !== ref_e[first + q]) begin
          if (err < 6) $display("DATA %0d at %h+%0d: %h expected %h", first + q, addr, q, get_elem(addr, q), ref_e[first + q]);
          err = err + 1;
        end
    end
  endtask
  task desc(input [31:0] at, input [31:0] next, input [31:0] buf_, input integer len, input own, input irq, input eof);
    begin
      mem[(at - BASE) >> 2] = next; mem[((at - BASE) >> 2) + 1] = buf_;
      mem[((at - BASE) >> 2) + 2] = {own, 5'd0, eof, irq, len[23:0]}; mem[((at - BASE) >> 2) + 3] = 32'd0;
    end
  endtask
  integer L1, L2, L3, R, hw, sw, cnt, n_in, n_out, rsz;
  initial begin
    for (i = 0; i < 16384; i = i + 1) mem[i] = 32'hA5A5_A5A5;
    repeat (4) @(posedge clk); @(negedge clk); rst_n = 1; run = 1;
    case (MODE)
      0: begin
        for (i = 0; i < N; i = i + 1) begin ref_e[i] = rnd_elem(0); put_elem(A, i, ref_e[i]); end
        rb_write(1, 16'h08, B); rb_write(1, 16'h0C, N); rb_write(1, 16'h00, 32'h1 | CT | (MSBA << 9));
        rb_write(0, 16'h08, A); rb_write(0, 16'h0C, N); rb_write(0, 16'h00, 32'h1 | CT | (MSBA << 9) | (1 << 24));
        wait_done(0); wait_done(1);
        check_buf(B, 0, N);
        // the word after the block keeps its bytes beyond the last element
        if (((N * EB) & 3) != 0 && mem[((B - BASE) + N * EB) >> 2][31:24] !== 8'hA5) begin
          $display("partial word: bytes after the block were written"); err = err + 1;
        end
        rb_read(1, 16'h10, v); if (v != N) begin $display("HW_IDX %0d", v); err = err + 1; end
        rb_read(1, 16'h20, v); if (v != N) begin $display("TOTAL %0d", v); err = err + 1; end
      end
      1: begin
        L1 = N / 3 + 1; L2 = N / 4; L3 = N - L1 - L2;
        for (i = 0; i < N; i = i + 1) ref_e[i] = rnd_elem(0);
        for (i = 0; i < L1; i = i + 1) put_elem(A, i, ref_e[i]);
        for (i = 0; i < L2; i = i + 1) put_elem(A + 32'h1000, i, ref_e[L1 + i]);
        for (i = 0; i < L3; i = i + 1) put_elem(A + 32'h2000, i, ref_e[L1 + L2 + i]);
        desc(D0, D0 + 16, A, L1, 1, 0, 0); desc(D0 + 16, D0 + 32, A + 32'h1000, L2, 1, 0, 0);
        desc(D0 + 32, 0, A + 32'h2000, L3, 1, 1, 0);
        // S2MM: two descriptors, the first one not owned yet (the channel must wait for KICK)
        desc(D1, D1 + 16, B, N / 2, 1, 1, 0); desc(D1 + 16, 0, B + 32'h1000, N - N / 2, 0, 1, 0);
        rb_write(1, 16'h1C, D1); rb_write(1, 16'h00, 32'h9 | CT | (MSBA << 9) | (1 << 4));
        rb_write(0, 16'h1C, D0); rb_write(0, 16'h00, 32'h9 | CT | (MSBA << 9));
        for (t = 0; t < 20000; t = t + 1) begin rb_read(1, 16'h04, v); if (v[4]) t = 20000; end
        if (!v[4]) begin $display("S2MM did not stall on OWN = 0"); err = err + 1; end
        mem[((D1 + 16 - BASE) >> 2) + 2][31] = 1'b1;
        rb_write(1, 16'h30, 0);                         // KICK
        wait_done(0); wait_done(1);
        check_buf(B, 0, N / 2); check_buf(B + 32'h1000, N / 2, N - N / 2);
        v = mem[((D1 - BASE) >> 2) + 3]; v2 = mem[((D1 - BASE) >> 2) + 2];
        if (v !== {1'b1, 7'd0, 24'd0} + (N / 2) || v2[31]) begin $display("descriptor write-back %h %h", v, v2); err = err + 1; end
        v = mem[((D0 + 32 - BASE) >> 2) + 3];
        if (v !== {1'b1, 7'd0, 24'd0} + L3) begin $display("MM2S descriptor write-back %h", v); err = err + 1; end
      end
      2: begin
        // MM2S ring (size R, the CPU writes and advances SW_IDX) -> S2MM ring (size R, the CPU reads)
        R = 8 * EPW;
        for (i = 0; i < N; i = i + 1) ref_e[i] = rnd_elem(0);
        rb_write(0, 16'h08, A); rb_write(0, 16'h0C, R); rb_write(0, 16'h14, 0);
        rb_write(1, 16'h08, B); rb_write(1, 16'h0C, R); rb_write(1, 16'h14, 0);
        rb_write(1, 16'h00, 32'h85 | CT | (MSBA << 9));
        rb_write(0, 16'h00, 32'h85 | CT | (MSBA << 9));
        n_in = 0; n_out = 0; sw = 0;
        for (t = 0; t < 4000 && n_out < N; t = t + 1) begin
          // producer: fill whole words while there is room (one slot kept free)
          rb_read(0, 16'h10, v); hw = v;
          while (n_in < N && ((hw - n_in % R - 1 + 2 * R) % R) >= EPW) begin
            for (j = 0; j < EPW; j = j + 1) put_elem(A, (n_in + j) % R, ref_e[(n_in + j) < N ? n_in + j : 0]);
            n_in = n_in + EPW;
            rb_write(0, 16'h14, n_in % R);
          end
          // consumer
          rb_read(1, 16'h10, v); hw = v;
          while (sw != hw && n_out < N) begin
            if (get_elem(B, sw) !== ref_e[n_out]) begin
              if (err < 6) $display("RING DATA %0d: %h expected %h", n_out, get_elem(B, sw), ref_e[n_out]); err = err + 1;
            end
            n_out = n_out + 1; sw = (sw + 1) % R;
            if (sw % EPW == 0) rb_write(1, 16'h14, sw);
          end
          repeat (($random(seed) & 31)) @(posedge clk);
        end
        if (n_out < N) begin $display("RING: %0d of %0d samples", n_out, N); err = err + 1; end
      end
      3: begin
        // FRAME = 5: tlast every 5 samples; S2MM descriptors of 8 samples end early at tlast
        for (i = 0; i < 20; i = i + 1) begin ref_e[i] = rnd_elem(0); put_elem(A, i, ref_e[i]); end
        for (i = 0; i < 4; i = i + 1) desc(D1 + 16 * i, (i == 3) ? 0 : D1 + 16 * (i + 1), B + 32'h100 * i, 8, 1, 0, 0);
        rb_write(1, 16'h1C, D1); rb_write(1, 16'h00, 32'h409 | CT | (MSBA << 9));
        rb_write(0, 16'h24, 5); rb_write(0, 16'h08, A); rb_write(0, 16'h0C, 20); rb_write(0, 16'h00, 32'h1 | CT | (MSBA << 9));
        wait_done(0); wait_done(1);
        for (i = 0; i < 4; i = i + 1) begin
          check_buf(B + 32'h100 * i, 5 * i, 5);
          v = mem[((D1 + 16 * i - BASE) >> 2) + 3];
          if (v !== {1'b1, 6'd0, 1'b1, 24'd5}) begin $display("packet %0d status %h", i, v); err = err + 1; end
        end
      end
      4: begin
        win_lo = BASE; win_hi = B - 1;                  // B is outside
        for (i = 0; i < N; i = i + 1) begin ref_e[i] = rnd_elem(0); put_elem(A, i, ref_e[i]); end
        rb_write(1, 16'h08, B); rb_write(1, 16'h0C, N); rb_write(1, 16'h00, 32'h1 | (1 << 6) | (1 << 8));
        rb_write(0, 16'h08, A); rb_write(0, 16'h0C, N); rb_write(0, 16'h00, 32'h1);
        for (t = 0; t < 2000; t = t + 1) begin rb_read(1, 16'h04, v); if (v[3]) t = 2000; end
        if (!v[3] || v[7:6] != 2'd2 || !v[8]) begin $display("expected a window error: status %h", v); err = err + 1; end
        rb_read(1, 16'h28, v); if (v != B) begin $display("ERR_ADDR %h", v); err = err + 1; end
        if (mem[(B - BASE) >> 2] !== 32'hA5A5_A5A5) begin $display("write outside the window"); err = err + 1; end
      end
      5: begin
        // MM2S ring of R samples, no FLOW: replayed three times into a SINGLE block
        R = 4 * EPW;
        for (i = 0; i < R; i = i + 1) begin ref_e[i] = rnd_elem(0); put_elem(A, i, ref_e[i]); end
        for (i = R; i < 3 * R; i = i + 1) ref_e[i] = ref_e[i % R];
        rb_write(1, 16'h08, B); rb_write(1, 16'h0C, 3 * R); rb_write(1, 16'h00, 32'h1 | (MSBA << 9));
        rb_write(0, 16'h08, A); rb_write(0, 16'h0C, R); rb_write(0, 16'h00, 32'h5 | (MSBA << 9));
        wait_done(1);
        check_buf(B, 0, 3 * R);
        rb_write(0, 16'h00, 32'h2);                    // ABORT
        rb_read(0, 16'h04, v); repeat (20) @(posedge clk); rb_read(0, 16'h04, v);
        if (v[0]) begin $display("ABORT: still busy %h", v); err = err + 1; end
      end
      default: ;
    endcase
    if (err == 0) $display("PASS"); else $display("FAIL %0d", err);
    $finish;
  end
  initial begin #50000000; $display("FAIL global timeout"); $finish; end
endmodule
