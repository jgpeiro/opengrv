// grv_probes - blocks_probe_signal_x, qtgui_number_sink: NP probes holding the latest sample of
// their stream (always ready). Probe k: word 0 at 0x3000 + 8k (bits [31:0], reading it latches
// the high word), word 1 at 0x3004 + 8k (bits [63:32]). Inputs are 64 bits, sign-extended by the
// top level.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_probes #(
  parameter integer NP = 1
)(
  input  wire           clk,
  input  wire           rst_n,
  input  wire [15:0]    rb_addr,
  input  wire           rb_re,
  input  wire           rb_sel,
  output wire           t_wrdy,
  output wire           t_rrdy,
  output reg  [31:0]    t_rdata,
  input  wire [64*NP-1:0] s_tdata,
  input  wire [NP-1:0]  s_tvalid,
  output wire [NP-1:0]  s_tready
);
  wire [63:0] val [0:NP-1];
  reg [31:0] hi;
  assign s_tready = {NP{1'b1}};
  assign t_wrdy = 1'b1;
  assign t_rrdy = 1'b1;
  genvar k;
  generate
    for (k = 0; k < NP; k = k + 1) begin : g_p
      reg [63:0] v;
      always @(posedge clk)
        if (!rst_n) v <= 64'd0;
        else if (s_tvalid[k]) v <= s_tdata[64*k +: 64];
      assign val[k] = v;
    end
  endgenerate
  wire [11:0] idx = rb_addr[11:3];
  always @(posedge clk) if (rb_sel && rb_re) begin
    if (idx >= NP) t_rdata <= 32'd0;
    else if (!rb_addr[2]) begin t_rdata <= val[idx][31:0]; hi <= val[idx][63:32]; end
    else t_rdata <= hi;
  end
endmodule

`default_nettype wire
