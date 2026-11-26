#!/bin/sh
# Lints every library module (and optionally generated top levels: tools/lint.sh build/x/top.f) with
# Verilator -Wall. Width, unused-signal and style warnings are waived (see README); anything else fails.
cd "$(dirname "$0")/.."
W="-Wno-WIDTHEXPAND -Wno-WIDTHTRUNC -Wno-UNUSEDSIGNAL -Wno-UNUSEDPARAM -Wno-PINCONNECTEMPTY -Wno-BLKSEQ -Wno-UNUSEDGENVAR -Wno-DECLFILENAME -Wno-UNSIGNED"
fail=0
for f in rtl/prim/*.v rtl/blocks/*.v rtl/axil/*.v rtl/periph/*.v rtl/dma/*.v; do
  m=$(basename "$f" .v)
  if ! verilator --lint-only -Wall $W -Irtl/inc -Irtl/prim -Irtl/blocks -Irtl/axil -Irtl/periph -Irtl/dma --top-module "$m" "$f" > /tmp/lint_$m.log 2>&1; then
    echo "FAIL $m"; cat /tmp/lint_$m.log | head -20; fail=1
  fi
done
for fl in "$@"; do
  top=$(basename "$fl" .f)
  if ! verilator --lint-only -Wall $W --top-module "$top" -f "$fl" > /tmp/lint_$top.log 2>&1; then
    echo "FAIL $top"; head -20 /tmp/lint_$top.log; fail=1
  fi
done
[ $fail = 0 ] && echo "lint: all modules clean"
exit $fail
