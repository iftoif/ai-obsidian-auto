#!/usr/bin/env bash
# Chroma 语义索引重建 service 入口
set -Eeuo pipefail
export OBSIDIAN_VAULT_PATH="${OBSIDIAN_VAULT_PATH:-$HOME/obsidian}"
export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
exec "$HERMES_HOME/obsidian-backup-env/bin/python" "$HERMES_HOME/scripts/wiki_chroma_rebuild.py" --vault "$OBSIDIAN_VAULT_PATH" --quiet
