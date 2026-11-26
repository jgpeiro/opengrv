// grv_pe_uart_tx - UART transmitter endpoint: the samples of a stream are sent as bytes (design
// document, section 9.2). Each sample of W bits is NB = ceil(W/8) bytes, least significant first
// (FORMAT.MSBF: most significant first), or, with FORMAT.TEXT, ceil(W/4) hexadecimal digits followed
// by a space (inside a vector, VEC = 1) or a line feed. After a sample with tlast the line stays idle
// for FORMAT.GAP bit times.
//   FORMAT [1:0] PARITY (0 none, 1 even, 2 odd) [2] STOP2 [3] MSBF [4] FLOW (wait for cts_n low)
//          [5] INV [6] TEXT [15:8] GAP [31:16] FRAME (receiver only)
//   TIMING bit time, 24.8 clocks (at least 8 clocks)
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_pe_uart_tx #(
  parameter integer W       = 16,         // sample width (all components)
  parameter integer CW      = 16,
  parameter integer NC      = 1,
  parameter integer SIGNED  = 1,
  parameter integer FRAC    = 15,
  parameter integer DEPTH   = 64,
  parameter integer VEC     = 0,          // the stream carries vectors (text mode separators)
  parameter [31:0]  CTRL0   = 32'h1,
  parameter [31:0]  TIMING0 = 32'd120000,
  parameter [31:0]  FORMAT0 = 32'd0,
  parameter [31:0]  THRESH0 = 32'd0
)(
  input  wire         clk,
  input  wire         rst_n,
  input  wire         run,
  input  wire [15:0]  rb_addr,
  input  wire [31:0]  rb_wdata,
  input  wire         rb_we,
  input  wire         rb_re,
  input  wire         rb_sel,
  output wire         t_wrdy,
  output wire         t_rrdy,
  output wire [31:0]  t_rdata,
  output wire         irq,
  input  wire [W-1:0] s_tdata,
  input  wire         s_tvalid,
  output wire         s_tready,
  input  wire         s_tlast,
  output reg          txd,
  input  wire         cts_n
);
  localparam integer NB = (W + 7) / 8;
  localparam integer ND = (W + 3) / 4;
  localparam integer AW = $clog2(DEPTH);
  localparam [31:0] INFO = {2'd0, NB[4:0] - 5'd1, 1'b1, 4'd1, AW[3:0], 2'd0, FRAC[5:0], SIGNED[0], (NC == 2), CW[5:0]};

  wire [31:0] ctrl, thresh, timing, format, k0, k1, k2, k3;
  wire        flush;
  wire [15:0] level;
  wire        f_full;
  reg         busy_r, ev_err;
  wire        en = ctrl[0] && run;
  wire        f_ready;
  wire        drop = ctrl[3] && !f_ready;
  assign s_tready = f_ready || ctrl[3];
  wire        ev_ovf = s_tvalid && drop;

  wire [W:0]  f_data;
  wire        f_valid;
  reg         f_pop;
  grv_fifo_fl #(.W(W + 1), .DEPTH(DEPTH)) u_fifo (.clk(clk), .rst_n(rst_n), .flush(flush),
    .s_data({s_tlast, s_tdata}), .s_valid(s_tvalid && f_ready), .s_ready(f_ready),
    .m_data(f_data), .m_valid(f_valid), .m_ready(f_pop), .level(level));
  assign f_full = !f_ready;

  grv_pe_regs #(.DIR(1), .INFO(INFO), .CTRL0(CTRL0), .THRESH0(THRESH0), .TIMING0(TIMING0), .FORMAT0(FORMAT0))
  u_regs (.clk(clk), .rst_n(rst_n), .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re),
    .rb_sel(rb_sel), .t_wrdy(t_wrdy), .t_rrdy(t_rrdy), .t_rdata(t_rdata), .irq(irq),
    .ctrl(ctrl), .thresh(thresh), .timing(timing), .format(format), .k0(k0), .k1(k1), .k2(k2), .k3(k3),
    .flush(flush), .level(level), .full(f_full), .busy(busy_r), .ev_xfer(f_pop), .ev_ovf(ev_ovf),
    .ev_unf(1'b0), .ev_err(1'b0));

  wire [1:0] parity = format[1:0];
  wire       stop2  = format[2];
  wire       msbf   = format[3];
  wire       flow   = format[4];
  wire       inv    = format[5];
  wire       text   = format[6];
  wire [7:0] gap    = format[15:8];

  wire cts_s;
  grv_sync #(.N(1), .INIT(1'b1)) u_cts (.clk(clk), .rst_n(rst_n), .d(cts_n), .q(cts_s));

  // sample -> characters
  reg [W-1:0] smp;
  reg         slast;
  reg [4:0]   ci;           // index of the next character of the sample
  reg [4:0]   cn;           // characters of the sample
  localparam S_IDLE = 2'd0, S_CHAR = 2'd1, S_GAP = 2'd2;
  reg [1:0]   st;
  // character shifter
  reg [11:0]  sh;           // bits to send, LSB first
  reg [3:0]   nb;           // bits left
  reg [32:0]  acc;
  wire [32:0] nxt = acc + 33'd256;
  wire        bit_end = (nxt >= {1'b0, timing});
  reg         line;
  reg [7:0]   gcnt;

  function [7:0] hexc(input [3:0] d);
    hexc = (d < 4'd10) ? (8'h30 + d) : (8'h37 + d);
  endfunction
  // character i of the current sample
  reg [7:0] ch;
  reg [W+7:0] shs;
  integer k;
  always @* begin
    shs = {8'd0, smp};
    ch = 8'h0A;
    if (text) begin
      if (ci < ND) ch = hexc(shs[4 * (ND - 1 - ci) +: 4]);
      else ch = (VEC != 0 && !slast) ? 8'h20 : 8'h0A;
    end else begin
      ch = msbf ? shs[8 * (NB - 1 - ci) +: 8] : shs[8 * ci +: 8];
    end
  end
  wire par = ^ch;
  wire [11:0] frame = (parity == 2'd0) ? {3'b111, ch, 1'b0}
                                       : {2'b11, (parity == 2'd2) ? ~par : par, ch, 1'b0};
  wire [3:0]  fbits = 4'd10 + (parity != 2'd0) + stop2;

  always @(posedge clk) begin
    f_pop  <= 1'b0;
    ev_err <= 1'b0;
    if (!rst_n || flush) begin
      st <= S_IDLE; line <= 1'b1; acc <= 33'd0; busy_r <= 1'b0; nb <= 4'd0;
    end else begin
      case (st)
        S_IDLE: begin
          line <= 1'b1;
          busy_r <= 1'b0;
          if (en && f_valid && !f_pop) begin
            smp <= f_data[W-1:0];
            slast <= f_data[W];
            f_pop <= 1'b1;
            ci <= 5'd0;
            cn <= text ? ND + 1 : NB;
            nb <= 4'd0;
            st <= S_CHAR;
            busy_r <= 1'b1;
          end
        end
        S_CHAR: begin
          if (nb == 4'd0) begin
            // start the next character, or finish the sample
            if (ci == cn) begin
              if (slast && gap != 8'd0) begin
                st <= S_GAP; gcnt <= gap; acc <= 33'd0;
              end else st <= S_IDLE;
            end else if (!flow || !cts_s) begin
              sh <= frame >> 1;
              line <= 1'b0;
              nb <= fbits;
              acc <= 33'd0;
              ci <= ci + 1'b1;
            end
          end else begin
            if (bit_end) begin
              acc <= nxt - {1'b0, timing};
              line <= sh[0];
              sh <= {1'b1, sh[11:1]};
              nb <= nb - 1'b1;
              if (nb == 4'd1) line <= 1'b1;
            end else acc <= nxt;
          end
        end
        default: begin   // S_GAP
          line <= 1'b1;
          if (bit_end) begin
            acc <= nxt - {1'b0, timing};
            gcnt <= gcnt - 1'b1;
            if (gcnt == 8'd1) st <= S_IDLE;
          end else acc <= nxt;
        end
      endcase
    end
  end
  always @(posedge clk) txd <= (!rst_n) ? ~inv : (line ^ inv);
endmodule

`default_nettype wire
