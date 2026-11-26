// register-bus tasks for the endpoint testbenches (one target per rb_sel bit)
task rb_write(input integer t, input [15:0] a, input [31:0] d);
  begin
    @(negedge clk); rb_sel = 0; rb_sel[t] = 1'b1; rb_addr = a; rb_wdata = d; rb_we = 1'b1;
    @(negedge clk); rb_we = 1'b0; rb_sel = 0;
  end
endtask
task rb_read(input integer t, input [15:0] a, output [31:0] d);
  begin
    @(negedge clk); rb_sel = 0; rb_sel[t] = 1'b1; rb_addr = a; rb_re = 1'b1;
    @(negedge clk); rb_re = 1'b0; rb_sel = 0;
    d = rdata_of(t);
  end
endtask
