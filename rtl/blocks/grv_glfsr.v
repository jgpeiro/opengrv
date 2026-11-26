// grv_glfsr - digital_glfsr_source_x: Galois LFSR as in GNU Radio's glfsr:
//   bit = reg & 1; reg >>= 1; if (bit) reg ^= MASK.
// OUTF 0: bytes 0 / 1 (OW = 8); 1: -ONE / +ONE in the output format. Without REPEAT the source
// stops after 2^DEGREE - 1 bits.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_glfsr #(
  parameter integer DEGREE = 8,
  parameter [31:0]  MASK   = 32'h8E,
  parameter [31:0]  SEED   = 32'h1,
  parameter integer REPEAT = 1,
  parameter integer OUTF   = 0,
  parameter integer OW     = 8,
  parameter integer ONE    = 1,
  parameter integer OREG   = 1
)(
  input  wire          clk,
  input  wire          rst_n,
  input  wire          run,
  output wire [OW-1:0] m_tdata,
  output wire          m_tvalid,
  input  wire          m_tready,
  output wire          m_tlast
);
  reg  [31:0] sr;
  reg  [31:0] cnt;
  reg         done;
  wire go = run && !done;
  wire ce, pv, pr;
  wire [1:1] v;
  grv_pctl #(.L(1)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(go), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));

  wire signed [OW-1:0] one = ONE;
  reg [OW-1:0] o1;
  always @(posedge clk) if (ce) o1 <= (OUTF == 0) ? {{(OW-1){1'b0}}, sr[0]} : (sr[0] ? one : -one);
  always @(posedge clk) begin
    if (!rst_n) begin
      sr <= SEED; cnt <= 32'd0; done <= 1'b0;
    end else if (ce && go) begin
      sr  <= sr[0] ? ((sr >> 1) ^ MASK) : (sr >> 1);
      cnt <= cnt + 1'b1;
      if (REPEAT == 0 && cnt == (32'd1 << DEGREE) - 32'd2) done <= 1'b1;
    end
  end

  grv_oreg #(.W(OW), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o1), .s_tvalid(pv), .s_tready(pr),
    .s_tlast(1'b0), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
