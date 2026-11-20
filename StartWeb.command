#!/bin/zsh
cd -- "$(dirname -- "$0")" || exit 1
rag_python=python3
[[ -x .venv/bin/python ]] && rag_python="$PWD/.venv/bin/python"
if ! "$rag_python" -c 'import pypdf' 2>/dev/null; then
    python3 -m venv .venv || exit 1
    rag_python="$PWD/.venv/bin/python"
    "$rag_python" -m pip install -r requirements.txt || exit 1
fi
exec "$rag_python" -m rag.web --open "$@"
