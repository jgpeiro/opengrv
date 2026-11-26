// grv_resize - reduce an exact result to an output width: round, shift, overflow handling.
// Combinational. SHIFT > 0 drops SHIFT LSBs with rounding, SHIFT < 0 shifts left.
//   ROUND: 0 floor, 1 half up, 2 half away from zero, 3 convergent (half to even)
//   SAT  : 0 wrap, 1 saturate, 2 symmetric saturate (signed only)
// ovf is 1 when the value was clamped (SAT != 0).
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_resize #(
  parameter integer GW      = 32,
  parameter integer OW      = 16,
  parameter integer SHIFT   = 0,
  parameter integer ROUND   = 1,
  parameter integer SAT     = 1,
  parameter integer ISIGNED = 1,
  parameter integer OSIGNED = 1
)(
  input  wire [GW-1:0] x,
  output wire [OW-1:0] y,
  output wire          ovf
);
  localparam integer S  = (SHIFT > 0) ? SHIFT : 0;
  localparam integer LS = (SHIFT < 0) ? -SHIFT : 0;
  localparam integer EW = ((GW + LS > S + 1) ? GW + LS : S + 1) + 2;
  localparam integer CW = (EW > OW + 2) ? EW : OW + 2;

  wire signed [EW-1:0] xe0 = (ISIGNED != 0) ? {{(EW-GW){x[GW-1]}}, x} : {{(EW-GW){1'b0}}, x};
  wire signed [EW-1:0] xe  = xe0 <<< LS;
  wire signed [EW-1:0] rc;
  wire        [EW-1:0] one = {{(EW-1){1'b0}}, 1'b1};

  generate
    if (S == 0 || ROUND == 0) begin : g_rnone
      assign rc = {EW{1'b0}};
    end else if (ROUND == 1) begin : g_rup
      assign rc = $signed(one << (S - 1));
    end else if (ROUND == 2) begin : g_raway
      assign rc = $signed(one << (S - 1)) - $signed({{(EW-1){1'b0}}, xe[EW-1]});
    end else begin : g_rconv
      assign rc = $signed(one << (S - 1)) - $signed(one) + $signed({{(EW-1){1'b0}}, xe[S]});
    end
  endgenerate

  wire signed [EW-1:0] xr  = xe + rc;
  wire signed [EW-1:0] ys  = xr >>> S;
  wire signed [CW-1:0] ysc = {{(CW-EW){ys[EW-1]}}, ys};

  wire        [CW-1:0] onec = {{(CW-1){1'b0}}, 1'b1};
  wire signed [CW-1:0] maxv = (OSIGNED != 0) ? $signed((onec << (OW - 1)) - onec) : $signed((onec << OW) - onec);
  wire signed [CW-1:0] minv = (OSIGNED == 0) ? {CW{1'b0}} :
                              (SAT == 2) ? -maxv : -$signed(onec << (OW - 1));
  wire hi = ysc > maxv;
  wire lo = ysc < minv;

  assign y   = (SAT != 0 && hi) ? maxv[OW-1:0] : (SAT != 0 && lo) ? minv[OW-1:0] : ysc[OW-1:0];
  assign ovf = (SAT != 0) && (hi || lo);
endmodule

`default_nettype wire
