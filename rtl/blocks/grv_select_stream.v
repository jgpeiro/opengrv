// grv_select_stream - sample selection blocks, one input, one output, no arithmetic:
//   MODE 0 head (pass the first N), 1 skiphead (drop the first N),
//   MODE 2 keep_one_in_n (keep sample n-1 of every cfg_n), 3 keep_m_in_n (keep M of every N from OFFSET),
//   MODE 4 copy (pass while cfg_en, drop otherwise)
// Dropped samples are consumed without back-pressure. Latency 1 + OREG.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_select_stream #(
  parameter integer W      = 16,
  parameter integer MODE   = 2,
  parameter [31:0]  N      = 32'd1,
  parameter integer M      = 1,
  parameter integer OFFSET = 0,
  parameter integer OREG   = 1
)(
  input  wire         clk,
  input  wire         rst_n,
  input  wire [W-1:0] s_tdata,
  input  wire         s_tvalid,
  output wire         s_tready,
  input  wire         s_tlast,
  input  wire [31:0]  cfg_n,
  input  wire         cfg_en,
  output wire [W-1:0] m_tdata,
  output wire         m_tvalid,
  input  wire         m_tready,
  output wire         m_tlast
);
  reg  [31:0] cnt;
  wire [31:0] nn = (MODE == 2) ? cfg_n : N;
  wire [31:0] rel = (cnt >= OFFSET) ? cnt - OFFSET : cnt + N - OFFSET;
  reg  pass;
  always @(*) case (MODE)
    0: pass = cnt < N;
    1: pass = cnt >= N;
    2: pass = cnt == nn - 1;
    3: pass = rel < M;
    default: pass = cfg_en;
  endcase
  wire ce, pv, pr;
  wire [1:1] v;
  grv_pctl #(.L(1)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(s_tvalid && pass), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));
  assign s_tready = pass ? ce : 1'b1;
  wire take = s_tvalid && s_tready;
  always @(posedge clk) begin
    if (!rst_n) cnt <= 32'd0;
    else if (take) case (MODE)
      0, 1: if (cnt != 32'hFFFFFFFF && cnt < N) cnt <= cnt + 1'b1;
      2, 3: cnt <= (cnt >= nn - 1) ? 32'd0 : cnt + 1'b1;
      default: cnt <= cnt;
    endcase
  end
  reg [W-1:0] o1;
  reg         l1;
  always @(posedge clk) if (ce) begin o1 <= s_tdata; l1 <= s_tlast; end
  grv_oreg #(.W(W), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o1), .s_tvalid(pv), .s_tready(pr),
    .s_tlast(l1), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
