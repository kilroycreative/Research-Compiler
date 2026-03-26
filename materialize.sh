#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
RESEARCH_OUT="$ROOT/research"
LOWERING_OUT="$ROOT/lowering-pass"
FACTORY_DIR="$ROOT/factory"

FORCE=0
if [[ "${1:-}" == "--force" ]]; then
  FORCE=1
elif [[ $# -gt 0 ]]; then
  echo "usage: ./materialize.sh [--force]" >&2
  exit 1
fi

if [[ $FORCE -eq 1 ]]; then
  rm -rf "$RESEARCH_OUT" "$LOWERING_OUT"
else
  for path in "$RESEARCH_OUT" "$LOWERING_OUT"; do
    if [[ -e "$path" ]]; then
      echo "refusing to overwrite $path; re-run with --force" >&2
      exit 1
    fi
  done
fi

python3 "$ROOT/tools/scaffold.py" \
          --config "$ROOT/research_config.json" \
          --output "$RESEARCH_OUT"

python3 "$ROOT/tools/lowering_scaffold.py" \
          --config "$ROOT/lowering_config.json" \
          --output "$LOWERING_OUT"

mkdir -p "$FACTORY_DIR"
if [[ ! -f "$FACTORY_DIR/README.md" ]]; then
  cat > "$FACTORY_DIR/README.md" <<'EOF'
# Factory

Use this folder for compiler-side notes, status files, or artifacts.

Primary inputs come from:
- ../lowering-pass/CLAUDE.md
- ../lowering-pass/DEBT.md
- ../lowering-pass/REVIEW_CHECKLIST.md
- ../lowering-pass/factory.yaml
EOF
fi

python3 "$ROOT/tools/compiler_bootstrap.py" \
          --config "$ROOT/lowering_config.json" \
          --factory-dir "$FACTORY_DIR"

python3 "$ROOT/tools/compiler_ticket_emitter.py" \
          --config "$ROOT/lowering_config.json" \
          --factory-dir "$FACTORY_DIR"

echo "Materialized run kit:"
echo "  research      -> $RESEARCH_OUT"
echo "  lowering-pass -> $LOWERING_OUT"
echo "  factory       -> $FACTORY_DIR"
