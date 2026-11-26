// grv_fork - eager fork of one stream to N branches.
//   m_tvalid[i] = s_tvalid && !done[i] ;  s_tready = &(done | m_tready)
//   done[i] <= transfer in ? 0 : done[i] | (m_tvalid[i] && m_tready[i])
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_fork #(
  parameter integer W = 16,
  parameter integer N = 2
)(
  input  wire           clk,
  input  wire           rst_n,
  input  wire [W-1:0]   s_tdata,
  input  wire           s_tvalid,
  output wire           s_tready,
  input  wire           s_tlast,
  output wire [N*W-1:0] m_tdata,
  output wire [N-1:0]   m_tvalid,
  input  wire [N-1:0]   m_tready,
  output wire [N-1:0]   m_tlast
);
  reg [N-1:0] done;
  assign m_tvalid = {N{s_tvalid}} & ~done;
  assign s_tready = &(done | m_tready);
  assign m_tdata  = {N{s_tdata}};
  assign m_tlast  = {N{s_tlast}};

  always @(posedge clk)
    if (!rst_n)                    done <= {N{1'b0}};
    else if (s_tvalid && s_tready) done <= {N{1'b0}};
    else                           done <= done | (m_tvalid & m_tready);
endmodule

`default_nettype wire
