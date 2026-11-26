// grv_ep_src - AXI4-Lite source endpoint: CPU writes become a stream (design document 8.6).
//   0x00 DATA W     push one sample, or 2 (W <= 16) / 4 (W <= 8) packed samples with CTRL.PACK
//   0x04 DATA_HI W  bits [W-1:32] of the next sample (W > 32)
//   0x08 STATUS     [15:0] LEVEL [16] EMPTY [17] FULL [18] OVF [20] TIMEOUT [24] IRQ (W1C 18, 20)
//   0x0C CTRL       [0] EN [1] FLUSH (W1) [2] WAIT [3] PACK [4] IRQ_EN [9:8] MODE (0 STREAM, 1 LOOP)
//   0x10 THRESH     interrupt while LEVEL <= THRESH
//   0x14 FRAME      tlast every FRAME samples (0: never)
//   0x18 COUNT      samples sent
//   0x1C INFO       [5:0] component width [6] complex [7] signed [13:8] fraction [19:16] log2 DEPTH [20] DATA_HI
//   0x20 FREE       DEPTH - LEVEL
//   0x40 .. 0x7C    aliases of DATA
// LOOP mode replays the samples in the buffer without consuming them.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_ep_src #(
  parameter integer W      = 32,
  parameter integer CW     = 16,
  parameter integer NC     = 2,
  parameter integer SIGNED = 1,
  parameter integer FRAC   = 15,
  parameter integer DEPTH  = 512,
  parameter integer FRAME0 = 0
)(
  input  wire         clk,
  input  wire         rst_n,
  input  wire         run,
  // register bus
  input  wire [15:0]  rb_addr,
  input  wire [31:0]  rb_wdata,
  input  wire         rb_we,
  input  wire         rb_re,
  input  wire         rb_force,
  input  wire         rb_sel,
  output wire         t_wrdy,
  output wire         t_rrdy,
  output reg  [31:0]  t_rdata,
  output wire         irq,
  // stream
  output wire [W-1:0] m_tdata,
  output wire         m_tvalid,
  input  wire         m_tready,
  output wire         m_tlast
);
  localparam integer AW = $clog2(DEPTH);
  localparam integer PK = (W <= 8) ? 4 : (W <= 16) ? 2 : 1;
  localparam integer SWP = (PK == 4) ? 8 : 16;

  reg [W-1:0]  mem [0:DEPTH-1];
  reg [AW:0]   wp, rp;
  reg [AW:0]   lp;                       // loop pointer (LOOP mode)
  reg [31:0]   ctrl, thresh, frame, count;
  reg          f_ovf, f_tmo;
  reg [31:0]   hi;
  reg [63:0]   ub;                       // unpacker
  reg [2:0]    uc;
  reg [W-1:0]  od;
  reg          ov, ol;
  reg [31:0]   fc;
  wire [AW:0]  cnt  = wp - rp;
  wire [AW:0]  free = DEPTH - cnt;
  wire         en   = ctrl[0];
  wire         pack = ctrl[3] && (PK > 1);
  wire         loop = (ctrl[9:8] == 2'd1);
  wire [2:0]   npush = pack ? PK : 1;
  wire [31:0]  level = cnt + (loop ? 0 : ov);
  wire [7:0]   ra = rb_addr[7:0];
  wire [63:0]  wfull = {hi, rb_wdata};
  wire [63:0]  wsample = (W >= 64) ? wfull : (wfull & ((64'd1 << W) - 1));
  wire         is_data = (ra == 8'h00) || (ra >= 8'h40 && ra <= 8'h7C);
  wire         w = rb_sel && rb_we;
  wire         wdat = w && is_data;
  // a DATA write waits while the unpacker is busy, and with WAIT while there is no room
  assign t_wrdy = !is_data || ((uc == 0) && (!ctrl[2] || free >= npush));
  assign t_rrdy = 1'b1;
  assign irq    = ctrl[4] && (level <= thresh);

  // unpacker -> memory
  wire push = (uc != 0) && (cnt != DEPTH);
  always @(posedge clk) if (push) mem[wp[AW-1:0]] <= ub[W-1:0];

  // output register (first-word fall-through)
  wire         o_take = m_tvalid && m_tready;
  wire         can_ld = en && run && (!ov || o_take);
  wire         ld_s   = can_ld && !loop && (cnt != 0);
  wire         ld_l   = can_ld && loop && (cnt != 0);
  wire [AW:0]  lpa    = (lp == wp || lp - rp >= cnt) ? rp : lp;
  always @(posedge clk) begin
    if (ld_s) od <= mem[rp[AW-1:0]];
    if (ld_l) od <= mem[lpa[AW-1:0]];
  end
  assign m_tdata  = od;
  assign m_tvalid = ov;
  assign m_tlast  = ol;

  always @(posedge clk) begin
    if (!rst_n) begin
      wp <= 0; rp <= 0; lp <= 0; ctrl <= 32'd0; thresh <= 32'd0; frame <= FRAME0; count <= 32'd0;
      f_ovf <= 1'b0; f_tmo <= 1'b0; uc <= 0; ov <= 1'b0; ol <= 1'b0; fc <= 32'd0; hi <= 32'd0;
    end else begin
      // unpacker
      if (push) begin
        wp <= wp + 1'b1;
        ub <= ub >> (pack ? SWP : W);
        uc <= uc - 1'b1;
      end else if (uc != 0) begin
        uc <= 0;                                   // no room: drop the rest
        f_ovf <= 1'b1;
      end
      // output
      if (ld_s || ld_l) begin
        ov <= 1'b1;
        ol <= (frame != 0) && (fc == frame - 1);
        fc <= (frame != 0 && fc == frame - 1) ? 32'd0 : fc + 1'b1;
        if (ld_s) rp <= rp + 1'b1;
        if (ld_l) lp <= lpa + 1'b1;
      end else if (o_take) begin
        ov <= 1'b0;
      end
      if (o_take) count <= count + 1'b1;
      // register writes
      if (wdat) begin
        if (rb_force && ctrl[2] && free < npush) f_tmo <= 1'b1;
        else if (free < npush) f_ovf <= 1'b1;
        else begin
          ub <= pack ? {32'd0, rb_wdata} : wsample;
          uc <= npush;
        end
      end
      if (w) case (ra)
        8'h04: hi <= rb_wdata;
        8'h08: begin
          if (rb_wdata[18]) f_ovf <= 1'b0;
          if (rb_wdata[20]) f_tmo <= 1'b0;
        end
        8'h0C: begin
          ctrl <= rb_wdata & 32'h0000_031D;
          if (rb_wdata[1]) begin rp <= wp; lp <= wp; ov <= 1'b0; fc <= 32'd0; end
        end
        8'h10: thresh <= rb_wdata;
        8'h14: begin frame <= rb_wdata; fc <= 32'd0; end
        default: ;
      endcase
    end
  end

  wire [31:0] info = {11'd0, (W > 32), AW[3:0], 2'd0, FRAC[5:0], SIGNED[0], (NC == 2), CW[5:0]};
  always @(posedge clk) if (rb_sel && rb_re) case (ra)
    8'h08: t_rdata <= {7'd0, irq, 3'd0, f_tmo, 1'b0, f_ovf, (cnt == DEPTH), (level == 0), level[15:0]};
    8'h0C: t_rdata <= ctrl;
    8'h10: t_rdata <= thresh;
    8'h14: t_rdata <= frame;
    8'h18: t_rdata <= count;
    8'h1C: t_rdata <= info;
    8'h20: t_rdata <= {{(31-AW){1'b0}}, free};
    default: t_rdata <= 32'd0;
  endcase
endmodule

`default_nettype wire
