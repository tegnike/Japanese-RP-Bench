#!/bin/zsh

# Continue the OpenCode Go benchmark independently of a Codex terminal session.
# Long-lived credentials stay in the macOS login keychain rather than this repo.

set -u

repo_root="/Users/user/WorkSpace/Japanese-RP-Bench"
output_root="$repo_root/tmp/benchmark-opencode-go-20260721"
run_log="$output_root.log"
config="$repo_root/configs/benchmark_opencode_go_candidates.yaml"
python_bin="/usr/local/bin/python3.12"

cd "$repo_root" || exit 1

export ANTHROPIC_API_KEY="$(/usr/bin/security find-generic-password -w -a Japanese-RP-Bench -s Japanese-RP-Bench-Anthropic)"
export OPENCODE_GO_API_KEY="$(/usr/bin/security find-generic-password -w -a Japanese-RP-Bench -s Japanese-RP-Bench-OpenCode-Go)"
export OPENAI_API_KEY="$(/usr/bin/security find-generic-password -w -a Japanese-RP-Bench -s Japanese-RP-Bench-OpenAI)"
export GEMINI_API_KEY="$(/usr/bin/security find-generic-password -w -a Japanese-RP-Bench -s Japanese-RP-Bench-Gemini)"

if [[ -z "${OPENAI_API_KEY:-}" || -z "$GEMINI_API_KEY" || -z "$ANTHROPIC_API_KEY" || -z "$OPENCODE_GO_API_KEY" ]]; then
  print -u2 -- "benchmark credential setup is incomplete"
  exit 1
fi

while true; do
  print -- "$(date -Iseconds) starting or resuming benchmark" >> "$run_log"
  PYTHONPATH=src "$python_bin" -m japanese_rp_bench.v2.cli run \
    --config "$config" \
    --output "$output_root" \
    --workers 2 >> "$run_log" 2>&1

  if "$python_bin" -c 'import json; from pathlib import Path; p=Path("tmp/benchmark-opencode-go-20260721/manifest.json"); raise SystemExit(0 if p.exists() and json.loads(p.read_text()).get("status") in {"complete", "partial"} else 1)'; then
    print -- "$(date -Iseconds) benchmark reached terminal status" >> "$run_log"
    exit 0
  fi

  if tail -n 6 "$run_log" | grep -q 'Provider rate limit exceeded'; then
    print -- "$(date -Iseconds) transient provider rate limit; retrying in 90 seconds" >> "$run_log"
    sleep 90
  else
    print -- "$(date -Iseconds) benchmark stopped; automatic retry disabled" >> "$run_log"
    exit 1
  fi
done
