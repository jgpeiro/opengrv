// grv_delay - blocks_delay: y[n] = x[n - DELAY], zeros for the first DELAY outputs.
// Circular buffer of DELAY entries with read-before-write (block RAM above 64 entries).
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_delay #(
  parameter integer W     = 16,
  parameter integer DELAY = 1,
  parameter integer OREG  = 1
)(
  input  wire         clk,
  input  wire         rst_n,
  input  wire [W-1:0] s_tdata,
  input  wire         s_tvalid,
  output wire         s_tready,
  input  wire         s_tlast,
  output wire [W-1:0] m_tdata,
  output wire         m_tvalid,
  input  wire         m_tready,
  output wire         m_tlast
);
  localparam integer D  = (DELAY > 0) ? DELAY : 1;
  localparam integer AW = (D > 1) ? $clog2(D) : 1;
  wire ce, pv, pr;
  wire [1:1] v;
  grv_pctl #(.L(1)) u_ctl (.clk(clk), .rst_n(rst_n), .in_valid(s_tvalid), .out_ready(pr), .ce(ce), .out_valid(pv), .v(v));
  assign s_tready = ce;
  wire take = ce && s_tvalid;

  reg [W:0]    rd;
  reg          zf;
  reg [AW-1:0] ptr;
  reg          filled;
  generate
    if (DELAY == 0) begin : g_pass
      always @(posedge clk) if (ce) begin rd <= {s_tlast, s_tdata}; zf <= 1'b0; end
      always @(posedge clk) begin ptr <= 0; filled <= 1'b1; end
    end else begin : g_buf
      reg [W:0] mem [0:D-1];
      always @(posedge clk) if (ce) begin
        rd <= mem[ptr];
        if (take) mem[ptr] <= {s_tlast, s_tdata};
      end
      always @(posedge clk) begin
        if (!rst_n) begin
          ptr <= 0; filled <= 1'b0;
        end else if (take) begin
          ptr <= (ptr == D - 1) ? {AW{1'b0}} : ptr + 1'b1;
          if (ptr == D - 1) filled <= 1'b1;
        end
        if (ce) zf <= !filled;
      end
    end
  endgenerate
  grv_oreg #(.W(W), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(zf ? {W{1'b0}} : rd[W-1:0]), .s_tvalid(pv),
    .s_tready(pr), .s_tlast(zf ? 1'b0 : rd[W]), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
