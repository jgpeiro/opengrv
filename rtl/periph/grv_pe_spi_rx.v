// grv_pe_spi_rx - SPI input endpoint (design document, section 9.3): samples from a converter
// (ROLE 0, master: one frame per component on every tick of the pacing timer, MOSI = CMD / CMD_Q)
// or from an SPI master (ROLE 1, slave: one component per FBITS bits while cs_n is low; the rise of
// cs_n puts tlast on the last complete sample and discards a partial one, which is an error).
// The component is the field of DBITS bits at FORMAT.DPOS of the frame; FORMAT.OFS converts offset
// binary to two's complement.
//   FORMAT [4:0] FBITS-1 [12:8] DPOS [16] CPHA [17] CPOL [18] LSBF [19] OFS [21:20] SDLY
//   0x20 SCLK [7:0] HALF   0x24 CMD   0x28 CMD_Q   0x2C CS_TIMING [7:0] SETUP [15:8] HOLD [23:16] GAP
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_pe_spi_rx #(
  parameter integer DBITS   = 12,         // component width = field width
  parameter integer NC      = 1,
  parameter integer SIGNED  = 1,
  parameter integer FRAC    = 11,
  parameter integer DEPTH   = 32,
  parameter integer ROLE    = 0,          // 0 master, 1 slave
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
  output wire [DBITS*NC-1:0] m_tdata,
  output wire                m_tvalid,
  input  wire                m_tready,
  output wire                m_tlast,
  // master pins
  output wire                sclk_o,
  output wire                cs_n_o,
  output wire                mosi_o,
  input  wire                miso_i,
  // slave pins
  input  wire                sclk_i,
  input  wire                cs_n_i,
  input  wire                mosi_i
);
  localparam integer W  = DBITS * NC;
  localparam integer AW = $clog2(DEPTH);
  localparam [31:0] INFO = {2'd0, DBITS[4:0] - 5'd1, 1'b0, (ROLE != 0) ? 4'd3 : 4'd2, AW[3:0], 2'd0, FRAC[5:0],
                            SIGNED[0], (NC == 2), DBITS[5:0]};

  wire [31:0] ctrl, thresh, timing, format, k0, k1, k2, k3;
  wire        flush;
  wire [15:0] level;
  wire        en = ctrl[0] && run;
  wire [4:0]  fbits = format[4:0];
  wire [4:0]  dpos  = format[12:8];
  wire        cpha  = format[16], cpol = format[17], lsbf = format[18], ofs = format[19];
  wire [1:0]  sdly  = format[21:20];

  reg  [W-1:0] p_data;
  reg          p_last, p_push, ev_err;
  wire         f_ready, f_valid;
  wire [W:0]   f_data;
  grv_fifo_fl #(.W(W + 1), .DEPTH(DEPTH)) u_fifo (.clk(clk), .rst_n(rst_n), .flush(flush),
    .s_data({p_last, p_data}), .s_valid(p_push), .s_ready(f_ready),
    .m_data(f_data), .m_valid(f_valid), .m_ready(m_tready && en), .level(level));
  assign m_tdata  = f_data[W-1:0];
  assign m_tlast  = f_data[W];
  assign m_tvalid = f_valid && en;
  wire busy;

  grv_pe_regs #(.DIR(0), .INFO(INFO), .CTRL0(CTRL0), .THRESH0(THRESH0), .TIMING0(TIMING0), .FORMAT0(FORMAT0),
                .K00(SCLK0), .K10(CMD0), .K20(CMDQ0), .K30(CST0))
  u_regs (.clk(clk), .rst_n(rst_n), .rb_addr(rb_addr), .rb_wdata(rb_wdata), .rb_we(rb_we), .rb_re(rb_re),
    .rb_sel(rb_sel), .t_wrdy(t_wrdy), .t_rrdy(t_rrdy), .t_rdata(t_rdata), .irq(irq),
    .ctrl(ctrl), .thresh(thresh), .timing(timing), .format(format), .k0(k0), .k1(k1), .k2(k2), .k3(k3),
    .flush(flush), .level(level), .full(!f_ready), .busy(busy), .ev_xfer(m_tvalid && m_tready),
    .ev_ovf(p_push && !f_ready), .ev_unf(1'b0), .ev_err(ev_err));

  // field of a received frame
  wire [31:0] fmask = (fbits == 5'd31) ? 32'hFFFF_FFFF : ((32'd1 << (fbits + 1'b1)) - 1'b1);
  function [DBITS-1:0] field(input [31:0] fr, input [4:0] pos, input o, input [31:0] m);
    reg [31:0] v;
    begin
      v = (fr & m) >> pos;
      field = v[DBITS-1:0];
      field[DBITS-1] = field[DBITS-1] ^ o;
    end
  endfunction

  reg [DBITS-1:0] comp0;
  reg             ci;              // component index (complex)

  generate if (ROLE == 0) begin : g_master
    wire tick, mdone, mbusy, miso_s;
    wire [31:0] rx;
    reg  mstart;
    grv_pace u_pace (.clk(clk), .rst_n(rst_n), .en(en), .timing(timing), .tick(tick));
    grv_sync #(.N(1)) u_s (.clk(clk), .rst_n(rst_n), .d(miso_i), .q(miso_s));
    grv_spi_mcore u_m (.clk(clk), .rst_n(rst_n), .start(mstart), .tx(ci ? k2 : k1), .fbits(fbits), .cpol(cpol),
      .cpha(cpha), .lsbf(lsbf), .half(k0[7:0]), .setup(k3[7:0]), .hold(k3[15:8]), .gap(k3[23:16]), .sdly(sdly),
      .miso_s(miso_s), .busy(mbusy), .done(mdone), .rx(rx), .sclk(sclk_o), .cs_n(cs_n_o), .mosi(mosi_o));
    reg act;
    assign busy = act;
    always @(posedge clk) begin
      mstart <= 1'b0; p_push <= 1'b0; ev_err <= 1'b0;
      if (!rst_n || flush) begin
        act <= 1'b0; ci <= 1'b0;
      end else begin
        if (tick) begin
          if (act) ev_err <= 1'b1;                 // overrun: the tick is skipped
          else begin act <= 1'b1; ci <= 1'b0; mstart <= 1'b1; end
        end
        if (mdone) begin
          if (NC == 2 && !ci) begin
            comp0 <= field(rx, dpos, ofs, fmask); ci <= 1'b1; mstart <= 1'b1;
          end else begin
            p_data <= (NC == 2) ? {field(rx, dpos, ofs, fmask), comp0} : field(rx, dpos, ofs, fmask);
            p_last <= 1'b0; p_push <= 1'b1; act <= 1'b0; ci <= 1'b0;
          end
        end
      end
    end
  end else begin : g_slave
    wire [2:0] s;
    grv_sync #(.N(3), .INIT(3'b010)) u_s (.clk(clk), .rst_n(rst_n), .d({mosi_i, cs_n_i, sclk_i}), .q(s));
    wire rxv, csf, csr, take, mo, moe;
    wire [31:0] rxw;
    wire [4:0] rbits;
    grv_spi_score u_sl (.clk(clk), .rst_n(rst_n), .sclk_s(s[0]), .cs_s(s[1] || !en), .mosi_s(s[2]), .fbits(fbits),
      .cpol(cpol), .cpha(cpha), .lsbf(lsbf), .tx_word(32'd0), .tx_fill(1'b1), .tx_take(take), .rx_valid(rxv), .rx_word(rxw),
      .cs_fall(csf), .cs_rise(csr), .rx_bits(rbits), .miso(mo), .miso_oe(moe));
    assign sclk_o = 1'b0; assign cs_n_o = 1'b1; assign mosi_o = 1'b0;
    reg [W-1:0] hold;
    reg         hv;
    assign busy = !s[1];
    always @(posedge clk) begin
      p_push <= 1'b0; ev_err <= 1'b0;
      if (!rst_n || flush) begin
        ci <= 1'b0; hv <= 1'b0;
      end else begin
        if (rxv) begin
          if (NC == 2 && !ci) begin
            comp0 <= field(rxw, dpos, ofs, fmask); ci <= 1'b1;
          end else begin
            ci <= 1'b0;
            hold <= (NC == 2) ? {field(rxw, dpos, ofs, fmask), comp0} : field(rxw, dpos, ofs, fmask);
            hv <= 1'b1;
            if (hv) begin p_data <= hold; p_last <= 1'b0; p_push <= 1'b1; end
          end
        end
        if (csr) begin
          if (hv) begin p_data <= hold; p_last <= 1'b1; p_push <= 1'b1; hv <= 1'b0; end
          if (rbits != 5'd0 || ci) ev_err <= 1'b1;
          ci <= 1'b0;
        end
      end
    end
  end endgenerate
endmodule

`default_nettype wire
