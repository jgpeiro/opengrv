// grv_axil_dec - AXI4-Lite slave of the generated top level and the internal register bus.
// One transaction at a time, writes first. A write is accepted (AW and W together) in the clock
// in which the target can take it (t_wrdy) or the TIMEOUT has expired (rb_force); B follows in
// the next clock. A read is accepted when the target can serve it; R follows in the next clock,
// RDATA from the target's read register. Responses: OKAY, SLVERR (WSTRB not 4'hF, timeout),
// DECERR (no target). Targets: 0 global/parameters, then NS source endpoints, NK sink endpoints
// (with their capture windows), the probe block (when NP > 0), NE peripheral endpoints and ND DMA
// channels.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_axil_dec #(
  parameter integer NS = 1,
  parameter integer NK = 1,
  parameter integer NP = 1,
  parameter integer NE = 0,               // peripheral endpoints (0x6000 + 0x100 k)
  parameter integer ND = 0                // DMA channels (0x7000 + 0x100 k)
)(
  input  wire               clk,
  input  wire               rst_n,
  input  wire [15:0]        timeout,
  // AXI4-Lite
  input  wire [15:0]        s_axil_awaddr,
  input  wire               s_axil_awvalid,
  output wire               s_axil_awready,
  input  wire [31:0]        s_axil_wdata,
  input  wire [3:0]         s_axil_wstrb,
  input  wire               s_axil_wvalid,
  output wire               s_axil_wready,
  output reg  [1:0]         s_axil_bresp,
  output reg                s_axil_bvalid,
  input  wire               s_axil_bready,
  input  wire [15:0]        s_axil_araddr,
  input  wire               s_axil_arvalid,
  output wire               s_axil_arready,
  output wire [31:0]        s_axil_rdata,
  output reg  [1:0]         s_axil_rresp,
  output reg                s_axil_rvalid,
  input  wire               s_axil_rready,
  // register bus
  output wire [15:0]        rb_addr,
  output wire [31:0]        rb_wdata,
  output wire               rb_we,
  output wire               rb_re,
  output wire               rb_force,
  output wire [1+NS+NK+((NP>0)?1:0)+NE+ND-1:0] rb_sel,
  input  wire [1+NS+NK+((NP>0)?1:0)+NE+ND-1:0] t_wrdy,
  input  wire [1+NS+NK+((NP>0)?1:0)+NE+ND-1:0] t_rrdy,
  input  wire [32*(1+NS+NK+((NP>0)?1:0)+NE+ND)-1:0] t_rdata
);
  localparam integer NT = 1 + NS + NK + ((NP > 0) ? 1 : 0) + NE + ND;
  localparam integer TP = 1 + NS + NK + ((NP > 0) ? 1 : 0);
  localparam integer TW = $clog2(NT + 1);

  // target of an address (NT = none)
  function [TW-1:0] target(input [15:0] a);
    begin
      target = NT;
      if (a[15:12] == 4'h0) target = 0;
      else if (a[15:12] == 4'h1 && a[11:8] < NS) target = 1 + a[11:8];
      else if (a[15:12] == 4'h2 && a[11:8] < NK) target = 1 + NS + a[11:8];
      else if (a[15] && a[14:13] < NK) target = 1 + NS + a[14:13];
      else if (a[15:12] == 4'h3 && NP > 0) target = 1 + NS + NK;
      else if (a[15:12] == 4'h6 && a[11:8] < NE) target = TP + a[11:8];
      else if (a[15:12] == 4'h7 && a[11:8] < ND) target = TP + NE + a[11:8];
    end
  endfunction

  wire busy = s_axil_bvalid || s_axil_rvalid;
  wire wreq = !busy && s_axil_awvalid && s_axil_wvalid;
  wire rreq = !busy && !wreq && s_axil_arvalid;
  wire [15:0]   a  = wreq ? s_axil_awaddr : s_axil_araddr;
  wire [TW-1:0] t  = target(a);
  wire          tv = (t < NT);
  wire [NT-1:0] one = 1;
  wire [NT-1:0] sel = tv ? (one << t) : {NT{1'b0}};
  reg  [15:0]   wcnt;
  wire          tmo = (timeout != 16'd0) && (wcnt >= timeout);
  wire          strb_ok = (s_axil_wstrb == 4'hF);
  wire          w_go = wreq && (!tv || !strb_ok || t_wrdy[t] || tmo);
  wire          r_go = rreq && (!tv || t_rrdy[t] || tmo);
  assign s_axil_awready = w_go;
  assign s_axil_wready  = w_go;
  assign s_axil_arready = r_go;
  assign rb_addr  = a;
  assign rb_wdata = s_axil_wdata;
  assign rb_we    = w_go && tv && strb_ok;
  assign rb_re    = r_go && tv;
  assign rb_force = tmo;
  assign rb_sel   = sel;

  reg [TW-1:0] rt;
  reg          rtv;
  always @(posedge clk) begin
    if (!rst_n) begin
      s_axil_bvalid <= 1'b0; s_axil_rvalid <= 1'b0; wcnt <= 16'd0; rtv <= 1'b0;
    end else begin
      if (s_axil_bvalid && s_axil_bready) s_axil_bvalid <= 1'b0;
      if (s_axil_rvalid && s_axil_rready) s_axil_rvalid <= 1'b0;
      if ((wreq && !w_go) || (rreq && !r_go)) wcnt <= wcnt + 1'b1;
      else wcnt <= 16'd0;
      if (w_go) begin
        s_axil_bvalid <= 1'b1;
        s_axil_bresp  <= !tv ? 2'b11 : (!strb_ok || (tmo && !t_wrdy[t])) ? 2'b10 : 2'b00;
      end
      if (r_go) begin
        s_axil_rvalid <= 1'b1;
        s_axil_rresp  <= !tv ? 2'b11 : (tmo && !t_rrdy[t]) ? 2'b10 : 2'b00;
        rt  <= t;
        rtv <= tv;
      end
    end
  end
  assign s_axil_rdata = rtv ? t_rdata[32*rt +: 32] : 32'd0;
endmodule

`default_nettype wire
