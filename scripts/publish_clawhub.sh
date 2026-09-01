#!/usr/bin/env bash
# Publish every skill to ClawHub from a --clawhub build.
#
#   bash scripts/publish_clawhub.sh [构建目录] [--dry-run]
#
# Prerequisites:
#   1. `clawhub login`
#   2. clawhub CLI >= 0.23. Older builds (0.7.x) fail every publish with
#      "MIT-0 license terms must be accepted to publish skills" — that version
#      has no licence handling at all and just relays the server error. There is
#      nothing to click; upgrade with `npm i -g clawhub@latest`.
#
# Slugs stay English (npm-safe, and ClawHub requires it); the Chinese display
# name comes from --name. Version is read from each SKILL.md so this script
# never invents one.
#
# SkillHub needs nothing: it mirrors and auto-claims from ClawHub.

set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OWNER="${CLAWHUB_OWNER:-zmm}"          # publisher handle; skills appear as @zmm/<slug>
CHANGELOG="${CLAWHUB_CHANGELOG:-更新}"  # CI passes the commit message
BUILD="${1:-}"
DRY=0
for a in "$@"; do [ "$a" = "--dry-run" ] && DRY=1; done
[ "${BUILD:-}" = "--dry-run" ] && BUILD=""
BUILD="${BUILD:-$SRC/../zmm-clawhub}"

if [ ! -d "$BUILD" ]; then
  echo "❌ 构建目录不存在：$BUILD"
  echo "   先跑：bash scripts/build_public.sh $BUILD --clawhub"
  exit 1
fi

# ClawHub imposes MIT-0 and rejects conflicting terms. Only what sits INSIDE a
# skill folder is uploaded, so a repo-root LICENSE (CC BY-NC, for the GitHub
# copy) is fine — a LICENSE inside a skill folder is not.
for lic in "$BUILD"/skills/*/LICENSE "$BUILD"/skills/*/LICENSE.*; do
  [ -e "$lic" ] || continue
  echo "❌ 技能文件夹内有 LICENSE：$lic"
  echo "   ClawHub 统一 MIT-0 且拒绝冲突条款，停止。"
  exit 1
done


# ClawHub display names. Deliberately NOT read from SKILL.md: `name` there must
# stay an ASCII slug, because skills.sh derives the install directory from it and
# a Chinese value slugifies to nothing — all 20 skills then land in one
# `unnamed-skill` folder and overwrite each other (measured 2026-09-01).
# So the Chinese brand name lives here and is passed with --name at publish time.
display_name() {
  case "$1" in
    zmm)                echo "詹明明" ;;
    zmm-topic)          echo "詹明明·今天拍什么" ;;
    zmm-script)         echo "詹明明·口播稿写作" ;;
    zmm-title)          echo "詹明明·标题与封面" ;;
    zmm-hook)           echo "詹明明·开头前五秒" ;;
    zmm-review)         echo "詹明明·发布前审一遍" ;;
    zmm-flow)           echo "詹明明·哪里会被划走" ;;
    zmm-cut)            echo "詹明明·口播剪辑" ;;
    zmm-retro)          echo "詹明明·发布后复盘" ;;
    zmm-post)           echo "詹明明·公众号短文" ;;
    zmm-mvp)            echo "詹明明·选题先试水" ;;
    zmm-resonate)       echo "詹明明·戳不戳得中人" ;;
    zmm-concept)        echo "詹明明·重讲一个概念" ;;
    zmm-product)        echo "詹明明·我该卖什么" ;;
    zmm-portfolio)      echo "詹明明·该投哪条线" ;;
    zmm-revenue)        echo "詹明明·这个月钱去哪了" ;;
    zmm-concentration)  echo "詹明明·大客户会不会跑" ;;
    zmm-dependency)     echo "詹明明·这生意靠谁" ;;
    zmm-decide)         echo "詹明明·拿不准的时候" ;;
    zmm-track)          echo "詹明明·有什么到期了" ;;
    *)                  echo "" ;;   # unknown slug: caller reports and skips
  esac
}

ok=0; fail=0; failed=()

for d in "$BUILD"/skills/zmm*/; do
  [ -f "$d/SKILL.md" ] || continue
  slug="$(basename "${d%/}")"
  name="$(display_name "$slug")"
  ver="$(awk 'NR>1 && /^---$/{exit} /^version:/{sub(/^version: */,""); print; exit}' "$d/SKILL.md")"
  # `ver` is only shown in the log; ClawHub picks the published version itself.

  if [ -z "$name" ] || [ -z "$ver" ]; then
    echo "⚠️  $slug 没有登记中文名或缺 version，跳过（请在 display_name() 里补一行）"
    fail=$((fail + 1)); failed+=("$slug (缺字段)")
    continue
  fi

  printf '%-20s → %-14s ' "$slug" "$name"

  if [ "$DRY" = "1" ]; then
    echo "[dry-run] → @$OWNER/$slug"
    ok=$((ok + 1))
    continue
  fi

  # No --version on purpose. ClawHub defaults to the next patch and reports
  # `unchanged` when a skill's files did not move, so an ordinary push republishes
  # only what actually changed. Pinning the frontmatter version instead made every
  # run skip all 20 with "该版本已发过" — the pipeline was green and did nothing
  # (measured 2026-09-01, run 33473489467).
  if clawhub skill publish "$d" \
      --slug "$slug" --name "$name" --owner "$OWNER" \
      --changelog "$CHANGELOG" --tags latest >/tmp/clawhub_publish.log 2>&1; then
    echo "✅"
    ok=$((ok + 1))
  else
    if grep -qi "unchanged\|already exists\|no changes" /tmp/clawhub_publish.log; then
      echo "⏭  内容未变"
      ok=$((ok + 1))
    else
      echo "❌"
      sed 's/^/      /' /tmp/clawhub_publish.log | tail -3
      fail=$((fail + 1)); failed+=("$slug")
    fi
  fi
done

echo
echo "成功 $ok · 失败 $fail"
if [ "$fail" -gt 0 ]; then
  printf '  失败：%s\n' "${failed[@]}"
  exit 1
fi
