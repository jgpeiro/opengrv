#!/bin/sh
# Synthesises a generated top level for Gowin with Yosys (yosys or yowasp-yosys) and prints the resources.
#   tools/synth.sh build/nbfm/nbfm_rx_top.f
set -e
fl="$1"; top=$(basename "$fl" .f); out=$(dirname "$fl")
Y=$(command -v yosys || command -v yowasp-yosys)
inc=$(grep '^+incdir+' "$fl" | sed 's/^+incdir+/-I/' | tr '\n' ' ')
files=$(grep -v '^+' "$fl" | tr '\n' ' ')
printf 'read_verilog %s %s\nsynth_gowin -top %s -json %s/%s_synth.json\ntee -o %s/%s_synth.txt stat\n' \
  "$inc" "$files" "$top" "$out" "$top" "$out" "$top" > "$out/${top}_synth.ys"
"$Y" -q -l "$out/${top}_synth.log" "$out/${top}_synth.ys" > /dev/null
awk '/^ +[0-9]+ +[A-Z]/ {n[$2]+=$1} END {
  for (k in n) { if (k ~ /^LUT/) l+=n[k]; else if (k ~ /^DFF/) f+=n[k]; else if (k ~ /^MULT/) m=m" "n[k]" "k; else if (k ~ /PX9|SP/) b+=n[k] }
  printf "LUT4 %d, ALU %d, FF %d, block RAM %d, multipliers:%s\n", l, n["ALU"], f, b, m }' "$out/${top}_synth.txt"
