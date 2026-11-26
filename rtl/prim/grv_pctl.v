// grv_pctl - control of an L-stage pipeline with one enable: valid bits per stage,
//   ce = !v[L] || out_ready ;  v[k] <= ce ? v[k-1] : v[k] ;  v[0] = in_valid
// The datapath registers of the block are clocked with ce.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_pctl #(
  parameter integer L = 1
)(
  input  wire       clk,
  input  wire       rst_n,
  input  wire       in_valid,
  input  wire       out_ready,
  output wire       ce,
  output wire       out_valid,
  output wire [L:1] v
);
  reg [L:1] vr;
  assign ce        = !vr[L] || out_ready;
  assign out_valid = vr[L];
  assign v         = vr;

  generate
    if (L == 1) begin : g_one
      always @(posedge clk)
        if (!rst_n)  vr <= 1'b0;
        else if (ce) vr <= in_valid;
    end else begin : g_many
      always @(posedge clk)
        if (!rst_n)  vr <= {L{1'b0}};
        else if (ce) vr <= {vr[L-1:1], in_valid};
    end
  endgenerate
endmodule

`default_nettype wire
