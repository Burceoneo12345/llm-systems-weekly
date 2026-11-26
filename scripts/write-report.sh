#!/usr/bin/env bash
set -euo pipefail

runtime="$RUNNER_TEMP/weekly-llama"
weights="$HOME/.cache/weekly-qwen3-8b/Qwen3-8B-Q4_K_M.gguf"
mkdir -p "$runtime" "$(dirname "$weights")"
if [[ ! -f "$weights" ]]; then
  curl -fL --retry 4 --retry-all-errors --connect-timeout 20 -o "$weights.part" \
    "https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/7c41481f57cb95916b40956ab2f0b139b296d974/Qwen3-8B-Q4_K_M.gguf?download=true&run=$GITHUB_RUN_ID"
  mv "$weights.part" "$weights"
fi
echo "d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785  $weights" | sha256sum --check --status
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
