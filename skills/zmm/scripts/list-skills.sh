#!/usr/bin/env bash
# 列出本机已安装的 zmm 家族 skill：名字 + description 第一行 + 真源路径。
# 只读，不改任何东西。给 /zmm 模式 A 做候选发现用。
set -uo pipefail

# 优先按已安装位置找（宿主实际加载的就是这里），找不到再回退到仓库
ROOTS=("$HOME/.claude/skills" "$HOME/.agents/skills" "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)")

found=0
for root in "${ROOTS[@]}"; do
  [ -d "$root" ] || continue
  for d in "$root"/zmm*/; do
    [ -f "$d/SKILL.md" ] || continue
    name=$(basename "${d%/}")
    [ "$name" = "zmm" ] && continue          # 排除入口自己
    real=$(cd "$d" && pwd -P)
    # description: frontmatter 里 description 之后、下一个顶格 key 之前的首个非空行
    desc=$(awk '/^description:/{f=1;sub(/^description:[[:space:]]*\|?[[:space:]]*/,"");if($0!="")
{print;exit}next} f&&/^[a-zA-Z_-]+:/{exit} f&&NF{print;exit}' "$d/SKILL.md")
    printf '%-20s %s\n' "$name" "${desc:-（无 description）}"
    printf '%-20s   ↳ %s\n' "" "$real"
    found=$((found+1))
  done
  [ "$found" -gt 0 ] && break
done

if [ "$found" -eq 0 ]; then
  echo "（没有发现任何已安装的 zmm 家族 skill）" >&2
  exit 1
fi
echo
echo "共 $found 个"
