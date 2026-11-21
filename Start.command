#!/bin/zsh
cd -- "$(dirname -- "$0")" || exit 1
rag_python=python3
[[ -x .venv/bin/python ]] && rag_python="$PWD/.venv/bin/python"
rag_profile=${1:-offline}
"$rag_python" -m rag --profile "$rag_profile" nsbm-demo || exit $?
"$rag_python" -m rag --profile "$rag_profile" --db "runtime/nsbm-$rag_profile.sqlite3" chat
