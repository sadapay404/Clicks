#!/usr/bin/env bash
# Run the Clicks-Auto test suite inside a bare container (no X, no GPU, no
# system GL/dbus/xkb libraries).
#
# Qt links against libGL, libEGL, libxkbcommon and libdbus even when it runs
# with the "offscreen" platform plugin.  On stripped-down images those shared
# objects are missing, which makes `import PyQt6.QtWidgets` fail before a single
# test runs.  This script builds tiny stub libraries with the exact symbol
# versions Qt asks for, puts them on LD_LIBRARY_PATH and then runs pytest with
# QT_QPA_PLATFORM=offscreen.
#
# Usage:
#     bash scripts/dev_headless_qt.sh              # full suite
#     bash scripts/dev_headless_qt.sh tests/test_gui_smoke.py -x
#
# Everything it creates lives outside the repository (in $TMPDIR), so it never
# pollutes the working tree.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STUB_DIR="${CLICKS_QT_STUBS:-${TMPDIR:-/tmp}/clicks-qt-stubs}"
PY="${ROOT}/.venv/bin/python"
VENV_DIR="${ROOT}/.venv"

cd "${ROOT}"

# --------------------------------------------------------------------- venv
if [[ ! -x "${PY}" ]]; then
    echo "==> creating ${VENV_DIR}"
    python3 -m venv "${VENV_DIR}"
    "${VENV_DIR}/bin/pip" install --quiet --upgrade pip
    "${VENV_DIR}/bin/pip" install --quiet -r requirements-dev.txt
fi
PY="${VENV_DIR}/bin/python"
QT_LIB="$("${PY}" -c 'import PyQt6, pathlib; print(pathlib.Path(PyQt6.__file__).parent / "Qt6")')"

# --------------------------------------------------------------------- stubs
build_stubs() {
    mkdir -p "${STUB_DIR}"
    local work
    work="$(mktemp -d)"

    # every symbol Qt wants from the missing libraries
    local libs=()
    while IFS= read -r lib; do libs+=("${lib}"); done < <(find "${QT_LIB}/lib" "${QT_LIB}/plugins/platforms" -name '*.so*')
    nm -D --undefined-only "${libs[@]}" 2>/dev/null \
        | awk '{print $NF}' | sed 's/@.*//' | sort -u > "${work}/symbols.txt"

    make_stub() {   # make_stub <soname> <version-script-file> <symbol-regex>
        local soname="$1"
        local map="$2"
        local pattern="$3"
        local cfile="${work}/${soname}.c"
        local -a mapflag=()
        if [[ -n "${map}" ]]; then
            mapflag=(-Wl,--version-script="${map}")
        fi
        : > "${cfile}"
        echo '#include <stddef.h>' >> "${cfile}"
        grep -E "${pattern}" "${work}/symbols.txt" | while read -r sym; do
            printf 'void %s(void) { }\n' "${sym}" >> "${cfile}"
        done
        gcc -shared -fPIC -o "${STUB_DIR}/${soname}" "${cfile}" \
            -Wl,-soname,"${soname}" "${mapflag[@]}"
    }

    printf 'V_0.5.0 {\n  global: *;\n};\n' > "${work}/xkb.map"
    printf 'LIBDBUS_1_3 {\n  global: *;\n};\n' > "${work}/dbus.map"
    make_stub libGL.so.1            ""           '^gl'
    make_stub libEGL.so.1           ""           '^egl'
    make_stub libxkbcommon.so.0     "${work}/xkb.map"  '^xkb'
    make_stub libdbus-1.so.3        "${work}/dbus.map" '^dbus_'
    rm -rf "${work}"
}

needs_stubs=0
for lib in libGL.so.1 libEGL.so.1 libxkbcommon.so.0 libdbus-1.so.3; do
    if ! LD_LIBRARY_PATH="${QT_LIB}/lib" "${PY}" -c "import ctypes; ctypes.CDLL('${lib}')" 2>/dev/null; then
        needs_stubs=1
    fi
done
if [[ "${needs_stubs}" == "1" ]]; then
    echo "==> building stub libraries in ${STUB_DIR}"
    build_stubs
fi

# ---------------------------------------------------------------------- run
export LD_LIBRARY_PATH="${QT_LIB}/lib:${STUB_DIR}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
export QT_LOGGING_RULES="${QT_LOGGING_RULES:-*.debug=false}"

if [[ $# -eq 0 ]]; then
    set -- tests/
fi
echo "==> pytest $*"
exec "${PY}" -m pytest -q --timeout=600 "$@"
