// grv_squelch - analog_simple_squelch_cc, analog_pwr_squelch_xx (ramp 0):
//   p = |x|^2 ; s += (((p << G) - s) * alpha) >>> AF ; open = s >= thr
//   output x when open; when closed, 0 (GATE = 0) or nothing (GATE = 1). One sample every 5 clocks.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_squelch #(
  parameter integer IW    = 16,
  parameter integer CPLX  = 1,
  parameter integer G     = 4,
  parameter integer AW    = 18,
  parameter integer AF    = 17,
  parameter integer GATE  = 0,
  parameter integer OREG  = 1
)(
  input  wire                   clk,
  input  wire                   rst_n,
  input  wire [IW*(CPLX+1)-1:0] s_tdata,
  input  wire                   s_tvalid,
  output wire                   s_tready,
  input  wire                   s_tlast,
  input  wire [AW-1:0]          cfg_alpha,
  input  wire [2*IW+G+1:0]      cfg_thr,
  output wire [IW*(CPLX+1)-1:0] m_tdata,
  output wire                   m_tvalid,
  input  wire                   m_tready,
  output wire                   m_tlast,
  output wire                   st_open
);
  localparam integer NC = CPLX + 1;
  localparam integer SW = 2 * IW + G + 2;
  localparam integer PW = SW + AW + 1;
  localparam [2:0] S_IDLE = 3'd0, S_D = 3'd1, S_M = 3'd2, S_U = 3'd3, S_OUT = 3'd4;
  reg [2:0] st;
  reg [IW*NC-1:0] x;
  reg lt, open;
  wire o_r;
  reg  signed [SW-1:0] s, d, pw;
  reg  signed [PW-1:0] m;
  wire signed [IW-1:0] xr = s_tdata[0 +: IW];
  wire signed [IW-1:0] xi = s_tdata[IW*CPLX +: IW];
  wire signed [SW-1:0] sn = s + (m >>> AF);
  assign s_tready = (st == S_IDLE);
  assign st_open = open;
  always @(posedge clk) begin
    if (!rst_n) begin
      st <= S_IDLE; s <= {SW{1'b0}}; open <= 1'b0;
    end else case (st)
      S_IDLE: if (s_tvalid) begin
        pw <= (CPLX != 0) ? (xr * xr + xi * xi) : (xr * xr);
        x  <= s_tdata;
        lt <= s_tlast;
        st <= S_D;
      end
      S_D: begin d <= (pw <<< G) - s; st <= S_M; end
      S_M: begin m <= d * $signed({1'b0, cfg_alpha}); st <= S_U; end
      S_U: begin
        s    <= sn;
        open <= sn >= $signed({1'b0, cfg_thr});
        st   <= (GATE != 0 && !(sn >= $signed({1'b0, cfg_thr}))) ? S_IDLE : S_OUT;
      end
      default: if (o_r) st <= S_IDLE;
    endcase
  end
  grv_oreg #(.W(IW*NC), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(open ? x : {IW*NC{1'b0}}), .s_tvalid(st == S_OUT),
    .s_tready(o_r), .s_tlast(lt), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
