// grv_fft - fft_vxx: N-point FFT (N = 8 .. 4096, power of two) on frames of N samples.
// The frame is windowed (WIN = 1: x * WINDOW[n] resized by WSH) and stored; an in-place radix-2
// decimation-in-frequency FFT runs with one butterfly unit, every stage scaling by 1/2:
//   a' = (a + b) >>> 1 ; b' = resize(((a - b) >>> 1) * W^k, >>> 17) ; W = exp(-+j 2 pi k / N)
// (twiddles from grv_sincos, FWD = 1 forward). The frame is read out in natural order
// (bit-reversed addressing), with SHIFTED = 1 as fftshift, resized from DW to OW bits (SHIFT).
// tlast marks the last sample of each output frame. About 6 * N/2 * log2(N) + 2 N clocks a frame.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_fft #(
  parameter integer N       = 64,
  parameter integer IW      = 16,
  parameter integer ICPLX   = 1,
  parameter integer DW      = 17,
  parameter integer FWD     = 1,
  parameter integer WIN     = 0,
  parameter integer WW      = 18,
  parameter [N*WW-1:0] WINDOW = {N*WW{1'b0}},
  parameter integer WSH     = 17,
  parameter integer SHIFTED = 0,
  parameter integer OW      = 16,
  parameter integer SHIFT   = 1,
  parameter integer ROUND   = 1,
  parameter integer SAT     = 1,
  parameter integer OREG    = 1
)(
  input  wire                    clk,
  input  wire                    rst_n,
  input  wire [IW*(ICPLX+1)-1:0] s_tdata,
  input  wire                    s_tvalid,
  output wire                    s_tready,
  input  wire                    s_tlast,
  output wire [2*OW-1:0]         m_tdata,
  output wire                    m_tvalid,
  input  wire                    m_tready,
  output wire                    m_tlast,
  output wire                    ovf
);
  localparam integer LG = $clog2(N);
  localparam integer TS = 12 - LG;                      // twiddle phase step: k << TS
  localparam integer PW = DW + 18 + 1;
  localparam [3:0] S_LOAD = 4'd0, S_RA = 4'd1, S_RB = 4'd2, S_WA = 4'd3, S_BF = 4'd4, S_MUL = 4'd5,
                   S_ROT = 4'd6, S_WR1 = 4'd7, S_WR2 = 4'd8, S_NEXT = 4'd9, S_OUT = 4'd10, S_OUTW = 4'd11;
  reg [3:0] st;

  // memory: {Q, I} of DW bits, one write and one read port
  reg [2*DW-1:0] mem [0:N-1];
  reg [LG-1:0]   ra, wa;
  reg [2*DW-1:0] wd, rd;
  reg            we;
  always @(posedge clk) begin
    rd <= mem[ra];
    if (we) mem[wa] <= wd;
  end
  reg [WW-1:0] wrom [0:N-1];
  integer i;
  initial for (i = 0; i < N; i = i + 1) wrom[i] = WINDOW[i*WW +: WW];

  // ---------------- load (window)
  reg  [LG:0]   n;                     // sample / output counter
  wire signed [IW-1:0] xr = s_tdata[0 +: IW];
  wire signed [IW-1:0] xi = (ICPLX != 0) ? s_tdata[IW*ICPLX +: IW] : {IW{1'b0}};
  wire signed [WW-1:0] wv = wrom[n[LG-1:0]];
  wire signed [IW+WW-1:0] xwr = xr * wv;
  wire signed [IW+WW-1:0] xwi = xi * wv;
  wire [DW-1:0] lr, li;
  grv_resize #(.GW(IW+WW), .OW(DW), .SHIFT(WSH), .ROUND(ROUND), .SAT(SAT)) u_wr (.x(xwr), .y(lr), .ovf());
  grv_resize #(.GW(IW+WW), .OW(DW), .SHIFT(WSH), .ROUND(ROUND), .SAT(SAT)) u_wi (.x(xwi), .y(li), .ovf());
  wire [DW-1:0] ldr = (WIN != 0) ? lr : {{(DW-IW){xr[IW-1]}}, xr};
  wire [DW-1:0] ldi = (WIN != 0) ? li : {{(DW-IW){xi[IW-1]}}, xi};
  assign s_tready = (st == S_LOAD);

  // ---------------- butterflies
  reg [LG-1:0] s;                      // stage
  reg [LG-1:0] g;                      // butterfly index within the stage (0 .. N/2-1)
  wire [LG-1:0] half = {{(LG-1){1'b0}}, 1'b1} << (LG - 1 - s);
  wire [LG-1:0] j    = g & (half - 1'b1);
  wire [LG-1:0] ia   = ((g >> (LG - 1 - s)) << (LG - s)) | j;
  wire [LG-1:0] ib   = ia | half;
  wire [LG-1:0] k    = j << s;
  wire [11:0]   tph  = {{(12-LG){1'b0}}, k} << TS;
  wire signed [17:0] tc, tsn;
  grv_sincos u_tw (.clk(clk), .ce(1'b1), .phase(tph), .cos_o(tc), .sin_o(tsn));
  reg  signed [DW-1:0] ar, ai, br, bi, dr, di;
  reg  signed [PW-1:0] p_rc, p_is, p_ic, p_rs;
  wire signed [DW:0]   sr_ = ar + br;
  wire signed [DW:0]   si_ = ai + bi;
  wire signed [DW:0]   dr_ = ar - br;
  wire signed [DW:0]   di_ = ai - bi;
  // forward: (dr + j di)(c - j s) = (dr c + di s) + j (di c - dr s) ; inverse: (dr c - di s) + j (di c + dr s)
  wire signed [PW-1:0] rr = (FWD != 0) ? p_rc + p_is : p_rc - p_is;
  wire signed [PW-1:0] ri = (FWD != 0) ? p_ic - p_rs : p_ic + p_rs;
  wire [DW-1:0] qr, qi;
  grv_resize #(.GW(PW), .OW(DW), .SHIFT(17), .ROUND(ROUND), .SAT(SAT)) u_qr (.x(rr), .y(qr), .ovf());
  grv_resize #(.GW(PW), .OW(DW), .SHIFT(17), .ROUND(ROUND), .SAT(SAT)) u_qi (.x(ri), .y(qi), .ovf());

  // ---------------- output (bit reversed, fftshift)
  function [LG-1:0] bitrev(input [LG-1:0] a);
    integer q;
    for (q = 0; q < LG; q = q + 1) bitrev[q] = a[LG-1-q];
  endfunction
  wire [LG-1:0] om  = n[LG-1:0] ^ ((SHIFTED != 0) ? {1'b1, {(LG-1){1'b0}}} : {LG{1'b0}});
  wire [OW-1:0] orr, ori;
  wire          ovr, ovi;
  grv_resize #(.GW(DW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_or (.x(rd[0 +: DW]), .y(orr), .ovf(ovr));
  grv_resize #(.GW(DW), .OW(OW), .SHIFT(SHIFT), .ROUND(ROUND), .SAT(SAT)) u_oi (.x(rd[DW +: DW]), .y(ori), .ovf(ovi));
  reg  [2*OW-1:0] od;
  reg             ol, ovq, rv;
  wire            o_r;
  reg             ov;

  always @(posedge clk) begin
    we  <= 1'b0;
    ovq <= 1'b0;
    if (!rst_n) begin
      st <= S_LOAD; n <= 0; ov <= 1'b0; rv <= 1'b0;
    end else case (st)
      S_LOAD: if (s_tvalid) begin
        we <= 1'b1; wa <= n[LG-1:0]; wd <= {ldi, ldr};
        if (n == N - 1) begin n <= 0; s <= 0; g <= 0; st <= S_RA; end
        else n <= n + 1'b1;
      end
      S_RA:  begin ra <= ia; st <= S_RB; end           // twiddle phase presented from here on
      S_RB:  begin ra <= ib; st <= S_WA; end
      S_WA:  begin ar <= rd[0 +: DW]; ai <= rd[DW +: DW]; st <= S_BF; end
      S_BF:  begin
        br <= rd[0 +: DW]; bi <= rd[DW +: DW];
        st <= S_MUL;
      end
      S_MUL: begin
        dr <= dr_ >>> 1; di <= di_ >>> 1;
        we <= 1'b1; wa <= ia; wd <= {si_[DW:1], sr_[DW:1]};
        st <= S_ROT;
      end
      S_ROT: begin
        p_rc <= dr * tc; p_is <= di * tsn; p_ic <= di * tc; p_rs <= dr * tsn;
        st <= S_WR1;
      end
      S_WR1: begin
        we <= 1'b1; wa <= ib; wd <= {qi, qr};
        st <= S_NEXT;
      end
      S_NEXT: begin
        if (g == N / 2 - 1) begin
          g <= 0;
          if (s == LG - 1) begin st <= S_OUT; n <= 0; end
          else begin s <= s + 1'b1; st <= S_RA; end
        end else begin
          g <= g + 1'b1; st <= S_RA;
        end
      end
      S_OUT: begin                                    // address of output n
        ra <= bitrev(om); st <= S_OUTW;
      end
      S_OUTW: begin                                   // data in the next clock
        if (!rv) begin
          rv <= 1'b1;                                 // rd valid after one wait clock
        end else if (!ov || o_r) begin
          od <= {ori, orr}; ol <= (n == N - 1); ov <= 1'b1; ovq <= ovr | ovi; rv <= 1'b0;
          if (n == N - 1) begin n <= 0; st <= S_LOAD; end
          else begin n <= n + 1'b1; st <= S_OUT; end
        end
      end
      default: st <= S_LOAD;
    endcase
    if (rst_n && ov && o_r && !(st == S_OUTW && rv && (!ov || o_r))) ov <= 1'b0;
  end
  assign ovf = ovq;
  grv_oreg #(.W(2*OW), .OREG(OREG)) u_o (.clk(clk), .rst_n(rst_n), .s_tdata(od), .s_tvalid(ov), .s_tready(o_r),
    .s_tlast(ol), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule

`default_nettype wire
