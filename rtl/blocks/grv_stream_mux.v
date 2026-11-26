// grv_stream_mux - blocks_stream_mux (LENS: LEN[k] samples from input k in turn; 32 bits each)
// and blocks_interleave (all LENS equal to blocksize). Latency 1 + OREG.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_stream_mux #(
  parameter integer NI   = 2,
  parameter integer W    = 16,
  parameter [32*NI-1:0] LENS = {NI{32'd1}},
  parameter integer OREG = 1
)(
  input  wire            clk,
  input  wire            rst_n,
  input  wire [NI*W-1:0] s_tdata,
  input  wire [NI-1:0]   s_tvalid,
  output wire [NI-1:0]   s_tready,
  input  wire [NI-1:0]   s_tlast,
  output wire [W-1:0]    m_tdata,
  output wire            m_tvalid,
  input  wire            m_tready,
  output wire            m_tlast
);
  localparam integer PW = (NI > 1) ? $clog2(NI) : 1;
  reg  [PW-1:0] port;
  reg  [31:0]   cnt;
  wire [31:0]   len = LENS[32*port +: 32];
  wire          sv  = s_tvalid[port];
  wire ce, pv, pr;
  wire [1:1] v;
  grv_pctl #(.L(1)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(sv), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));
  wire [NI-1:0] one = 1;
  assign s_tready = ce ? (one << port) : {NI{1'b0}};
  function [PW-1:0] nextp(input [PW-1:0] p);
    integer k;
    reg [PW-1:0] q;
    reg found;
    begin
      q = p; found = 1'b0;
      for (k = 1; k <= NI; k = k + 1)
        if (!found && LENS[32*((p + k) % NI) +: 32] != 0) begin q = (p + k) % NI; found = 1'b1; end
      nextp = q;
    end
  endfunction
  function [PW-1:0] firstp(input integer dummy);
    integer k;
    reg found;
    begin
      firstp = 0; found = 1'b0;
      for (k = 0; k < NI; k = k + 1)
        if (!found && LENS[32*k +: 32] != 0) begin firstp = k; found = 1'b1; end
    end
  endfunction
  always @(posedge clk) begin
    if (!rst_n) begin
      port <= firstp(0); cnt <= 32'd0;
    end else if (ce && sv) begin
      if (cnt == len - 1) begin cnt <= 32'd0; port <= nextp(port); end
      else cnt <= cnt + 1'b1;
    end
  end
  reg [W-1:0] o1;
  reg         l1;
  always @(posedge clk) if (ce) begin o1 <= s_tdata[W*port +: W]; l1 <= s_tlast[port]; end
  grv_oreg #(.W(W), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o1), .s_tvalid(pv), .s_tready(pr),
    .s_tlast(l1), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
