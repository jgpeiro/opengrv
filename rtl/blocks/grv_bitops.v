// grv_bitops - bit-stream blocks on bytes (bit in the LSB), one output per input:
//   MODE 0 diff encoder  (digital_diff_encoder_bb): out = (in + last_out) mod MODULUS
//   MODE 1 diff decoder  (digital_diff_decoder_bb): out = (in - last_in) mod MODULUS
//   MODE 2 scrambler     (digital_scrambler_bb), GNU Radio lfsr::next_bit_scramble:
//          out = sr[0]; new = parity(sr & MASK) ^ in; sr = (sr >> 1) | (new << LEN)
//   MODE 3 descrambler   (digital_descrambler_bb), lfsr::next_bit_descramble:
//          out = parity(sr & MASK) ^ in; sr = (sr >> 1) | (in << LEN)
//   MODE 4 additive scrambler (digital_additive_scrambler_bb, bits_per_byte 1):
//          out = in ^ sr[0]; new = parity(sr & MASK); sr = (sr >> 1) | (new << LEN);
//          sr = SEED after COUNT bits (COUNT 0: never)
//   MODE 5 access code correlator (digital_correlate_access_code_bb): out = in | flag << 1,
//          flag = 1 when the LEN bits before this one differ from CODE in at most THR bits
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_bitops #(
  parameter integer MODE    = 0,
  parameter integer MODULUS = 2,
  parameter [63:0]  MASK    = 64'h0,
  parameter [63:0]  SEED    = 64'h0,
  parameter integer LEN     = 7,
  parameter integer COUNT   = 0,
  parameter [63:0]  CODE    = 64'h0,
  parameter integer THR     = 0,
  parameter integer OREG    = 1
)(
  input  wire       clk,
  input  wire       rst_n,
  input  wire [7:0] s_tdata,
  input  wire       s_tvalid,
  output wire       s_tready,
  input  wire       s_tlast,
  output wire [7:0] m_tdata,
  output wire       m_tvalid,
  input  wire       m_tready,
  output wire       m_tlast
);
  wire ce, pv, pr;
  wire [1:1] v;
  grv_pctl #(.L(1)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(s_tvalid), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));
  assign s_tready = ce;
  wire take = ce && s_tvalid;
  reg  [7:0]  last;
  reg  [63:0] sr;
  reg  [31:0] cnt;
  wire        par = ^(sr & MASK);
  wire        ib  = s_tdata[0];
  // access code
  wire [63:0] amask = (LEN >= 64) ? 64'hFFFFFFFFFFFFFFFF : ((64'd1 << LEN) - 1);
  wire [63:0] diff  = (sr ^ CODE) & amask;
  integer q;
  reg [6:0] nw;
  always @(*) begin
    nw = 0;
    for (q = 0; q < 64; q = q + 1) nw = nw + diff[q];
  end
  wire [8:0] sum = {1'b0, s_tdata} + {1'b0, last};
  wire [8:0] dif = ({1'b0, s_tdata} % MODULUS) + MODULUS - ({1'b0, last} % MODULUS);
  reg  [7:0] o;
  always @(*) case (MODE)
    0: o = sum % MODULUS;
    1: o = dif % MODULUS;
    2: o = {7'd0, sr[0]};
    3: o = {7'd0, par ^ ib};
    4: o = {7'd0, ib ^ sr[0]};
    default: o = {6'd0, (cnt >= LEN) && (nw <= THR), ib};
  endcase
  always @(posedge clk) begin
    if (!rst_n) begin
      last <= 8'd0; sr <= (MODE == 5) ? 64'd0 : SEED; cnt <= 32'd0;
    end else if (take) begin
      case (MODE)
        0: last <= o;
        1: last <= s_tdata;
        2: sr <= (sr >> 1) | ({63'd0, par ^ ib} << LEN);
        3: sr <= (sr >> 1) | ({63'd0, ib} << LEN);
        4: begin
          if (COUNT != 0 && cnt == COUNT - 1) begin sr <= SEED; cnt <= 32'd0; end
          else begin sr <= (sr >> 1) | ({63'd0, par} << LEN); cnt <= cnt + 1'b1; end
        end
        default: begin
          sr <= {sr[62:0], ib};
          if (cnt < LEN) cnt <= cnt + 1'b1;
        end
      endcase
    end
  end
  reg [7:0] o1;
  reg       l1;
  always @(posedge clk) if (ce) begin o1 <= o; l1 <= s_tlast; end
  grv_oreg #(.W(8), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o1), .s_tvalid(pv), .s_tready(pr),
    .s_tlast(l1), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
