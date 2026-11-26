#!/usr/bin/env bash
set -euo pipefail

runtime="$RUNNER_TEMP/weekly-llama"
weights="$HOME/.cache/weekly-qwen3/Qwen3-4B-Q4_K_M.gguf"
mkdir -p "$runtime" "$(dirname "$weights")"
if [[ ! -f "$weights" ]]; then
  curl -fL --retry 4 --retry-all-errors --connect-timeout 20 -o "$weights.part" \
    "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/bc640142c66e1fdd12af0bd68f40445458f3869b/Qwen3-4B-Q4_K_M.gguf?download=true&run=$GITHUB_RUN_ID"
  mv "$weights.part" "$weights"
fi
echo "7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5  $weights" | sha256sum --check --status
curl -fsSL --retry 4 --retry-all-errors -o "$runtime/llama.tar.gz" \
  https://github.com/ggml-org/llama.cpp/releases/download/b12757/llama-b12757-bin-ubuntu-x64.tar.gz
echo "99e34cc6a39f3afda735d43d76d15d6ead2297406cc9c0cf421b771fd3a1a84a  $runtime/llama.tar.gz" | sha256sum --check --status
tar -xzf "$runtime/llama.tar.gz" -C "$runtime" --strip-components=1
"$runtime/llama-server" -m "$weights" --alias weekly-editor --host 127.0.0.1 --port 8089 \
  -ngl 0 -c 8192 -t "$(nproc)" -np 1 --jinja >"$runtime/server.log" 2>&1 &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT
for _ in {1..90}; do
  if ! kill -0 "$server_pid" 2>/dev/null; then tail -40 "$runtime/server.log"; exit 1; fi
  if curl -fsS http://127.0.0.1:8089/health >/dev/null 2>&1; then
    python3 scripts/digest.py write "$1"
    exit 0
  fi
  sleep 2
done
tail -40 "$runtime/server.log"
exit 1
