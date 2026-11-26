// grv_demux - blocks_deinterleave (MODE 0: BS samples to output 0, BS to output 1, ...) and
// blocks_selector (MODE 1: all NI inputs joined, input cfg_in goes to output cfg_out while cfg_en,
// the other inputs are drained). One output register shared by all outputs.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_demux #(
  parameter integer MODE = 0,
  parameter integer NI   = 1,
  parameter integer NO   = 2,
  parameter integer W    = 16,
  parameter integer BS   = 1
)(
  input  wire            clk,
  input  wire            rst_n,
  input  wire [NI*W-1:0] s_tdata,
  input  wire [NI-1:0]   s_tvalid,
  output wire [NI-1:0]   s_tready,
  input  wire [NI-1:0]   s_tlast,
  input  wire [7:0]      cfg_in,
  input  wire [7:0]      cfg_out,
  input  wire            cfg_en,
  output wire [NO*W-1:0] m_tdata,
  output wire [NO-1:0]   m_tvalid,
  input  wire [NO-1:0]   m_tready,
  output wire [NO-1:0]   m_tlast
);
  localparam integer PW = (NO > 1) ? $clog2(NO) : 1;
  reg  [PW-1:0] port, op;
  reg  [31:0]   cnt;
  reg  [W-1:0]  od;
  reg           ol, ov;
  wire all_v = &s_tvalid;
  wire o_free = !ov || m_tready[op];
  wire sel_ok = (MODE == 0) ? 1'b1 : (cfg_en && cfg_out < NO && cfg_in < NI);
  assign s_tready = {NI{all_v && (o_free || !sel_ok)}};
  wire take = all_v && s_tready[0];
  wire [W-1:0] din = (MODE == 0) ? s_tdata[0 +: W] : s_tdata[W*cfg_in +: W];
  wire         lin = (MODE == 0) ? s_tlast[0] : s_tlast[cfg_in];
  always @(posedge clk) begin
    if (!rst_n) begin
      ov <= 1'b0; port <= 0; cnt <= 32'd0;
    end else begin
      if (ov && m_tready[op]) ov <= 1'b0;
      if (take && sel_ok) begin
        ov <= 1'b1;
        op <= (MODE == 0) ? port : cfg_out[PW-1:0];
        od <= din;
        ol <= lin;
      end
      if (take && MODE == 0) begin
        if (cnt == BS - 1) begin cnt <= 32'd0; port <= (port == NO - 1) ? {PW{1'b0}} : port + 1'b1; end
        else cnt <= cnt + 1'b1;
      end
    end
  end
  assign m_tdata  = {NO{od}};
  wire [NO-1:0] one = 1;
  assign m_tvalid = ov ? (one << op) : {NO{1'b0}};
  assign m_tlast  = {NO{ol}};
endmodule

`default_nettype wire
