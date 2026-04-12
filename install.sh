#!/usr/bin/env bash
# hermes-qwen-bridge installer
# Symlinks the plugin and skill into place, then optionally writes qwen settings.
# Safe to re-run — existing symlinks are updated, files are not overwritten unless --force.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
QWEN_HOME="${QWEN_HOME:-$HOME/.qwen}"

PLUGIN_SRC="$REPO_DIR/plugin"
SKILL_SRC="$REPO_DIR/skill/SKILL.md"
QWEN_SETTINGS_SRC="$REPO_DIR/config/qwen-settings.json"

PLUGIN_DEST="$HERMES_HOME/plugins/qwen-bridge"
SKILL_DEST="$HERMES_HOME/skills/software-development/qwen-code-delegation"
QWEN_SETTINGS_DEST="$QWEN_HOME/settings.json"

FORCE=false
for arg in "$@"; do
  [[ "$arg" == "--force" ]] && FORCE=true
done

ok()   { echo "  [ok] $*"; }
info() { echo "  [--] $*"; }
warn() { echo "  [!!] $*"; }

echo
echo "hermes-qwen-bridge installer"
echo "============================"
echo

# ── Plugin ────────────────────────────────────────────────────────────────
echo "1. Hermes plugin → $PLUGIN_DEST"
mkdir -p "$HERMES_HOME/plugins"
if [[ -L "$PLUGIN_DEST" ]]; then
  rm "$PLUGIN_DEST"
  ln -s "$PLUGIN_SRC" "$PLUGIN_DEST"
  ok "symlink updated"
elif [[ -d "$PLUGIN_DEST" ]]; then
  if $FORCE; then
    rm -rf "$PLUGIN_DEST"
    ln -s "$PLUGIN_SRC" "$PLUGIN_DEST"
    ok "replaced existing directory with symlink (--force)"
  else
    warn "$PLUGIN_DEST already exists as a directory. Use --force to replace."
  fi
else
  ln -s "$PLUGIN_SRC" "$PLUGIN_DEST"
  ok "symlink created"
fi

# ── Skill ─────────────────────────────────────────────────────────────────
echo "2. Hermes skill → $SKILL_DEST/SKILL.md"
mkdir -p "$SKILL_DEST"
if [[ -L "$SKILL_DEST/SKILL.md" ]]; then
  rm "$SKILL_DEST/SKILL.md"
  ln -s "$SKILL_SRC" "$SKILL_DEST/SKILL.md"
  ok "symlink updated"
elif [[ -f "$SKILL_DEST/SKILL.md" ]]; then
  if $FORCE; then
    rm "$SKILL_DEST/SKILL.md"
    ln -s "$SKILL_SRC" "$SKILL_DEST/SKILL.md"
    ok "replaced with symlink (--force)"
  else
    warn "$SKILL_DEST/SKILL.md already exists. Use --force to replace."
  fi
else
  ln -s "$SKILL_SRC" "$SKILL_DEST/SKILL.md"
  ok "symlink created"
fi

# ── Qwen settings ─────────────────────────────────────────────────────────
echo "3. Qwen Code settings → $QWEN_SETTINGS_DEST"
mkdir -p "$QWEN_HOME"
if [[ -f "$QWEN_SETTINGS_DEST" ]] && ! $FORCE; then
  info "~/.qwen/settings.json already exists — skipping (use --force to overwrite)"
  info "Reference config is at: $QWEN_SETTINGS_SRC"
else
  cp "$QWEN_SETTINGS_SRC" "$QWEN_SETTINGS_DEST"
  ok "written"
fi

# ── Hermes config: ensure qwen_bridge toolset is listed ───────────────────
echo "4. Hermes config.yaml — checking qwen_bridge toolset"
HERMES_CONFIG="$HERMES_HOME/config.yaml"
if [[ -f "$HERMES_CONFIG" ]]; then
  if grep -q "qwen_bridge" "$HERMES_CONFIG"; then
    ok "qwen_bridge already in config.yaml"
  else
    # Append after the first 'hermes-cli' toolset line
    sed -i '/- hermes-cli/a - qwen_bridge' "$HERMES_CONFIG"
    ok "qwen_bridge added to toolsets in config.yaml"
  fi
else
  warn "config.yaml not found at $HERMES_CONFIG — add 'qwen_bridge' to toolsets manually"
fi

# ── Check Qwen Code is installed ──────────────────────────────────────────
echo "5. Checking Qwen Code installation"
if command -v qwen &>/dev/null; then
  QWEN_VER=$(qwen --version 2>/dev/null || echo "unknown")
  ok "qwen found: $QWEN_VER"
else
  warn "qwen not found in PATH"
  info "Install with: npm install -g @qwen-code/qwen-code"
fi

echo
echo "Done. Restart Hermes to load the plugin."
echo
