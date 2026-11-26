# OpenGRV - test and example targets
PY ?= python3

.PHONY: all test unit pe ctrl graph errors example example_pe examples lint synth clean

all: test

test: unit pe ctrl graph errors example example_pe examples lint

unit:
	$(PY) tb/unit/run_tests.py -j 8

examples:
	$(PY) tools/run_examples.py -j 4 --no-copy

pe:
	$(PY) tb/pe/run_pe.py -j 8

ctrl:
	mkdir -p build && cd tb/axil && iverilog -g2005 -I../../rtl/inc -I../../rtl/prim -y../../rtl/prim -y../../rtl/axil -Y.v -o ../../build/tb_ctrl tb_ctrl.v
	vvp -n build/tb_ctrl | grep -q PASS && echo "PASS tb_ctrl"

graph:
	$(PY) tb/graph/test_graphs.py -j 4

errors:
	$(PY) tb/graph/test_errors.py

example: build/nbfm/nbfm_rx_top.v
	$(PY) examples/nbfm_rx/check_float.py build/nbfm --save build/nbfm_in.npy
	build/nbfm/nbfm_rx_top_sim.sh -n 76800 --input adc_iq=$(CURDIR)/build/nbfm_in.npy --param tune=100e3 --param volume=0.7

build/nbfm/nbfm_rx_top.v: examples/nbfm_rx/nbfm_rx.grc
	$(PY) grvgen/grvgen.py $< -o build/nbfm

example_pe: build/nbfm_pe/nbfm_rx_top.v
	build/nbfm_pe/nbfm_rx_top_sim.sh -n 20000 --param tune=100e3

build/nbfm_pe/nbfm_rx_top.v: examples/nbfm_rx_pe/nbfm_rx_pe.grc
	$(PY) grvgen/grvgen.py $< -o build/nbfm_pe

lint: build/nbfm/nbfm_rx_top.v build/nbfm_pe/nbfm_rx_top.v
	tools/lint.sh build/nbfm/nbfm_rx_top.f build/nbfm_pe/nbfm_rx_top.f

synth: build/nbfm/nbfm_rx_top.v
	tools/synth.sh build/nbfm/nbfm_rx_top.f

clean:
	rm -rf build
