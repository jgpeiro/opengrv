// grv_pe_spi_tx - SPI output endpoint (design document, section 9.3): samples to a converter (ROLE 0,
// master: one frame per component on every tick of the pacing timer, or as soon as a sample is there
// with TIMING = 0) or to an SPI master (ROLE 1, slave: the next component is loaded at the fall of
// cs_n and after every FBITS bits; an empty FIFO sends CMD as fill word and counts an underflow).
// Frame = (CMD & ~field mask) | field << DPOS, CMD_Q for the Q component; FORMAT.OFS sends offset
// binary. drdy is high while LEVEL >= THRESH, or (slave) while a sample loaded at the end of the
// last frame waits for the next one.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_pe_spi_tx #(
  parameter integer DBITS   = 12,
  parameter integer NC      = 1,
  parameter integer SIGNED  = 1,
  parameter integer FRAC    = 11,
  parameter integer DEPTH   = 32,
  parameter integer ROLE    = 0,
  parameter [31:0]  CTRL0   = 32'h1,
  parameter [31:0]  TIMING0 = 32'd0,
  parameter [31:0]  FORMAT0 = 32'h0000_000F,
  parameter [31:0]  THRESH0 = 32'd1,
  parameter [31:0]  SCLK0   = 32'd0,
  parameter [31:0]  CMD0    = 32'd0,
  parameter [31:0]  CMDQ0   = 32'd0,
  parameter [31:0]  CST0    = 32'h0001_0101
)(
  input  wire                clk,
  input  wire                rst_n,
  input  wire                run,
  input  wire [15:0]         rb_addr,
  input  wire [31:0]         rb_wdata,
  input  wire                rb_we,
  input  wire                rb_re,
  input  wire                rb_sel,
  output wire                t_wrdy,
  output wire                t_rrdy,
  output wire [31:0]         t_rdata,
  output wire                irq,
  input  wire [DBITS*NC-1:0] s_tdata,
  input  wire                s_tvalid,
  output wire                s_tready,
  input  wire                s_tlast,
  // master pins
  output wire                sclk_o,
  output wire                cs_n_o,
  output wire                mosi_o,
  // slave pins
  input  wire                sclk_i,
  input  wire                cs_n_i,
  input  wire                mosi_i,
  output wire                miso_o,
  output wire                miso_oe,
  output reg                 drdy
);
  localparam integer W  = DBITS * NC;
  localparam integer AW = $clog2(DEPTH);
  localparam [31:0] INFO = {2'd0, DBITS[4:0] - 5'd1, 1'b1, (ROLE != 0) ? 4'd3 : 4'd2, AW[3:0], 2'd0, FRAC[5:0],
                            SIGNED[0], (NC == 2), DBITS[5:0]};

  wire [31:0] ctrl, thresh, timing, format, k0, k1, k2, k3;
  wire        flush;
  wire [15:0] level;
  wire        en = ctrl[0] && run;
  wire [4:0]  fbits = format[4:0];
  wire [4:0]  dpos  = format[12:8];
  wire        cpha  = format[16], cpol = format[17], lsbf = format[18], ofs = format[19];
  wire [1:0]  sdly  = format[21:20];
  wire        f_ready, f_valid;
  wire [W:0]  f_data;
  reg         f_pop, ev_unf, ev_err;
  assign s_tready = f_ready || ctrl[3];
  grv_fifo_fl #(.W(W + 1), .DEPTH(DEPTH)) u_fifo (.clk(clk), .rst_n(rst_n), .flush(flush),
    .s_data({s_tlast, s_tdata}), .s_valid(s_tvalid && f_ready), .s_ready(f_ready),
    .m_data(f_data), .m_valid(f_valid), .m_ready(f_pop), .level(level));
  wire busy;

  grv_pe_regs #(.DIR(1), .INFO(INFO), .CTRL0(CTRL0), .THRESH0(THRESH0), .TIMING0(TIMING0), .FORMAT0(FORMAT0),
                .K00(SCLK0), .K10(CMD0), .K20(CMDQ0), .K30(CST0))
  u_regs (.clk(clk), .rst_n(rst_n), .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re),
    .rb_sel(rb_sel), .t_wrdy(t_wrdy), .t_rrdy(t_rrdy), .t_rdata(t_rdata), .irq(irq),
    .ctrl(ctrl), .thresh(thresh), .timing(timing), .format(format), .k0(k0), .k1(k1), .k2(k2), .k3(k3),
    .flush(flush), .level(level), .full(!f_ready), .busy(busy), .ev_xfer(f_pop),
    .ev_ovf(s_tvalid && !f_ready && ctrl[3]), .ev_unf(ev_unf), .ev_err(ev_err));

  wire pend;
  always @(posedge clk) drdy <= (({16'd0, level} >= thresh) && (level != 16'd0)) || pend;

  // frame of a component
  wire [31:0] dmask = ((DBITS >= 32) ? 32'hFFFF_FFFF : ((32'd1 << DBITS) - 1)) << dpos;
  function [31:0] frame(input [31:0] cmd, input [DBITS-1:0] c, input [4:0] pos, input o, input [31:0] m);
    reg [DBITS-1:0] f;
    begin
      f = c;
      f[DBITS-1] = f[DBITS-1] ^ o;
      frame = (cmd & ~m) | (({{(32-DBITS){1'b0}}, f} << pos) & m);
    end
  endfunction

  reg [W-1:0] smp;
  reg         ci;

  generate if (ROLE == 0) begin : g_master
    wire tick, mdone, mbusy;
    wire [31:0] rx;
    reg  mstart, act, have;
    wire paced = (timing >= 32'd256);
    grv_pace u_pace (.clk(clk), .rst_n(rst_n), .en(en), .timing(timing), .tick(tick));
    wire [DBITS-1:0] c0 = smp[DBITS-1:0];
    wire [DBITS-1:0] c1 = smp[W-1:W-DBITS];
    grv_spi_mcore u_m (.clk(clk), .rst_n(rst_n), .start(mstart), .tx(frame(ci ? k2 : k1, ci ? c1 : c0, dpos, ofs, dmask)),
      .fbits(fbits), .cpol(cpol), .cpha(cpha), .lsbf(lsbf), .half(k0[7:0]), .setup(k3[7:0]), .hold(k3[15:8]),
      .gap(k3[23:16]), .sdly(sdly), .miso_s(1'b0), .busy(mbusy), .done(mdone), .rx(rx), .sclk(sclk_o),
      .cs_n(cs_n_o), .mosi(mosi_o));
    assign busy = act;
    wire go = paced ? tick : (en && !act && f_valid && !f_pop);
    always @(posedge clk) begin
      mstart <= 1'b0; f_pop <= 1'b0; ev_unf <= 1'b0; ev_err <= 1'b0;
      if (!rst_n || flush) begin
        act <= 1'b0; ci <= 1'b0; have <= 1'b0;
      end else begin
        if (go) begin
          if (act) ev_err <= 1'b1;                  // overrun
          else if (f_valid) begin
            smp <= f_data[W-1:0]; f_pop <= 1'b1; have <= 1'b1;
            act <= 1'b1; ci <= 1'b0; mstart <= 1'b1;
          end else begin
            ev_unf <= 1'b1;
            if (ctrl[4] && have) begin act <= 1'b1; ci <= 1'b0; mstart <= 1'b1; end
          end
        end
        if (mdone) begin
          if (NC == 2 && !ci) begin ci <= 1'b1; mstart <= 1'b1; end
          else begin act <= 1'b0; ci <= 1'b0; end
        end
      end
    end
    assign miso_o = 1'b0;
    assign miso_oe = 1'b0;
    assign pend = 1'b0;
  end else begin : g_slave
    wire [2:0] s;
    grv_sync #(.N(3), .INIT(3'b010)) u_s (.clk(clk), .rst_n(rst_n), .d({mosi_i, cs_n_i, sclk_i}), .q(s));
    wire rxv, csf, csr, take;
    wire [31:0] rxw;
    wire [4:0] rbits;
    // next component to send
    wire [DBITS-1:0] nc0 = f_data[DBITS-1:0];
    wire [DBITS-1:0] nc1 = (NC == 2) ? f_data[W-1:W-DBITS] : f_data[DBITS-1:0];
    wire avail = f_valid && en;
    wire [31:0] word = ci ? frame(k2, smp[W-1:W-DBITS], dpos, ofs, dmask)
                          : (avail ? frame(k1, nc0, dpos, ofs, dmask) : k1);
    grv_spi_score u_sl (.clk(clk), .rst_n(rst_n), .sclk_s(s[0]), .cs_s(s[1]), .mosi_s(s[2]), .fbits(fbits),
      .cpol(cpol), .cpha(cpha), .lsbf(lsbf), .tx_word(word), .tx_fill(!ci && !avail), .tx_take(take), .rx_valid(rxv), .rx_word(rxw),
      .cs_fall(csf), .cs_rise(csr), .rx_bits(rbits), .miso(miso_o), .miso_oe(miso_oe));
    assign sclk_o = 1'b0; assign cs_n_o = 1'b1; assign mosi_o = 1'b0;
    assign busy = !s[1];
    // take is registered in the core: the word it loaded was computed in the previous clock
    reg av_d;                                    // avail when the core loaded the word
    always @(posedge clk) av_d <= avail && !f_pop;
    // a sample preloaded at the end of a frame waits for the next frame: keep drdy high
    reg pnd;
    assign pend = pnd;
    always @(posedge clk)
      if (!rst_n || flush || csf) pnd <= 1'b0;
      else if (take && !ci && av_d) pnd <= 1'b1;
    always @(posedge clk) begin
      f_pop <= 1'b0; ev_unf <= 1'b0; ev_err <= 1'b0;
      if (!rst_n || flush) begin
        ci <= 1'b0;
      end else begin
        if (take) begin
          if (ci) ci <= 1'b0;
          else if (av_d) begin
            smp <= f_data[W-1:0]; f_pop <= 1'b1;
            if (NC == 2) ci <= 1'b1;
          end else ev_unf <= 1'b1;
        end
      end
    end
  end endgenerate
endmodule

`default_nettype wire
