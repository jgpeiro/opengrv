// grv_add - blocks_add_xx, blocks_sub_xx (SUB=1: in0 - in1 - ...): sum of NI streams.
// Input k is shifted left by SHIFT_IN[6k +: 6] to align binary points, the exact sum is resized.
// tlast comes from input 0. Latency 2 + OREG.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_add #(
  parameter integer NI       = 2,
  parameter integer IW       = 16,
  parameter integer CPLX     = 0,
  parameter integer OW       = 16,
  parameter [6*NI-1:0] SHIFT_IN = {6*NI{1'b0}},
  parameter integer SUB      = 0,
  parameter integer SHIFT    = 1,
  parameter integer ROUND    = 1,
  parameter integer SAT      = 1,
  parameter integer OREG     = 1
)(
  input  wire                      clk,
  input  wire                      rst_n,
  input  wire [NI*IW*(CPLX+1)-1:0] s_tdata,
  input  wire [NI-1:0]             s_tvalid,
  output wire [NI-1:0]             s_tready,
  input  wire [NI-1:0]             s_tlast,
  output wire [OW*(CPLX+1)-1:0]    m_tdata,
  output wire                      m_tvalid,
  input  wire                      m_tready,
  output wire                      m_tlast,
  output wire                      ovf
);
  localparam integer NC = CPLX + 1;
  function integer maxsh(input integer dummy);
    integer k, m;
    begin
      m = 0;
      for (k = 0; k < NI; k = k + 1) if (SHIFT_IN[6*k +: 6] > m) m = SHIFT_IN[6*k +: 6];
      maxsh = m;
    end
  endfunction
  localparam integer GW = IW + maxsh(0) + $clog2(NI) + 1;
  localparam integer LATENCY = 2 + OREG;

  wire all_v = &s_tvalid;
  wire ce, pv, pr;
  wire [2:1] v;
  grv_pctl #(.L(2)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(all_v), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));
  assign s_tready = {NI{ce && all_v}};

  wire [OW*NC-1:0] r;
  wire [NC-1:0]    ov;
  reg  [OW*NC-1:0] o2;
  reg  [1:0]       l;
  reg              ov2;
  genvar c;
  generate
    for (c = 0; c < NC; c = c + 1) begin : g_c
      reg signed [GW-1:0] acc, s1;
      integer k;
      always @(*) begin
        acc = {GW{1'b0}};
        for (k = 0; k < NI; k = k + 1) begin
          if (SUB != 0 && k > 0)
            acc = acc - ($signed({{(GW-IW){s_tdata[(k*NC+c)*IW+IW-1]}}, s_tdata[(k*NC+c)*IW +: IW]}) <<< SHIFT_IN[6*k +: 6]);
          else
            acc = acc + ($signed({{(GW-IW){s_tdata[(k*NC+c)*IW+IW-1]}}, s_tdata[(k*NC+c)*IW +: IW]}) <<< SHIFT_IN[6*k +: 6]);
        end
      end
      always @(posedge clk) if (ce) s1 <= acc;
      grv_resize #(.GW(GW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_r (.x(s1), .y(r[c*OW +: OW]), .ovf(ov[c]));
    end
  endgenerate
  always @(posedge clk) if (ce) begin
    o2  <= r;
    l   <= {l[0], s_tlast[0]};
    ov2 <= v[1] & |ov;
  end
  assign ovf = ov2 & ce & v[2];

  grv_oreg #(.W(OW*NC), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(o2), .s_tvalid(pv), .s_tready(pr),
    .s_tlast(l[1]), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
