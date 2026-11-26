// generated: atan(2^-i) / (2 pi) * 2^32, i = 0 .. 31 (grvgen/grv/fx.py ATAN)
  function [31:0] atan;
    input [5:0] i;
    case (i)
      6'd0: atan = 32'h20000000;
      6'd1: atan = 32'h12E4051E;
      6'd2: atan = 32'h09FB385B;
      6'd3: atan = 32'h051111D4;
      6'd4: atan = 32'h028B0D43;
      6'd5: atan = 32'h0145D7E1;
      6'd6: atan = 32'h00A2F61E;
      6'd7: atan = 32'h00517C55;
      6'd8: atan = 32'h0028BE53;
      6'd9: atan = 32'h00145F2F;
      6'd10: atan = 32'h000A2F98;
      6'd11: atan = 32'h000517CC;
      6'd12: atan = 32'h00028BE6;
      6'd13: atan = 32'h000145F3;
      6'd14: atan = 32'h0000A2FA;
      6'd15: atan = 32'h0000517D;
      6'd16: atan = 32'h000028BE;
      6'd17: atan = 32'h0000145F;
      6'd18: atan = 32'h00000A30;
      6'd19: atan = 32'h00000518;
      6'd20: atan = 32'h0000028C;
      6'd21: atan = 32'h00000146;
      6'd22: atan = 32'h000000A3;
      6'd23: atan = 32'h00000051;
      6'd24: atan = 32'h00000029;
      6'd25: atan = 32'h00000014;
      6'd26: atan = 32'h0000000A;
      6'd27: atan = 32'h00000005;
      6'd28: atan = 32'h00000003;
      6'd29: atan = 32'h00000001;
      6'd30: atan = 32'h00000001;
      6'd31: atan = 32'h00000000;
      default: atan = 32'h0;
    endcase
  endfunction
