#!/usr/bin/env bash
set -Eeuo pipefail
export OBSIDIAN_VAULT_PATH="${OBSIDIAN_VAULT_PATH:-$HOME/obsidian}"
export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
exec "$HOME/.hermes/obsidian-backup-env/bin/python" "$HOME/.hermes/scripts/obsidian_backup.py" --quiet
