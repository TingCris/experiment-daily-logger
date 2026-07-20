#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$HOME/.agents/skills/experiment-daily-logger"
BIN_PATH="$HOME/.local/bin/exp-run"
HOOKS_PATH="$HOME/.codex/hooks.json"

rm -rf "$SKILL_DIR"
rm -f "$BIN_PATH"

echo "已删除："
echo "  $SKILL_DIR"
echo "  $BIN_PATH"
echo
echo "已有实验日志不会被删除。"
echo
echo "为避免误删其他 Hook，请手动编辑："
echo "  $HOOKS_PATH"
echo
echo "删除 command 中包含以下内容的 Hook 条目："
echo "  experiment-daily-logger/scripts/codex_hook.py"
