#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

python3 "$ROOT/tools/handoff_to_lowering.py" \
          --report "$ROOT/research/report.md" \
          --program "$ROOT/research/program.md" \
          --knowledge-index "$ROOT/research/knowledge_index.tsv" \
          --research-config "$ROOT/research_config.json" \
          --lowering-template "$ROOT/lowering_config.json" \
          --output "$ROOT/lowering_config.json"

"$ROOT/materialize.sh" --force
