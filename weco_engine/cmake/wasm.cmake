# §5.1 — Emscripten/WebAssembly build toolchain for browser demo
#
# Build:
#   emcmake cmake -B build_wasm -S . -DCMAKE_TOOLCHAIN_FILE=cmake/wasm.cmake
#   cmake --build build_wasm
#
# This produces weco_wasm.js + weco_wasm.wasm for browser use.

set(CMAKE_SYSTEM_NAME Emscripten)
set(WASM_BUILD ON)

# Emscripten flags
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -s WASM=1")
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -s WASM=1 -s ALLOW_MEMORY_GROWTH=1")

# Export DTW functions for JS
set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} \
    -s EXPORTED_FUNCTIONS='[\"_weco_correlate\",\"_weco_init\",\"_weco_free\",\"_malloc\",\"_free\"]' \
    -s EXPORTED_RUNTIME_METHODS='[\"ccall\",\"cwrap\",\"getValue\",\"setValue\"]' \
    -s MODULARIZE=1 \
    -s EXPORT_NAME='WeCoWasm' \
    -s ALLOW_MEMORY_GROWTH=1 \
")
