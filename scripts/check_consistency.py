#!/usr/bin/env python3
"""
Consistency gate — README and the skills must never drift apart.

Writing "keep the README updated" in a markdown file means "probably". This runs
inside build_public.sh and fails the build instead, so a drifted README can never
reach the public repo.

Checks, against the BUILT tree:
  1. every skill folder is listed in README.md
  2. README's per-suite counts match the real ones
  3. every skill has a Chinese display name registered in publish_clawhub.sh
  4. every skill's frontmatter has an ASCII-slug name matching its folder

Usage: python3 scripts/check_consistency.py <built tree>
"""

import re
import sys
from pathlib import Path

CONTENT = {"zmm", "zmm-topic", "zmm-benchmark", "zmm-script", "zmm-title", "zmm-hook", "zmm-review",
           "zmm-flow", "zmm-cut", "zmm-retro", "zmm-post", "zmm-mvp", "zmm-resonate",
           "zmm-concept", "zmm-skillify"}


def main(root: Path) -> int:
    problems = []

    skills = sorted(d.name for d in (root / "skills").iterdir()
                    if (d / "SKILL.md").is_file())
    if not skills:
        print("❌ 产出树里没有技能，check 无法进行")
        return 1

    readme = (root / "README.md").read_text(encoding="utf-8")

    # 1. every skill listed
    for slug in skills:
        if f"`{slug}`" not in readme:
            problems.append(f"README 没有列出技能 `{slug}`")

    # 2. counts match
    n_content = sum(1 for s in skills if s in CONTENT)
    n_biz = len(skills) - n_content
    for label, actual in (("内容操盘手", n_content), ("小老板看盘", n_biz)):
        m = re.search(rf"{label}（(\d+) 个技能）", readme)
        if not m:
            problems.append(f"README 找不到「{label}（N 个技能）」抬头")
        elif int(m.group(1)) != actual:
            problems.append(
                f"README 写「{label}（{m.group(1)} 个技能）」，实际 {actual} 个")

    # 3. display name registered
    pub = (root / "scripts" / "publish_clawhub.sh").read_text(encoding="utf-8")
    for slug in skills:
        if not re.search(rf"^\s*{re.escape(slug)}\)\s+echo", pub, re.M):
            problems.append(
                f"`{slug}` 在 publish_clawhub.sh 的 display_name() 里没有中文名")

    # 4. frontmatter name is the ASCII slug
    for slug in skills:
        text = (root / "skills" / slug / "SKILL.md").read_text(encoding="utf-8")
        m = re.search(r"^name:\s*(.+)$", text, re.M)
        if not m:
            problems.append(f"`{slug}/SKILL.md` 没有 name 字段")
        elif m.group(1).strip() != slug:
            problems.append(
                f"`{slug}/SKILL.md` 的 name 是 {m.group(1).strip()!r}，应为 {slug!r} —— "
                "非 ASCII slug 会让 skills.sh 把所有技能装进同一个 unnamed-skill 目录")

    if problems:
        print(f"\n❌ 一致性检查未通过（{len(problems)} 项）：")
        for p in problems:
            print(f"   · {p}")
        return 1

    print(f"✅ 一致性检查通过：{len(skills)} 个技能，README、中文名表、frontmatter 三处一致")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else ".")))
