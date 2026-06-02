#!/usr/bin/env bash
set -e

echo ""
echo "  installing xcoding…"

PY=""
for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
    echo "  Python not found. Install python3 first (e.g. 'sudo apt install python3 python3-pip')." >&2
    exit 1
fi

if "$PY" -m pip install --upgrade --user xcoding 2>/dev/null; then
    :
elif "$PY" -m pip install --upgrade --user --break-system-packages xcoding 2>/dev/null; then
    :
elif command -v pipx >/dev/null 2>&1; then
    pipx install xcoding || pipx upgrade xcoding
else
    "$PY" -m pip install --upgrade xcoding
fi

BIN="$("$PY" -c 'import sysconfig; print(sysconfig.get_path("scripts", scheme="posix_user"))' 2>/dev/null || true)"
[ -z "$BIN" ] && BIN="$HOME/.local/bin"

case ":$PATH:" in
    *":$BIN:"*) ;;
    *)
        for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
            if [ -f "$rc" ] && ! grep -q "xcoding installer PATH" "$rc" 2>/dev/null; then
                {
                    echo ""
                    echo "# xcoding installer PATH"
                    echo "export PATH=\"\$PATH:$BIN\""
                } >> "$rc"
            fi
        done
        export PATH="$PATH:$BIN"
        echo "  added to PATH: $BIN"
        ;;
esac

echo ""
echo "  done. type 'xcode' or 'xcoding' to start."
echo "  (if not found, open a NEW terminal, or run: $PY -m xcode)"
echo ""
