// grv_const_decoder - digital_constellation_decoder_cb: index of the nearest of NP points
// (squared Euclidean distance, first minimum wins), output SYMS[index]. One point per clock:
// one sample every NP + 3 clocks. POINTS: {Q, I} of PW bits each, in the input format.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_const_decoder #(
  parameter integer IW   = 16,
  parameter integer NP   = 4,
  parameter [NP*2*IW-1:0] POINTS = {NP*2*IW{1'b0}},
  parameter [NP*8-1:0]    SYMS   = {NP*8{1'b0}},
  parameter integer OREG = 1
)(
  input  wire            clk,
  input  wire            rst_n,
  input  wire [2*IW-1:0] s_tdata,
  input  wire            s_tvalid,
  output wire            s_tready,
  input  wire            s_tlast,
  output wire [7:0]      m_tdata,
  output wire            m_tvalid,
  input  wire            m_tready,
  output wire            m_tlast
);
  localparam integer KW = (NP > 1) ? $clog2(NP + 1) : 1;
  localparam integer DW = 2 * IW + 3;
  localparam [1:0] S_IDLE = 2'd0, S_RUN = 2'd1, S_OUT = 2'd2;
  reg [1:0]  st;
  reg [KW-1:0] k;
  reg signed [IW-1:0] xr, xi;
  reg [DW-1:0] best;
  reg [7:0]    bsym;
  reg          lt;
  wire         o_r;
  assign s_tready = (st == S_IDLE);
  wire signed [IW-1:0] pr = POINTS[(2*k)*IW +: IW];
  wire signed [IW-1:0] pi = POINTS[(2*k+1)*IW +: IW];
  wire signed [IW:0]   dr = xr - pr;
  wire signed [IW:0]   di = xi - pi;
  wire [DW-1:0] d2 = dr * dr + di * di;
  always @(posedge clk) begin
    if (!rst_n) st <= S_IDLE;
    else case (st)
      S_IDLE: if (s_tvalid) begin
        xr <= s_tdata[0 +: IW]; xi <= s_tdata[IW +: IW]; lt <= s_tlast; k <= 0; st <= S_RUN;
      end
      S_RUN: begin
        if (k == 0 || d2 < best) begin best <= d2; bsym <= SYMS[8*k +: 8]; end
        k <= k + 1'b1;
        if (k == NP - 1) st <= S_OUT;
      end
      default: if (o_r) st <= S_IDLE;
    endcase
  end
  grv_oreg #(.W(8), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(bsym), .s_tvalid(st == S_OUT), .s_tready(o_r),
    .s_tlast(lt), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
