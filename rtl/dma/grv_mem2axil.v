// grv_mem2axil - turns the DMA memory port (PicoRV32 native interface) into an AXI4-Lite master
// (design document, figure 57 c). One transaction at a time; a write sends AW and W together.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_mem2axil (
  input  wire        clk,
  input  wire        rst_n,
  input  wire        mem_valid,
  input  wire [31:0] mem_addr,
  input  wire [31:0] mem_wdata,
  input  wire [3:0]  mem_wstrb,
  output reg         mem_ready,
  output reg  [31:0] mem_rdata,
  output reg  [31:0] m_axil_awaddr,
  output reg         m_axil_awvalid,
  input  wire        m_axil_awready,
  output reg  [31:0] m_axil_wdata,
  output reg  [3:0]  m_axil_wstrb,
  output reg         m_axil_wvalid,
  input  wire        m_axil_wready,
  input  wire [1:0]  m_axil_bresp,
  input  wire        m_axil_bvalid,
  output wire        m_axil_bready,
  output reg  [31:0] m_axil_araddr,
  output reg         m_axil_arvalid,
  input  wire        m_axil_arready,
  input  wire [31:0] m_axil_rdata,
  input  wire [1:0]  m_axil_rresp,
  input  wire        m_axil_rvalid,
  output wire        m_axil_rready
);
  reg busy;
  assign m_axil_bready = 1'b1;
  assign m_axil_rready = 1'b1;
  always @(posedge clk) begin
    mem_ready <= 1'b0;
    if (!rst_n) begin
      busy <= 1'b0; m_axil_awvalid <= 1'b0; m_axil_wvalid <= 1'b0; m_axil_arvalid <= 1'b0;
    end else begin
      if (mem_valid && !busy && !mem_ready) begin
        busy <= 1'b1;
        if (mem_wstrb != 4'd0) begin
          m_axil_awaddr <= mem_addr; m_axil_awvalid <= 1'b1;
          m_axil_wdata <= mem_wdata; m_axil_wstrb <= mem_wstrb; m_axil_wvalid <= 1'b1;
        end else begin
          m_axil_araddr <= mem_addr; m_axil_arvalid <= 1'b1;
        end
      end
      if (m_axil_awvalid && m_axil_awready) m_axil_awvalid <= 1'b0;
      if (m_axil_wvalid && m_axil_wready) m_axil_wvalid <= 1'b0;
      if (m_axil_arvalid && m_axil_arready) m_axil_arvalid <= 1'b0;
      if (busy && m_axil_bvalid) begin busy <= 1'b0; mem_ready <= 1'b1; end
      if (busy && m_axil_rvalid) begin busy <= 1'b0; mem_ready <= 1'b1; mem_rdata <= m_axil_rdata; end
    end
  end
endmodule

`default_nettype wire
