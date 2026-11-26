// grv_oreg - output stage of a block: a grv_skid register slice when OREG = 1, wires when 0.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_oreg #(
  parameter integer W    = 16,
  parameter integer OREG = 1
)(
  input  wire         clk,
  input  wire         rst_n,
  input  wire [W-1:0] s_tdata,
  input  wire         s_tvalid,
  output wire         s_tready,
  input  wire         s_tlast,
  output wire [W-1:0] m_tdata,
  output wire         m_tvalid,
  input  wire         m_tready,
  output wire         m_tlast
);
  generate
    if (OREG != 0) begin : g_skid
      grv_skid #(.W(W)) u_skid (.clk(clk), .rst_n(rst_n), .s_tdata(s_tdata), .s_tvalid(s_tvalid),
        .s_tready(s_tready), .s_tlast(s_tlast), .m_tdata(m_tdata), .m_tvalid(m_tvalid),
        .m_tready(m_tready), .m_tlast(m_tlast));
    end else begin : g_wire
      assign m_tdata  = s_tdata;
      assign m_tvalid = s_tvalid;
      assign s_tready = m_tready;
      assign m_tlast  = s_tlast;
    end
  endgenerate
endmodule

`default_nettype wire
