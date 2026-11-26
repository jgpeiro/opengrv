// grv_elem - element-wise one-input operations, selected by OP:
//   0 conjugate (blocks_conjugate_cc): (I, -Q), Q resized with SAT
//   1 abs (blocks_abs_xx): |x| resized
//   2 magnitude squared (blocks_complex_to_mag_squared): I*I + Q*Q resized
//   3 negate: -x resized
// Latency 3 + OREG.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_elem #(
  parameter integer OP    = 1,
  parameter integer IW    = 16,
  parameter integer CPLX  = 0,
  parameter integer OW    = 16,
  parameter integer SHIFT = 0,
  parameter integer ROUND = 1,
  parameter integer SAT   = 1,
  parameter integer OREG  = 1
)(
  input  wire                   clk,
  input  wire                   rst_n,
  input  wire [IW*(CPLX+1)-1:0] s_tdata,
  input  wire                   s_tvalid,
  output wire                   s_tready,
  input  wire                   s_tlast,
  output wire [OW*((OP==0)?2:((OP==2)?1:(CPLX+1)))-1:0] m_tdata,
  output wire                   m_tvalid,
  input  wire                   m_tready,
  output wire                   m_tlast,
  output wire                   ovf
);
  localparam integer NCO = (OP == 0) ? 2 : ((OP == 2) ? 1 : (CPLX + 1));
  localparam integer GW  = 2 * IW + 2;
  localparam integer LATENCY = 3 + OREG;
  wire ce, pv, pr;
  wire [3:1] v;
  grv_pctl #(.L(3)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(s_tvalid), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));
  assign s_tready = ce;

  wire signed [IW-1:0] xr = s_tdata[0 +: IW];
  wire signed [IW-1:0] xi = s_tdata[IW*CPLX +: IW];
  reg  signed [GW-1:0] a1, b1, a2, b2;
  always @(posedge clk) if (ce) begin
    case (OP)
      0: begin a1 <= xr; b1 <= -$signed({xi[IW-1], xi}); end
      1: begin a1 <= xr[IW-1] ? -$signed({xr[IW-1], xr}) : xr; b1 <= xi[IW-1] ? -$signed({xi[IW-1], xi}) : xi; end
      2: begin a1 <= xr * xr; b1 <= xi * xi; end
      default: begin a1 <= -$signed({xr[IW-1], xr}); b1 <= -$signed({xi[IW-1], xi}); end
    endcase
    if (OP == 2) begin
      a2 <= (CPLX != 0) ? a1 + b1 : a1;
      b2 <= {GW{1'b0}};
    end else begin
      a2 <= a1;
      b2 <= b1;
    end
  end
  wire [OW-1:0] ra, rb;
  wire          ova, ovb;
  // conjugate: I passes unchanged (SHIFT 0, wrap), Q with the block's SAT
  grv_resize #(.GW(GW), .OW(OW), .SHIFT((OP == 0) ? 0 : SHIFT), .ROUND(ROUND), .SAT((OP == 0) ? 0 : SAT)) u_ra (.x(a2), .y(ra), .ovf(ova));
  grv_resize #(.GW(GW), .OW(OW), .SHIFT((OP == 0) ? 0 : SHIFT), .ROUND(ROUND), .SAT(SAT)) u_rb (.x(b2), .y(rb), .ovf(ovb));
  reg [OW*NCO-1:0] o3;
  reg [2:0]        l;
  reg              ov3;
  always @(posedge clk) if (ce) begin
    o3  <= (NCO == 2) ? {rb, ra} : ra;
    l   <= {l[1:0], s_tlast};
    ov3 <= v[2] & (ova | (ovb & (NCO == 2)));
  end
  assign ovf = ov3 & ce & v[3];
  grv_oreg #(.W(OW*NCO), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o3), .s_tvalid(pv), .s_tready(pr),
    .s_tlast(l[2]), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
