#!/bin/zsh
cd -- "$(dirname -- "$0")" || exit 1
mkdir -p runtime/swift-cache
swiftc -module-cache-path "$PWD/runtime/swift-cache" rag/apple_embeddings.swift -o runtime/apple-embeddings || exit $?
printf '%s' '["Test the university policy embedding"]' | runtime/apple-embeddings > /dev/null || exit $?
echo "English sentence embeddings are ready. Run ./Start.command semantic."
