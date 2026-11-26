// grv_dma_bus - the shared bus master of the DMA channels (design document, section 9.7.3). It makes
// one memory access at a time on m_mem_* (PicoRV32 native interface: request held until ready).
// Arbitration when the bus is free or the current access completes: the last channel keeps the bus for
// up to BURST + 1 consecutive accesses while it asks; otherwise round robin, PRIO channels first.
// An address outside [win_lo, win_hi] completes at once with error code 2 (no access); an access not
// answered within TIMEOUT clocks (0: no limit) is dropped with error code 1.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_dma_bus #(
  parameter integer NCH = 1
)(
  input  wire              clk,
  input  wire              rst_n,
  input  wire [NCH-1:0]    rq_valid,
  input  wire [32*NCH-1:0] rq_addr,
  input  wire [32*NCH-1:0] rq_wdata,
  input  wire [4*NCH-1:0]  rq_wstrb,
  input  wire [4*NCH-1:0]  rq_burst,
  input  wire [NCH-1:0]    rq_prio,
  output wire [NCH-1:0]    rq_gnt,
  output wire [NCH-1:0]    rq_done,         // in the clock the access completes
  output wire [31:0]       rq_rdata,
  output wire              rq_err,
  output wire [1:0]        rq_ecode,
  input  wire [31:0]       win_lo,
  input  wire [31:0]       win_hi,
  input  wire [15:0]       timeout,
  output reg               m_mem_valid,
  output reg  [31:0]       m_mem_addr,
  output reg  [31:0]       m_mem_wdata,
  output reg  [3:0]        m_mem_wstrb,
  input  wire              m_mem_ready,
  input  wire [31:0]       m_mem_rdata
);
  localparam integer IW = (NCH > 1) ? $clog2(NCH) : 1;
  reg  [IW-1:0] own, last;
  reg  [3:0]    bc;
  reg  [15:0]   tc;
  wire          fin  = m_mem_valid && m_mem_ready;
  wire          tmo  = m_mem_valid && !m_mem_ready && (timeout != 16'd0) && (tc >= timeout);
  wire          free = !m_mem_valid || fin || tmo;

  // choice
  reg  [IW-1:0] pick;
  reg           any;
  integer i, j;
  always @* begin
    j = 0;
    any = 1'b0;
    pick = last;
    if (rq_valid[last] && bc != 4'd0 && bc <= rq_burst[4 * last +: 4]) begin
      any = 1'b1;
    end else begin
      for (i = NCH; i >= 1; i = i - 1) begin          // lowest distance after 'last' wins
        j = (last + i) % NCH;
        if (rq_valid[j] && rq_prio[j]) begin any = 1'b1; pick = j; end
      end
      if (!any) for (i = NCH; i >= 1; i = i - 1) begin
        j = (last + i) % NCH;
        if (rq_valid[j]) begin any = 1'b1; pick = j; end
      end
    end
  end
  wire          go = free && any && !werr;
  wire [31:0]   ga = rq_addr[32 * pick +: 32];
  wire          inwin = (ga >= win_lo) && (ga <= win_hi);
  wire [NCH-1:0] one = 1;
  assign rq_gnt = go ? (one << pick) : {NCH{1'b0}};

  reg           werr;      // window error to report in the next clock
  reg [IW-1:0]  wown;
  assign rq_done  = ((fin || tmo) ? (one << own) : {NCH{1'b0}}) | (werr ? (one << wown) : {NCH{1'b0}});
  assign rq_rdata = m_mem_rdata;
  assign rq_err   = tmo || werr;
  assign rq_ecode = tmo ? 2'd1 : werr ? 2'd2 : 2'd0;
  always @(posedge clk) begin
    if (!rst_n) begin
      m_mem_valid <= 1'b0; own <= 0; last <= 0; bc <= 4'd0; tc <= 16'd0; werr <= 1'b0;
    end else begin
      if (m_mem_valid) tc <= tc + 1'b1;
      if (fin || tmo) m_mem_valid <= 1'b0;
      werr <= 1'b0;
      if (go) begin
        bc   <= (pick == last && bc != 4'd0) ? bc + 1'b1 : 4'd1;
        last <= pick;
        if (inwin) begin
          m_mem_valid <= 1'b1;
          m_mem_addr  <= ga;
          m_mem_wdata <= rq_wdata[32 * pick +: 32];
          m_mem_wstrb <= rq_wstrb[4 * pick +: 4];
          own <= pick;
          tc  <= 16'd0;
        end else begin
          werr <= 1'b1;
          wown <= pick;
        end
      end
    end
  end
endmodule

`default_nettype wire
