// grv_pe_uart_rx - UART receiver endpoint: bytes on rxd become samples (design document, section 9.2).
// A character starts at a falling edge; half a bit time later the line must still be low; each bit
// is then sampled at its centre (majority of three samples one clock apart when the bit time is at
// least 16 clocks). A stop bit at 0 or a wrong parity is an error: the byte and the partial sample
// are discarded. NB = ceil(W/8) bytes make a sample, least significant first (FORMAT.MSBF: most).
// Framing: with FORMAT.GAP != 0 an idle line of GAP bit times discards a partial sample (an error)
// and puts tlast on the last complete one (held until the next start bit or the end of the gap);
// with GAP = 0, tlast every FORMAT.FRAME samples (0: never).
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_pe_uart_rx #(
  parameter integer W       = 16,
  parameter integer CW      = 16,
  parameter integer NC      = 1,
  parameter integer SIGNED  = 1,
  parameter integer FRAC    = 15,
  parameter integer DEPTH   = 64,
  parameter [31:0]  CTRL0   = 32'h1,
  parameter [31:0]  TIMING0 = 32'd120000,
  parameter [31:0]  FORMAT0 = 32'd0,
  parameter [31:0]  THRESH0 = 32'd1
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
  output wire [W-1:0] m_tdata,
  output wire         m_tvalid,
  input  wire         m_tready,
  output wire         m_tlast,
  input  wire         rxd,
  output reg          rts_n
);
  localparam integer NB = (W + 7) / 8;
  localparam integer AW = $clog2(DEPTH);
  localparam [31:0] INFO = {2'd0, NB[4:0] - 5'd1, 1'b0, 4'd1, AW[3:0], 2'd0, FRAC[5:0], SIGNED[0], (NC == 2), CW[5:0]};

  wire [31:0] ctrl, thresh, timing, format, k0, k1, k2, k3;
  wire        flush;
  wire [15:0] level;
  wire        en = ctrl[0] && run;
  wire [1:0]  parity = format[1:0];
  wire        msbf   = format[3];
  wire        flow   = format[4];
  wire        inv    = format[5];
  wire [7:0]  gap    = format[15:8];
  wire [15:0] frame  = format[31:16];

  // FIFO
  reg  [W-1:0] p_data;
  reg          p_last, p_push;
  wire         f_ready, f_valid;
  wire [W:0]   f_data;
  grv_fifo_fl #(.W(W + 1), .DEPTH(DEPTH)) u_fifo (.clk(clk), .rst_n(rst_n), .flush(flush),
    .s_data({p_last, p_data}), .s_valid(p_push), .s_ready(f_ready),
    .m_data(f_data), .m_valid(f_valid), .m_ready(m_tready && en), .level(level));
  assign m_tdata  = f_data[W-1:0];
  assign m_tlast  = f_data[W];
  assign m_tvalid = f_valid && en;
  wire ev_ovf = p_push && !f_ready;
  reg  ev_err;
  reg  busy_r;

  grv_pe_regs #(.DIR(0), .INFO(INFO), .CTRL0(CTRL0), .THRESH0(THRESH0), .TIMING0(TIMING0), .FORMAT0(FORMAT0))
  u_regs (.clk(clk), .rst_n(rst_n), .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re),
    .rb_sel(rb_sel), .t_wrdy(t_wrdy), .t_rrdy(t_rrdy), .t_rdata(t_rdata), .irq(irq),
    .ctrl(ctrl), .thresh(thresh), .timing(timing), .format(format), .k0(k0), .k1(k1), .k2(k2), .k3(k3),
    .flush(flush), .level(level), .full(!f_ready), .busy(busy_r), .ev_xfer(m_tvalid && m_tready),
    .ev_ovf(ev_ovf), .ev_unf(1'b0), .ev_err(ev_err));

  // line
  wire rx_s;
  grv_sync #(.N(1), .INIT(1'b1)) u_rx (.clk(clk), .rst_n(rst_n), .d(rxd), .q(rx_s));
  reg  [2:0] hist;
  wire       rx = hist[0];
  wire       maj = (hist[0] & hist[1]) | (hist[0] & hist[2]) | (hist[1] & hist[2]);
  wire       big = (timing >= 32'd4096);           // at least 16 clocks per bit
  wire       sbit = big ? maj : rx;

  localparam R_IDLE = 2'd0, R_START = 2'd1, R_BITS = 2'd2;
  reg [1:0]   st;
  reg [32:0]  acc;
  wire [32:0] nxt = acc + 33'd256;
  wire        half_end = (nxt >= {2'b0, timing[31:1]});
  wire        bit_end  = (nxt >= {1'b0, timing});
  reg [3:0]   bi;            // bit index: 0..7 data, 8 parity / stop, 9 stop
  reg [8:0]   sh;
  localparam integer AB = 8 * NB;
  reg [AB-1:0] asm_;         // sample being assembled
  reg [AB-1:0] asm_n;
  reg [4:0]   na;            // bytes assembled
  reg [W-1:0] hold;          // complete sample waiting for its tlast (GAP framing)
  reg         hv;
  reg [7:0]   idle;          // idle bit times (GAP framing)
  reg [32:0]  iacc;
  reg [15:0]  fc;            // FRAME counter
  wire [3:0]  nbits = (parity != 2'd0) ? 4'd10 : 4'd9;   // data + parity + stop, after the start bit

  always @(posedge clk) begin
    p_push <= 1'b0;
    ev_err <= 1'b0;
    rts_n  <= flow && ({16'd0, level} + 2 * NB + 2 > DEPTH);
    if (!rst_n || flush) begin
      st <= R_IDLE; hist <= 3'b111; hv <= 1'b0; na <= 5'd0; idle <= 8'd0; iacc <= 33'd0; fc <= 16'd0;
      busy_r <= 1'b0; rts_n <= 1'b0; acc <= 33'd0;
    end else begin
      hist <= {hist[1:0], rx_s ^ inv};
      case (st)
        R_IDLE: begin
          busy_r <= 1'b0;
          if (en && hist[1] && !hist[0]) begin
            st <= R_START; acc <= 33'd256; busy_r <= 1'b1;
            idle <= 8'd0; iacc <= 33'd0;
            if (hv) begin                       // a new character: the held sample was not the last
              p_data <= hold; p_last <= 1'b0; p_push <= 1'b1; hv <= 1'b0;
            end
          end else if (gap != 8'd0 && (hv || na != 5'd0)) begin
            // idle-line timer
            if (iacc + 33'd256 >= {1'b0, timing}) begin
              iacc <= iacc + 33'd256 - {1'b0, timing};
              idle <= idle + 1'b1;
              if (idle + 1'b1 >= gap) begin
                if (hv) begin p_data <= hold; p_last <= 1'b1; p_push <= 1'b1; hv <= 1'b0; end
                if (na != 5'd0) begin na <= 5'd0; ev_err <= 1'b1; end
                idle <= 8'd0;
              end
            end else iacc <= iacc + 33'd256;
          end
        end
        R_START: begin
          if (half_end) begin
            if (sbit) st <= R_IDLE;               // glitch
            else begin st <= R_BITS; acc <= nxt - {2'b0, timing[31:1]}; bi <= 4'd0; end
          end else acc <= nxt;
        end
        default: begin                          // R_BITS
          if (bit_end) begin
            acc <= nxt - {1'b0, timing};
            sh <= {sbit, sh[8:1]};
            bi <= bi + 1'b1;
            if (bi + 1'b1 == nbits) st <= R_IDLE;   // the stop bit: see below
          end else acc <= nxt;
        end
      endcase
      // character complete: evaluated in the clock after the stop bit was sampled
      if (st == R_BITS && bit_end && bi + 1'b1 == nbits) begin : done_char
        reg [7:0] b;
        reg       pok;
        if (parity == 2'd0) begin
          b = sh[8:1];
          pok = 1'b1;
        end else begin
          b = sh[7:0];
          pok = ((^sh[7:0]) ^ sh[8]) == (parity == 2'd2);
        end
        if (!sbit || !pok) begin
          ev_err <= 1'b1;
          na <= 5'd0;
        end else begin
          asm_n = msbf ? ((asm_ << 8) | b) : ((asm_ >> 8) | ({{(AB-8){1'b0}}, b} << (AB - 8)));
          asm_ <= asm_n;
          if (na + 1'b1 == NB) begin
            na <= 5'd0;
            if (gap != 8'd0) begin
              hold <= asm_n[W-1:0];
              hv <= 1'b1;
            end else begin
              p_data <= asm_n[W-1:0];
              p_last <= (frame != 16'd0) && (fc + 1'b1 == frame);
              fc <= (frame != 16'd0 && fc + 1'b1 == frame) ? 16'd0 : fc + 1'b1;
              p_push <= 1'b1;
            end
          end else na <= na + 1'b1;
        end
      end
    end
  end
endmodule

`default_nettype wire
