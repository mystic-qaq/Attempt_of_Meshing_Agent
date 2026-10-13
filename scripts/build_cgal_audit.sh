#!/bin/bash
set -eu
deps=$1
numeric_prefix=$2
output=$3
script_root=$(cd -- "$(dirname -- "$0")/.." && pwd)
test ! -e "$output"
g++ -std=c++17 -O2 -pthread -DCGAL_HEADER_ONLY \
  -I"$deps/CGAL-5.6.2/include" -I"$deps/boost_1_84_0" -I"$numeric_prefix/include" \
  "$script_root/native_tools/cgal_surface_audit.cpp" -L"$numeric_prefix/lib" \
  -Wl,-rpath,"$numeric_prefix/lib" -lmpfr -lgmp -o "$output"
sha256sum "$output" "$script_root/native_tools/cgal_surface_audit.cpp"
