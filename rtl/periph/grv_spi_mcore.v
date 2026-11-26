// grv_spi_mcore - SPI master engine: one frame of FBITS bits (1 .. 32) per start.
// Each bit is two half periods of HALF + 1 clocks; MOSI changes at the start of the first half,
// MISO is sampled at the start of the second half, SDLY clocks later, through the synchroniser
// (miso_s is the synchronised pin). SCLK is CPOL ^ CPHA in the first half and the inverse in the
// second, which gives the four SPI modes. Chip select falls SETUP clocks before the first half and
// rises HOLD clocks after the last bit, then stays high at least GAP clocks (each at least 1).
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_spi_mcore (
  input  wire        clk,
  input  wire        rst_n,
  input  wire        start,
  input  wire [31:0] tx,
  input  wire [4:0]  fbits,       // FBITS - 1
  input  wire        cpol,
  input  wire        cpha,
  input  wire        lsbf,
  input  wire [7:0]  half,
  input  wire [7:0]  setup,
  input  wire [7:0]  hold,
  input  wire [7:0]  gap,
  input  wire [1:0]  sdly,
  input  wire        miso_s,
  output wire        busy,
  output reg         done,
  output reg  [31:0] rx,
  output reg         sclk,
  output reg         cs_n,
  output reg         mosi
);
  localparam S_IDLE = 3'd0, S_SETUP = 3'd1, S_H1 = 3'd2, S_H2 = 3'd3, S_HOLD = 3'd4, S_GAP = 3'd5, S_DRAIN = 3'd6;
  reg [2:0]  st;
  reg [7:0]  cnt;
  reg [4:0]  bi;            // bit being sent
  reg [4:0]  ri;            // bit being received (LSB first)
  reg [31:0] txr;
  reg [5:0]  sp;            // sample strobe pipeline
  wire       samp = sp[1 + sdly];
  assign busy = (st != S_IDLE);
  wire       obit = lsbf ? txr[bi] : txr[fbits - bi];

  always @(posedge clk) begin
    done <= 1'b0;
    if (!rst_n) begin
      st <= S_IDLE; cs_n <= 1'b1; sclk <= cpol; mosi <= 1'b0; sp <= 6'd0;
    end else begin
      sp <= {sp[4:0], 1'b0};
      if (samp) begin
        if (lsbf) rx[ri] <= miso_s;
        else rx <= {rx[30:0], miso_s};
        ri <= ri + 1'b1;
      end
      case (st)
        S_IDLE: begin
          sclk <= cpol;
          cs_n <= 1'b1;
          if (start) begin
            txr <= tx; bi <= 5'd0; ri <= 5'd0; rx <= 32'd0;
            cs_n <= 1'b0; cnt <= setup; st <= S_SETUP;
          end
        end
        S_SETUP: begin
          if (cnt <= 8'd1) begin
            st <= S_H1; cnt <= half; sclk <= cpol ^ cpha; mosi <= lsbf ? txr[0] : txr[fbits];
          end else cnt <= cnt - 1'b1;
        end
        S_H1: begin
          if (cnt == 8'd0) begin
            st <= S_H2; cnt <= half; sclk <= ~(cpol ^ cpha); sp[0] <= 1'b1;
          end else cnt <= cnt - 1'b1;
        end
        S_H2: begin
          if (cnt == 8'd0) begin
            if (bi == fbits) begin
              st <= S_HOLD; cnt <= hold; sclk <= cpol;
            end else begin
              bi <= bi + 1'b1;
              st <= S_H1; cnt <= half; sclk <= cpol ^ cpha;
              mosi <= lsbf ? txr[bi + 1'b1] : txr[fbits - bi - 1'b1];
            end
          end else cnt <= cnt - 1'b1;
        end
        S_HOLD: begin
          if (cnt <= 8'd1) begin cs_n <= 1'b1; st <= S_GAP; cnt <= gap; end
          else cnt <= cnt - 1'b1;
        end
        S_GAP: begin
          if (cnt <= 8'd1) st <= S_DRAIN;
          else cnt <= cnt - 1'b1;
        end
        default: begin             // S_DRAIN: wait for the delayed samples
          if (sp == 6'd0 && !samp) begin st <= S_IDLE; done <= 1'b1; end
        end
      endcase
    end
  end
endmodule

`default_nettype wire
