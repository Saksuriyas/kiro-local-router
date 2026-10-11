#!/usr/bin/env bash
# Installs kiro-localllm into a local venv and copies the two Kiro CLI agents.
# Usage:
#   ./install.sh                     # agents -> ~/.kiro/agents (global)
#   ./install.sh --workspace DIR     # agents -> DIR/.kiro/agents (project-local, shareable via git)
#   ./install.sh --no-agents         # only set up the venv
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$HOME/.kiro/agents"
INSTALL_AGENTS=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace) AGENT_DIR="$(cd "$2" && pwd)/.kiro/agents"; shift 2 ;;
    --no-agents) INSTALL_AGENTS=0; shift ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

PYTHON="${PYTHON:-python3}"
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' \
  || { echo "Python 3.10+ is required (set PYTHON=/path/to/python3.x)" >&2; exit 1; }

echo "==> Creating venv and installing kiro-localllm"
"$PYTHON" -m venv "$PROJECT_DIR/.venv"
"$PROJECT_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$PROJECT_DIR/.venv/bin/pip" install --quiet -e "$PROJECT_DIR"

[[ -f "$PROJECT_DIR/.env" ]] || { cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"; echo "==> Created .env (edit it to change model/provider)"; }

BIN="$PROJECT_DIR/.venv/bin/kiro-localllm"
[[ -x "$BIN" ]] || { echo "Install failed: $BIN not found" >&2; exit 1; }

if [[ "$INSTALL_AGENTS" == 1 ]]; then
  mkdir -p "$AGENT_DIR"
  for tpl in "$PROJECT_DIR"/agents/*.json.template; do
    name="$(basename "$tpl" .template)"
    sed "s|__KIRO_LOCALLM_BIN__|$BIN|g" "$tpl" > "$AGENT_DIR/$name"
    echo "==> Installed agent: $AGENT_DIR/$name"
  done
fi

cat <<MSG

Done. Next steps:
  1. Make sure Ollama is running and a model is pulled (see README.md, section 2)
  2. $PROJECT_DIR/.venv/bin/python $PROJECT_DIR/scripts/smoke_test.py
  3. cd <your project> && kiro-cli chat --agent docs-writer
MSG
