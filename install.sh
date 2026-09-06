#!/usr/bin/env bash
# One-command install. Links every skill into the agent's skills directory.
#
#   bash install.sh            # auto-detect (Claude Code by default)
#   bash install.sh <目录>      # install into a specific skills directory
#
# Safe to re-run: existing links are replaced, nothing else is touched.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Known skills directories for the agents that support this layout.
CANDIDATES=(
  "$HOME/.claude/skills"
  "$HOME/.agents/skills"
  "$HOME/.codex/skills"
  "$HOME/.workbuddy/skills"
)

TARGET="${1:-}"
if [ -z "$TARGET" ]; then
  for d in "${CANDIDATES[@]}"; do
    if [ -d "$d" ]; then TARGET="$d"; break; fi
  done
fi

if [ -z "$TARGET" ]; then
  echo "没找到技能目录。请把目录作为参数传进来，例如："
  echo "  bash install.sh ~/.claude/skills"
  echo
  echo "不知道你的工具用哪个目录？直接问它：「你的本地技能目录在哪？」"
  exit 1
fi

mkdir -p "$TARGET"

n=0
# Skills live under skills/ so skills.sh can discover this repo.
for d in "$REPO"/skills/zmm*/; do
  [ -f "$d/SKILL.md" ] || continue
  name="$(basename "$d")"
  ln -sfn "${d%/}" "$TARGET/$name"
  n=$((n + 1))
done

echo "✅ 已安装 $n 个技能到：$TARGET"
echo

if [ ! -f "$REPO/config.yaml" ]; then
  cp "$REPO/config.example.yaml" "$REPO/config.yaml"
  echo "📝 已生成配置文件：$REPO/config.yaml"
  echo "   打开它按注释填。不知道怎么填就对 AI 说：「帮我填 config.yaml，一项一项问我。」"
  echo
fi

echo "下一步：重启你的 AI 工具，然后输入  /新手上路"
