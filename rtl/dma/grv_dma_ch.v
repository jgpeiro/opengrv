// grv_dma_ch - one DMA channel (design document, section 9.7): MM2S (DIR = 0, memory to the graph)
// or S2MM (DIR = 1, the graph to memory). Samples are stored as elements of NC containers of CB bytes,
// packed little-endian into 32-bit words (an 8-byte element takes two words, I first). Modes: SINGLE,
// RING (with FLOW / SW_IDX and watermark interrupts), DESC (linked descriptors with OWN bit).
// The channel asks grv_dma_bus for one memory access at a time (rq_*); S2MM data writes are pipelined
// (the next word is presented as soon as the previous one is granted).
//   0x00 CTRL    [0] EN [1] ABORT (W1) [3:2] MODE [4] I_DONE [5] I_WM [6] I_ERR [7] FLOW [8] DROP [9] MSBA
//                [10] EOFL [15:12] BURST-1 [23:16] GAP [24] PRIO
//   0x04 STATUS  [0] BUSY [1] DONE [2] WM [3] ERR [4] STALLED [5] OVF [7:6] ERR_CODE [8] IRQ [31:16] FIFO
//   0x08 ADDR  0x0C LEN  0x10 HW_IDX  0x14 SW_IDX  0x18 WM  0x1C DESC  0x20 TOTAL  0x24 FRAME
//   0x28 ERR_ADDR  0x2C INFO  0x30 KICK
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_dma_ch #(
  parameter integer DIR     = 1,
  parameter integer W       = 32,         // sample width (all components)
  parameter integer CW      = 16,         // component width
  parameter integer NC      = 2,
  parameter integer SIGNED  = 1,
  parameter integer FRAC    = 15,
  parameter integer CB      = 2,          // container bytes per component: 1, 2 or 4
  parameter integer DEPTH   = 32,         // element FIFO
  parameter [31:0]  CTRL0   = 32'd0,
  parameter [31:0]  ADDR0   = 32'd0,
  parameter [31:0]  LEN0    = 32'd0,
  parameter [31:0]  WM0     = 32'd0,
  parameter [31:0]  FRAME0  = 32'd0
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
  output reg  [31:0]  t_rdata,
  output wire         irq,
  // stream: S2MM input / MM2S output
  input  wire [W-1:0] s_tdata,
  input  wire         s_tvalid,
  output wire         s_tready,
  input  wire         s_tlast,
  output wire [W-1:0] m_tdata,
  output wire         m_tvalid,
  input  wire         m_tready,
  output wire         m_tlast,
  // memory requests
  output reg          rq_valid,
  output reg  [31:0]  rq_addr,
  output reg  [31:0]  rq_wdata,
  output reg  [3:0]   rq_wstrb,
  output wire [3:0]   rq_burst,
  output wire         rq_prio,
  input  wire         rq_gnt,
  input  wire         rq_done,
  input  wire [31:0]  rq_rdata,
  input  wire         rq_err,
  input  wire [1:0]   rq_ecode
);
  localparam integer EB    = NC * CB;              // element bytes
  localparam integer EBITS = 8 * EB;
  localparam integer CBITS = 8 * CB;
  localparam integer EPW   = (EB >= 4) ? 1 : 4 / EB; // elements per word
  localparam integer WPE   = (EB == 8) ? 2 : 1;      // words per element
  localparam integer FAW   = $clog2(DEPTH);
  localparam [31:0]  INFO  = {4'd0, (EB == 8) ? 4'd3 : (EB == 4) ? 4'd2 : (EB == 2) ? 4'd1 : 4'd0, FAW[3:0], 3'd0, DIR[0],
                              (CB == 4) ? 2'd2 : (CB == 2) ? 2'd1 : 2'd0, FRAC[5:0], SIGNED[0], (NC == 2), CW[5:0]};
  localparam M_SINGLE = 2'd0, M_RING = 2'd1, M_DESC = 2'd2;

  // ---------------------------------------------------------------- registers
  reg [31:0] ctrl, addr, len, sw_idx, wm, desc, frame, err_addr, total;
  reg [23:0] hw_idx;
  reg        f_done, f_wm, f_err, f_ovf, stalled, kick;
  reg [1:0]  ecode;
  wire       en_bit = ctrl[0];
  wire [1:0] mode = ctrl[3:2];
  wire       flow = ctrl[7], drop = ctrl[8], msba = ctrl[9], eofl = ctrl[10];
  wire [7:0] gap  = ctrl[23:16];
  assign rq_burst = ctrl[15:12];
  assign rq_prio  = ctrl[24];
  assign t_wrdy = 1'b1;
  assign t_rrdy = 1'b1;
  wire cond = (ctrl[4] && f_done) || (ctrl[5] && f_wm) || (ctrl[6] && f_err);
  assign irq = cond;
  wire w = rb_sel && rb_we;
  wire [7:0] ra = rb_addr[7:0];

  // ---------------------------------------------------------------- element FIFO
  reg              act;                  // the channel is transferring
  reg              start, fl;
  wire [EBITS:0]   e_in, e_out;
  wire             e_in_v, e_in_r, e_out_v;
  reg              e_out_r;
  wire             e_pop;
  wire [EBITS+63:0] e_x = {64'd0, e_out[EBITS-1:0]};
  wire [15:0]      e_level;
  grv_fifo_fl #(.W(EBITS + 1), .DEPTH(DEPTH)) u_fifo (.clk(clk), .rst_n(rst_n), .flush(fl),
    .s_data(e_in), .s_valid(e_in_v), .s_ready(e_in_r), .m_data(e_out), .m_valid(e_out_v), .m_ready(e_pop),
    .level(e_level));

  // sample <-> element
  function [EBITS-1:0] to_elem(input [W-1:0] s, input m);
    integer c, b;
    reg [CBITS-1:0] v;
    begin
      to_elem = {EBITS{1'b0}};
      for (c = 0; c < NC; c = c + 1) begin
        for (b = 0; b < CBITS; b = b + 1) begin
          if (m) v[b] = (b >= CBITS - CW) ? s[c * CW + b - (CBITS - CW)] : 1'b0;
          else   v[b] = (b < CW) ? s[c * CW + b] : (SIGNED != 0 ? s[c * CW + CW - 1] : 1'b0);
        end
        to_elem[c * CBITS +: CBITS] = v;
      end
    end
  endfunction
  function [W-1:0] from_elem(input [EBITS-1:0] e, input m);
    integer c;
    begin
      for (c = 0; c < NC; c = c + 1)
        from_elem[c * CW +: CW] = m ? e[c * CBITS + CBITS - CW +: CW] : e[c * CBITS +: CW];
    end
  endfunction

  // ---------------------------------------------------------------- block state
  reg [31:0] base;        // block address
  reg [23:0] blen;        // block length in samples
  reg [23:0] ridx;        // next sample to request (word side)
  reg [23:0] widx;        // word index of the next access in the block
  reg [23:0] didx;        // samples done (= HW_IDX)
  reg [23:0] wmc;
  reg [31:0] dptr, dnext, dctrl;
  reg        deof, dovf;
  reg [23:0] sacc;        // samples accepted (S2MM SINGLE)
  reg        slast_seen;
  localparam S_IDLE = 4'd0, S_FNEXT = 4'd1, S_FADDR = 4'd2, S_FCTRL = 4'd3, S_STALL = 4'd4, S_XFER = 4'd5,
             S_WSTAT = 4'd6, S_WCTRL = 4'd7, S_END = 4'd8, S_ABORT = 4'd9;
  reg [3:0]  st;
  reg [3:0]  pend;        // kind of the access in flight (0: none)
  reg [3:0]  pk;          // kind of the presented request
  reg [3:0]  pn;          // samples of the presented request
  reg [3:0]  inf_n;       // samples of the access in flight
  reg        inf_last;    // the access in flight ends the block (EOF)
  reg [31:0] inf_addr;
  reg        p_last;
  reg [3:0]  bcnt;        // accesses since the last gap
  reg [7:0]  gcnt;        // gap countdown
  wire       inflight = (pend != 4'd0);
  wire       ring = (mode == M_RING);

  // ring room (samples) for the next request
  wire [24:0] d_room = {1'b0, sw_idx[23:0]} - {1'b0, ridx} - (DIR ? 25'd1 : 25'd0);
  wire [23:0] room   = d_room[24] ? d_room[23:0] + blen : d_room[23:0];
  wire [23:0] remain = blen - ridx;

  // ---------------------------------------------------------------- S2MM word assembly
  reg [31:0] ab;          // assembly buffer
  reg [3:0]  as_;         // strobes
  reg [3:0]  an;          // elements (samples) in the buffer
  reg        ahi;         // EB = 8: the high word is next
  reg [31:0] ahw;         // EB = 8: high word
  reg        aready;      // buffer complete, waiting to be presented
  reg        alast;       // buffer ends the block (EOF)

  // ---------------------------------------------------------------- MM2S unpacking
  reg [31:0] ub;
  wire [95:0] ubx = {64'd0, ub};       // ub padded for the element selects (any element size)
  reg [3:0]  un;          // elements left in ub
  reg        ulo;         // EB = 8: low word received
  reg [31:0] ulw;
  reg        ulast;       // the word ends the block (EOF flag on its last element)
  reg [3:0]  uk;          // element index
  reg        m_push;
  reg [EBITS:0] m_elem;

  // stream side
  wire s_can = act && (DIR == 1) &&
               (mode != M_SINGLE || (sacc < blen && !(eofl && slast_seen)));
  generate if (DIR == 1) begin : g_s2mm_in
    assign e_in     = {s_tlast, to_elem(s_tdata, msba)};
    assign e_in_v   = s_tvalid && s_can && e_in_r;
    assign s_tready = s_can ? (e_in_r || drop) : drop;
    assign m_tdata  = {W{1'b0}};
    assign m_tvalid = 1'b0;
    assign m_tlast  = 1'b0;
    assign e_pop    = e_out_r;
  end else begin : g_mm2s_out
    reg [31:0] fc;
    assign e_in     = m_elem;
    assign e_in_v   = m_push;
    assign s_tready = 1'b0;
    assign m_tdata  = from_elem(e_out[EBITS-1:0], msba);
    assign m_tvalid = e_out_v && en_bit && run;
    assign m_tlast  = e_out[EBITS] || (frame != 32'd0 && fc == frame - 1);
    assign e_pop    = m_tvalid && m_tready;
    always @(posedge clk)
      if (!rst_n || start) fc <= 32'd0;
      else if (m_tvalid && m_tready) fc <= (frame != 32'd0 && fc == frame - 1) ? 32'd0 : fc + 1'b1;
  end endgenerate
  wire s_drop_ovf = (DIR == 1) && s_tvalid && s_can && !e_in_r && drop;

  // ---------------------------------------------------------------- main
  wire abort_now = w && ra == 8'h00 && (rb_wdata[1] || (!rb_wdata[0] && ctrl[0]));
  wire err_now   = rq_done && rq_err;
  wire eofb      = (mode == M_DESC) ? dctrl[25] : eofl;
  reg  ablk;              // S2MM: the block's last word is assembled
  wire asm_ok    = ring || (!ablk && (ridx + {20'd0, an} < blen));
  integer k;
  reg [31:0] wtmp;
  reg [3:0]  stmp;
  always @(posedge clk) begin
    start <= 1'b0;
    fl    <= 1'b0;
    m_push <= 1'b0;
    if (!rst_n) begin
      ctrl <= CTRL0; addr <= ADDR0; len <= LEN0; wm <= WM0; frame <= FRAME0; sw_idx <= 32'd0; desc <= 32'd0;
      err_addr <= 32'd0; total <= 32'd0; hw_idx <= 24'd0;
      f_done <= 1'b0; f_wm <= 1'b0; f_err <= 1'b0; f_ovf <= 1'b0; stalled <= 1'b0; kick <= 1'b0; ecode <= 2'd0;
      act <= 1'b0; st <= S_IDLE; pend <= 4'd0; rq_valid <= 1'b0; an <= 4'd0; as_ <= 4'd0; ahi <= 1'b0;
      aready <= 1'b0; un <= 4'd0; ub <= 32'd0; ulast <= 1'b0; ahw <= 32'd0; ulo <= 1'b0; bcnt <= 4'd0; gcnt <= 8'd0; sacc <= 24'd0; slast_seen <= 1'b0;
      e_out_r <= 1'b0; ablk <= 1'b0;
    end else begin
      e_out_r <= 1'b0;
      if (s_drop_ovf && act) f_ovf <= 1'b1;
      if (e_in_v && DIR == 1) begin
        sacc <= sacc + 1'b1;
        if (s_tlast) slast_seen <= 1'b1;
      end
      if (gcnt != 8'd0) gcnt <= gcnt - 1'b1;

      // ------------------------------------------------ register writes
      if (w) case (ra)
        8'h00: begin
          ctrl <= rb_wdata & 32'h01FF_F7FD;
          if (abort_now) ctrl[0] <= 1'b0;
          else if (rb_wdata[0] && !ctrl[0]) start <= 1'b1;
        end
        8'h04: begin
          if (rb_wdata[1]) f_done <= 1'b0;
          if (rb_wdata[2]) f_wm <= 1'b0;
          if (rb_wdata[3]) begin f_err <= 1'b0; ecode <= 2'd0; end
          if (rb_wdata[5]) f_ovf <= 1'b0;
        end
        8'h08: addr <= rb_wdata;
        8'h0C: len <= rb_wdata & 32'h00FF_FFFF;
        8'h14: sw_idx <= rb_wdata & 32'h00FF_FFFF;
        8'h18: wm <= rb_wdata & 32'h00FF_FFFF;
        8'h1C: desc <= rb_wdata;
        8'h24: frame <= rb_wdata & 32'h00FF_FFFF;
        8'h30: kick <= 1'b1;
        default: ;
      endcase
      // a channel enabled by its reset value starts on its own
      if (st == S_IDLE && !act && en_bit && !start && !(w && ra == 8'h00) && pend == 4'd0 && !f_err && !f_done)
        start <= (CTRL0[0] != 1'b0) && (total == 32'd0);

      // ------------------------------------------------ grant / completion
      if (rq_gnt) begin
        rq_valid <= 1'b0;
        pend <= pk;
        inf_n <= pn;
        inf_last <= p_last;
        inf_addr <= rq_addr;
        bcnt <= bcnt + 1'b1;
        if (bcnt == rq_burst) begin bcnt <= 4'd0; gcnt <= gap; end
      end
      if (rq_done) begin
        pend <= (rq_gnt) ? pk : 4'd0;
        if (rq_err) begin
          f_err <= 1'b1; ecode <= rq_ecode; err_addr <= inf_addr;
        end else case (pend)
          4'd1: begin                      // data
            hw_idx <= (ring && didx + inf_n >= blen) ? didx + inf_n - blen : didx + inf_n;
            didx   <= (ring && didx + inf_n >= blen) ? didx + inf_n - blen : didx + inf_n;
            total  <= total + inf_n;
            if (wm[23:0] != 24'd0) begin
              if (wmc + inf_n >= wm[23:0]) begin wmc <= wmc + inf_n - wm[23:0]; f_wm <= 1'b1; end
              else wmc <= wmc + inf_n;
            end
            if (DIR == 0) begin            // read data -> unpacker
              if (WPE == 2 && !ulo) begin ulw <= rq_rdata; ulo <= 1'b1; end
              else begin ub <= rq_rdata; un <= inf_n; uk <= 4'd0; ulast <= inf_last; ulo <= 1'b0; end
            end
            if (inf_last) deof <= 1'b1;
          end
          4'd2: dnext <= rq_rdata;
          4'd3: begin base <= rq_rdata; end
          4'd4: dctrl <= rq_rdata;
          default: ;
        endcase
      end

      // ------------------------------------------------ MM2S unpacker -> FIFO
      if (DIR == 0 && un != 4'd0) begin
        if (WPE == 2) m_elem <= {ulast, ub, ulw};
        else m_elem <= {ulast && un == 4'd1, ubx[EBITS * uk +: EBITS]};
        m_push <= 1'b1;
        un <= un - 1'b1;
        uk <= uk + 1'b1;
      end

      // ------------------------------------------------ S2MM assembly from the FIFO
      if (DIR == 1 && act && st == S_XFER && !aready && e_out_v && !e_out_r && asm_ok) begin
        e_out_r <= 1'b1;
        if (WPE == 2) begin
          ab <= e_x[31:0]; ahw <= e_x[63:32]; as_ <= 4'hF; an <= 4'd1; ahi <= 1'b0;
          aready <= 1'b1; alast <= (eofl && !ring && e_out[EBITS]) || (!ring && ridx + 1 == blen);
          if (!ring && (eofl && e_out[EBITS] || ridx + 1 == blen)) ablk <= 1'b1;
        end else begin
          wtmp = ab; stmp = as_;
          for (k = 0; k < 4; k = k + 1)
            if (k / EB == an) begin wtmp[8 * k +: 8] = e_out[8 * (k % EB) +: 8]; stmp[k] = 1'b1; end
          ab <= wtmp; as_ <= stmp; an <= an + 1'b1;
          if (an + 1 == EPW || (eofl && !ring && e_out[EBITS]) || (!ring && ridx + an + 1 == blen)) begin
            aready <= 1'b1;
            alast <= (eofl && !ring && e_out[EBITS]) || (!ring && ridx + an + 1 == blen);
            if (!ring && ((eofl && e_out[EBITS]) || ridx + an + 1 == blen)) ablk <= 1'b1;
          end
        end
      end

      // ------------------------------------------------ state machine
      case (st)
        S_IDLE: begin
          stalled <= 1'b0;
          if (start) begin
            act <= 1'b1; total <= 32'd0; didx <= 24'd0; hw_idx <= 24'd0; ridx <= 24'd0; widx <= 24'd0; wmc <= 24'd0;
            sacc <= 24'd0; slast_seen <= 1'b0; deof <= 1'b0; dovf <= 1'b0; f_done <= 1'b0; ablk <= 1'b0;
            an <= 4'd0; as_ <= 4'd0; aready <= 1'b0; un <= 4'd0; ulo <= 1'b0; bcnt <= 4'd0; kick <= 1'b0;
            if (DIR == 0 || drop) fl <= 1'b1;
            if (mode == M_DESC) begin
              dptr <= desc; st <= S_FNEXT;
              if (desc[3:0] != 4'd0) begin f_err <= 1'b1; ecode <= 2'd3; act <= 1'b0; ctrl[0] <= 1'b0; st <= S_IDLE; end
            end else begin
              base <= addr; blen <= len[23:0]; st <= S_XFER;
              if (len[23:0] == 24'd0 || addr[1:0] != 2'd0) begin
                f_err <= 1'b1; ecode <= 2'd3; act <= 1'b0; ctrl[0] <= 1'b0; st <= S_IDLE;
              end
            end
          end
        end
        S_FNEXT, S_FADDR, S_FCTRL: begin
          if (!rq_valid && !inflight && !rq_done) begin
            rq_valid <= 1'b1; rq_wstrb <= 4'd0;
            rq_addr <= dptr + ((st == S_FNEXT) ? 32'd0 : (st == S_FADDR) ? 32'd4 : 32'd8);
            pk <= (st == S_FNEXT) ? 4'd2 : (st == S_FADDR) ? 4'd3 : 4'd4; pn <= 4'd0; p_last <= 1'b0;
          end
          if (rq_done && !rq_err) begin
            if (st == S_FNEXT) st <= S_FADDR;
            else if (st == S_FADDR) st <= S_FCTRL;
            else begin
              // CTRL word read
              if (!rq_rdata[31]) begin st <= S_STALL; stalled <= 1'b1; kick <= 1'b0; end
              else if (rq_rdata[23:0] == 24'd0 || base[1:0] != 2'd0 || dnext[3:0] != 4'd0) begin
                f_err <= 1'b1; ecode <= 2'd3; act <= 1'b0; ctrl[0] <= 1'b0; st <= S_IDLE;
              end else begin
                blen <= rq_rdata[23:0]; ridx <= 24'd0; widx <= 24'd0; didx <= 24'd0; hw_idx <= 24'd0;
                deof <= 1'b0; dovf <= f_ovf; sacc <= 24'd0; slast_seen <= 1'b0; st <= S_XFER; ablk <= 1'b0;
              end
            end
          end
        end
        S_STALL: begin
          if (kick) begin kick <= 1'b0; stalled <= 1'b0; st <= S_FCTRL; end
        end
        S_XFER: begin
          stalled <= 1'b0;
          // block complete?
          if (!inflight && !rq_valid && !rq_done && !aready && un == 4'd0 && !m_push &&
              ((!ring && didx == blen) || (deof && didx == ridx))) begin
            if (mode == M_DESC) st <= S_WSTAT;
            else begin st <= S_END; end
          end else if ((!rq_valid || rq_gnt) && gcnt == 8'd0 && !(rq_gnt && bcnt == rq_burst && gap != 8'd0)) begin
            if (DIR == 1) begin
              if (aready && (!ring || !flow || room >= {20'd0, an})) begin
                rq_valid <= 1'b1;
                rq_addr  <= base + {widx[21:0], 2'b00};
                rq_wdata <= ahi ? ahw : ab;
                rq_wstrb <= as_;
                pk <= 4'd1;
                if (WPE == 2 && !ahi) begin
                  pn <= 4'd0; p_last <= 1'b0; ahi <= 1'b1;
                  widx <= widx + 1'b1;
                end else begin
                  pn <= an; p_last <= alast;
                  aready <= 1'b0; an <= 4'd0; as_ <= 4'd0; ab <= 32'd0; ahi <= 1'b0;
                  if (ring && ridx + an >= blen) begin ridx <= ridx + an - blen; widx <= 24'd0; end
                  else begin ridx <= ridx + an; widx <= widx + 1'b1; end
                end
                stalled <= 1'b0;
              end else if (aready) stalled <= 1'b1;
            end else begin
              // MM2S: one read at a time, when the unpacker and the FIFO have room
              if (!inflight && !rq_valid && !rq_done && un == 4'd0 && !m_push && (ring || ridx != blen) &&
                  ({16'd0, e_level} + EPW + 2 <= DEPTH) &&
                  (!ring || !flow || room >= ((EPW < blen) ? EPW : blen))) begin
                rq_valid <= 1'b1; rq_wstrb <= 4'd0; pk <= 4'd1;
                rq_addr  <= base + {widx[21:0], 2'b00};
                if (WPE == 2 && !ulo && !ahi) begin
                  pn <= 4'd0; p_last <= 1'b0; ahi <= 1'b1; widx <= widx + 1'b1;
                end else begin
                  ahi <= 1'b0;
                  pn <= (!ring && remain < EPW) ? remain[3:0] : EPW[3:0];
                  p_last <= !ring && eofb && (remain <= EPW);
                  if (ring && ridx + EPW >= blen) begin ridx <= ridx + EPW - blen; widx <= 24'd0; end
                  else begin
                    ridx <= ridx + ((!ring && remain < EPW) ? remain : EPW);
                    widx <= widx + 1'b1;
                  end
                end
                stalled <= 1'b0;
              end else if (ring && flow && room < EPW) stalled <= 1'b1;
            end
          end
        end
        S_WSTAT, S_WCTRL: begin
          if (!rq_valid && !inflight && !rq_done) begin
            rq_valid <= 1'b1; rq_wstrb <= 4'hF; pk <= (st == S_WSTAT) ? 4'd5 : 4'd6; pn <= 4'd0; p_last <= 1'b0;
            rq_addr  <= dptr + ((st == S_WSTAT) ? 32'd12 : 32'd8);
            rq_wdata <= (st == S_WSTAT) ? {1'b1, 5'd0, f_ovf && !dovf, deof_seen(didx, blen), didx}
                                        : (dctrl & 32'h7FFF_FFFF);
          end
          if (rq_done && !rq_err) begin
            if (st == S_WSTAT) st <= S_WCTRL;
            else begin
              if (dctrl[24]) f_done <= 1'b1;
              if (dnext == 32'd0) begin st <= S_END; end
              else begin dptr <= dnext; st <= S_FNEXT; end
            end
          end
        end
        S_END: begin                         // MM2S: done when the last sample has left the FIFO
          if (DIR == 1 || !e_out_v) begin
            f_done <= 1'b1; act <= 1'b0; ctrl[0] <= 1'b0; st <= S_IDLE;
          end
          if (mode == M_SINGLE) hw_idx <= didx;
        end
        default: begin                       // S_ABORT: wait for the access in flight
          rq_valid <= 1'b0;
          if (!inflight || rq_done) begin
            st <= S_IDLE; pend <= 4'd0; fl <= 1'b1; aready <= 1'b0; an <= 4'd0; un <= 4'd0; ulo <= 1'b0;
          end
        end
      endcase
      if (err_now) begin
        act <= 1'b0; ctrl[0] <= 1'b0; st <= S_ABORT; rq_valid <= 1'b0;
      end
      if (abort_now) begin
        act <= 1'b0; rq_valid <= 1'b0;
        if (act || st != S_IDLE) st <= S_ABORT;
      end
    end
  end
  function deof_seen(input [23:0] a, input [23:0] b);
    deof_seen = (a != b);
  endfunction

  always @(posedge clk) if (rb_sel && rb_re) case (ra)
    8'h00: t_rdata <= ctrl;
    8'h04: t_rdata <= {e_level, 7'd0, cond, ecode, f_ovf, stalled, f_err, f_wm, f_done, act};
    8'h08: t_rdata <= addr;
    8'h0C: t_rdata <= len;
    8'h10: t_rdata <= {8'd0, hw_idx};
    8'h14: t_rdata <= sw_idx;
    8'h18: t_rdata <= wm;
    8'h1C: t_rdata <= (st == S_IDLE) ? desc : dptr;
    8'h20: t_rdata <= total;
    8'h24: t_rdata <= frame;
    8'h28: t_rdata <= err_addr;
    8'h2C: t_rdata <= INFO;
    default: t_rdata <= 32'd0;
  endcase
endmodule

`default_nettype wire
