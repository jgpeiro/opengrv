// grv_mem_arb - shares a PicoRV32 native memory bus between the CPU and the DMA memory port of a
// generated top level (design document, figure 57 a). The owner changes only between accesses. The CPU
// has priority; a DMA request that has waited MAXWAIT clocks is served next, so the DMA cannot starve.
// The masters see the slave's ready and read data only while they own the bus.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_mem_arb #(
  parameter integer MAXWAIT = 16
)(
  input  wire        clk,
  input  wire        rst_n,
  // CPU
  input  wire        c_valid,
  input  wire [31:0] c_addr,
  input  wire [31:0] c_wdata,
  input  wire [3:0]  c_wstrb,
  output wire        c_ready,
  output wire [31:0] c_rdata,
  // DMA
  input  wire        d_valid,
  input  wire [31:0] d_addr,
  input  wire [31:0] d_wdata,
  input  wire [3:0]  d_wstrb,
  output wire        d_ready,
  output wire [31:0] d_rdata,
  // memory bus of the SoC
  output wire        m_valid,
  output wire [31:0] m_addr,
  output wire [31:0] m_wdata,
  output wire [3:0]  m_wstrb,
  input  wire        m_ready,
  input  wire [31:0] m_rdata
);
  localparam NONE = 2'd0, CPU = 2'd1, DMA = 2'd2;
  reg  [1:0]  own;
  reg  [15:0] wcnt;
  wire        dma_first = (wcnt >= MAXWAIT);
  wire [1:0]  cur = (own != NONE) ? own :
                    (d_valid && dma_first) ? DMA :
                    c_valid ? CPU : d_valid ? DMA : NONE;
  assign m_valid = (cur == CPU) ? c_valid : (cur == DMA) ? d_valid : 1'b0;
  assign m_addr  = (cur == DMA) ? d_addr  : c_addr;
  assign m_wdata = (cur == DMA) ? d_wdata : c_wdata;
  assign m_wstrb = (cur == DMA) ? d_wstrb : c_wstrb;
  assign c_ready = (cur == CPU) && m_ready;
  assign d_ready = (cur == DMA) && m_ready;
  assign c_rdata = m_rdata;
  assign d_rdata = m_rdata;
  always @(posedge clk) begin
    if (!rst_n) begin
      own <= NONE; wcnt <= 16'd0;
    end else begin
      if (m_valid && m_ready) own <= NONE;
      else if (m_valid) own <= cur;
      if (d_valid && cur != DMA) begin if (wcnt != 16'hFFFF) wcnt <= wcnt + 1'b1; end
      else wcnt <= 16'd0;
    end
  end
endmodule

`default_nettype wire
