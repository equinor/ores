#!/usr/bin/env bash
# =============================================================================
# WeCo - Multiple Well Correlation
# Complete run script for setup, build, test, and execution
# =============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${WECO_VENV:-$HOME/.venv}"
PYTHON="${VENV_DIR}/bin/python"
PIP="${VENV_DIR}/bin/pip"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail()  { echo -e "${RED}[FAIL]${NC} $*"; }

usage() {
    cat <<EOF
WeCo Run Script - v0.9.31

Usage: $(basename "$0") <command> [options]

Commands:
  setup       Create/activate venv and install WeCo + dependencies
  build       Build WeCo C++ engine and install (editable mode)
  rebuild     Clean build artifacts and rebuild from scratch
  test        Run the pytest test suite
  check       Run WeCoCheck to verify installation
  studio      Launch WeCo Studio (default GUI)
  run         Run WeCoRun with given option and well files
  resview     Launch the WeCoResView result viewer
  demo        Run auto_run_examples (batch demo runner)
  stubs       Regenerate engine.pyi stubs
  doc         Build Python docs (Sphinx)
  cppdoc      Build C++ docs (Doxygen)
  info        Show installation info and available commands
  clean       Remove build artifacts

Environment variables:
  WECO_VENV   Path to virtual environment (default: ~/.venv)

Examples:
  $(basename "$0") setup                        # First-time setup
  $(basename "$0") studio                       # Launch WeCo Studio
  $(basename "$0") run option.txt wells.txt     # Run correlation
  $(basename "$0") demo                         # Run batch demos
  $(basename "$0") test                         # Run test suite
EOF
}

# -----------------------------------------------------------------------------
# Commands
# -----------------------------------------------------------------------------

cmd_setup() {
    info "Setting up WeCo environment..."

    # Check venv exists
    if [ ! -d "$VENV_DIR" ]; then
        info "Creating virtual environment at $VENV_DIR ..."
        python3 -m venv "$VENV_DIR"
    fi
    ok "Virtual environment: $VENV_DIR"

    # Activate
    source "${VENV_DIR}/bin/activate"

    # Install build deps
    info "Installing build dependencies..."
    pip install -q scikit-build-core pybind11

    # Install WeCo in editable mode
    info "Building and installing WeCo (editable mode)..."
    cd "$SCRIPT_DIR"
    pip install --no-build-isolation -e . 2>&1 | grep -E "^(Successfully|ERROR|Building)" || true

    # Install test deps
    pip install -q pytest

    ok "WeCo v$("${VENV_DIR}/bin/python" -c 'from weco.engine import get_version; print(get_version())') installed successfully!"
    echo ""
    info "Activate the environment with:"
    echo "  source ${VENV_DIR}/bin/activate"
    echo ""
    info "Then run: $(basename "$0") check"
}

cmd_build() {
    source "${VENV_DIR}/bin/activate"
    info "Building WeCo..."
    cd "$SCRIPT_DIR"
    pip install --no-build-isolation -e . 2>&1 | grep -E "^(Successfully|ERROR|Building)" || true
    ok "Build complete."
}

cmd_rebuild() {
    source "${VENV_DIR}/bin/activate"
    info "Cleaning build artifacts..."
    rm -rf "${SCRIPT_DIR}/.python_build" "${SCRIPT_DIR}/build" "${SCRIPT_DIR}/*.egg-info"
    info "Rebuilding WeCo..."
    cd "$SCRIPT_DIR"
    pip install --no-build-isolation -e . 2>&1 | tail -5
    ok "Rebuild complete."
}

cmd_test() {
    source "${VENV_DIR}/bin/activate"
    info "Running WeCo test suite..."
    cd "$SCRIPT_DIR"
    "$PYTHON" -m pytest pytest/ -v "$@"
}

cmd_check() {
    source "${VENV_DIR}/bin/activate"
    info "Running WeCoCheck..."
    WeCoCheck -g -v
    ok "Installation check complete."
}

cmd_run() {
    source "${VENV_DIR}/bin/activate"
    if [ $# -lt 2 ]; then
        fail "Usage: $(basename "$0") run <options_file> <wells_file> [extra_args...]"
        echo "  Example: $(basename "$0") run option.txt wells.txt"
        exit 1
    fi
    info "Running WeCoRun: $*"
    WeCoRun "$@"
}

cmd_gui() {
    source "${VENV_DIR}/bin/activate"
    info "Launching WeCo Studio..."
    WeCoStudio "$@"
}

cmd_studio() {
    cmd_gui "$@"
}

cmd_resview() {
    source "${VENV_DIR}/bin/activate"
    info "Launching WeCoResView..."
    WeCoResView "$@"
}

cmd_demo() {
    source "${VENV_DIR}/bin/activate"
    info "Running batch demos..."
    "$PYTHON" "${SCRIPT_DIR}/bin/auto_run_examples.py" "$@"
}

cmd_stubs() {
    source "${VENV_DIR}/bin/activate"
    info "Regenerating engine.pyi stubs..."
    cd "$SCRIPT_DIR"
    pybind11-stubgen -o . weco.engine
    ok "Stubs regenerated."
}

cmd_doc() {
    source "${VENV_DIR}/bin/activate"
    info "Building Python documentation (Sphinx)..."
    cd "$SCRIPT_DIR"
    local version
    version=$(cat VERSION)
    local file="WeCo-${version}-doc.zip"
    mkdir -p dist
    sphinx-build doc_src doc/python
    cd doc && zip "${file}" -r python && mv "${file}" ../dist/
    ok "Documentation built → dist/${file}"
}

cmd_cppdoc() {
    info "Building C++ documentation (Doxygen)..."
    cd "$SCRIPT_DIR"
    if [ ! -d .doc_build ]; then
        mkdir .doc_build
        cd .doc_build
        cmake .. -DGEN_CPP_DOC=ON
        cd ..
    fi
    cd .doc_build && make doc
    ok "C++ docs built."
}

cmd_info() {
    source "${VENV_DIR}/bin/activate"
    echo "============================================"
    echo "  WeCo - Multiple Well Correlation"
    echo "============================================"
    echo ""
    echo "Version:       $("$PYTHON" -c 'from weco.engine import get_version; print(get_version())' 2>/dev/null || echo 'not installed')"
    echo "Python:        $("$PYTHON" --version 2>&1)"
    echo "Venv:          ${VENV_DIR}"
    echo "Project dir:   ${SCRIPT_DIR}"
    echo ""
    echo "Installed commands (via PATH after activating venv):"
    echo "  WeCoStudio       - WeCo Studio GUI (main application)"
    echo "  WeCoRun          - Command-line correlation engine"
    echo "  WeCoResView      - Result viewer"
    echo "  WeCoRes2Las      - Convert results to LAS format"
    echo "  WeCoRes2Csv      - Convert results to CSV format"
    echo "  WeCoCheck        - Check installation"
    echo "  WeCoAddRegion    - Add region to well file"
    echo "  WeCoConvert      - Format converter"
    echo ""
    echo "Scripts (in bin/):"
    echo "  auto_run_examples.py  - Batch demo runner with plots"
    echo "  demo_gui.py           - Interactive demo runner"
    echo "  demo_rddms.py         - OSDU/RDDMS live demo"
    echo "  gocad_extract.py      - GOCAD .wl → WeCo converter"
    echo ""
    echo "Data sets:     ${SCRIPT_DIR}/data/"
    echo "Examples:      ${SCRIPT_DIR}/examples/"
    echo "Output:        ${SCRIPT_DIR}/tmp/"
    echo "Documentation: ${SCRIPT_DIR}/doc/"
}

cmd_clean() {
    info "Cleaning build artifacts..."
    rm -rf "${SCRIPT_DIR}/.python_build"
    rm -rf "${SCRIPT_DIR}/build"
    rm -rf "${SCRIPT_DIR}"/*.egg-info
    rm -rf "${SCRIPT_DIR}/.pytest_cache"
    rm -rf "${SCRIPT_DIR}/weco/__pycache__"
    find "${SCRIPT_DIR}" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
    ok "Clean complete."
}

# -----------------------------------------------------------------------------
# Main dispatch
# -----------------------------------------------------------------------------

if [ $# -eq 0 ]; then
    usage
    exit 0
fi

COMMAND="$1"
shift

case "$COMMAND" in
    setup)    cmd_setup "$@" ;;
    build)    cmd_build "$@" ;;
    rebuild)  cmd_rebuild "$@" ;;
    test)     cmd_test "$@" ;;
    check)    cmd_check "$@" ;;
    run)      cmd_run "$@" ;;
    gui|studio) cmd_studio "$@" ;;
    resview)  cmd_resview "$@" ;;
    demo)     cmd_demo "$@" ;;
    stubs)    cmd_stubs "$@" ;;
    doc)      cmd_doc "$@" ;;
    cppdoc)   cmd_cppdoc "$@" ;;
    info)     cmd_info "$@" ;;
    clean)    cmd_clean "$@" ;;
    help|-h|--help) usage ;;
    *)
        fail "Unknown command: $COMMAND"
        echo ""
        usage
        exit 1
        ;;
esac
