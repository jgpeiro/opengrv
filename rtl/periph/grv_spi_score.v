// grv_spi_score - SPI slave engine. The pins are synchronised outside (sclk_s, cs_s, mosi_s, two
// flops); the serial clock must be at most clk / 8. On the sampling edge of the master (leading
// edge with CPHA = 0, trailing edge with CPHA = 1) MOSI is shifted in and MISO advances to the next
// bit, so MISO is stable for a whole serial clock period before the master samples it.
// SPDX-License-Identifier: MIT
`default_nettype none

module grv_spi_score (
  input  wire        clk,
  input  wire        rst_n,
  input  wire        sclk_s,
  input  wire        cs_s,         // chip select, active low, synchronised
  input  wire        mosi_s,
  input  wire [4:0]  fbits,
  input  wire        cpol,
  input  wire        cpha,
  input  wire        lsbf,
  input  wire [31:0] tx_word,      // next word to send, taken with tx_take
  input  wire        tx_fill,      // tx_word is a fill word (no data)
  output reg         tx_take,
  output reg         rx_valid,     // a word was received
  output reg  [31:0] rx_word,
  output reg         cs_fall,
  output reg         cs_rise,
  output reg  [4:0]  rx_bits,      // bits of the partial word at cs_rise
  output reg         miso,
  output reg         miso_oe
);
  reg        sk_d, cs_d;
  reg [4:0]  bi;           // bits received in the current word
  reg [4:0]  oi;           // bit being sent
  reg [31:0] tw, rsh;
  reg        pre, pre_fill;  // a word was loaded at the end of the previous word and not sent yet
  wire lead  = (sk_d == cpol) && (sclk_s != cpol);
  wire trail = (sk_d != cpol) && (sclk_s == cpol);
  wire samp  = !cs_s && (cpha ? trail : lead);
  wire [4:0] oi_n = (oi == fbits) ? 5'd0 : oi + 1'b1;
  always @(posedge clk) begin
    tx_take <= 1'b0; rx_valid <= 1'b0; cs_fall <= 1'b0; cs_rise <= 1'b0;
    if (!rst_n) begin
      sk_d <= 1'b0; cs_d <= 1'b1; bi <= 5'd0; oi <= 5'd0; miso_oe <= 1'b0; miso <= 1'b0; pre <= 1'b0;
    end else begin
      sk_d <= sclk_s;
      cs_d <= cs_s;
      miso_oe <= !cs_s;
      if (cs_d && !cs_s) begin                     // chip select falls: load the first word
        cs_fall <= 1'b1;
        bi <= 5'd0; oi <= 5'd0;
        if (pre && !pre_fill) begin
          miso <= lsbf ? tw[0] : tw[fbits];     // the word loaded at the end of the last frame
        end else begin
          tw <= tx_word; tx_take <= 1'b1; pre_fill <= tx_fill;
          miso <= lsbf ? tx_word[0] : tx_word[fbits];
        end
        pre <= 1'b0;
      end else if (!cs_d && cs_s) begin            // chip select rises
        cs_rise <= 1'b1;
        rx_bits <= bi;
        bi <= 5'd0;
      end else if (samp) begin
        if (lsbf) rsh <= {mosi_s, rsh[31:1]};
        else rsh <= {rsh[30:0], mosi_s};
        if (bi == fbits) begin
          bi <= 5'd0;
          rx_valid <= 1'b1;
          rx_word <= lsbf ? ({mosi_s, rsh[31:1]} >> (5'd31 - fbits)) : {rsh[30:0], mosi_s};
        end else bi <= bi + 1'b1;
        oi <= oi_n;
        pre <= (oi == fbits);
        if (oi == fbits) begin
          tw <= tx_word; tx_take <= 1'b1; pre_fill <= tx_fill;
          miso <= lsbf ? tx_word[0] : tx_word[fbits];
        end else miso <= lsbf ? tw[oi_n] : tw[fbits - oi_n];
      end
    end
  end
endmodule

`default_nettype wire
