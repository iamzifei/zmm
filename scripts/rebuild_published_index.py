#!/usr/bin/env python3
"""
Rebuild the published-content index from the published folders themselves.

The manual index (config.paths.published_index, default `_已发布/已发布内容库.md`)
is the dedup gate every topic must pass before production. It is filled by hand
after each publish, and "after each publish" is exactly when nobody remembers —
one script went unregistered for four days, during which the gate was blind to
it. This script makes the folders the source of truth and the table a product:

  1. Walk `<drafts>/已发布/*/` (one folder per published piece, named
     `YYYYMMDD-<id>-<short title>`), read the loose frontmatter of 稿件.md and
     发布记录.md, and pull out: date, id, platform, title, core conclusion,
     main analogy.
  2. Write `<published_index stem>.自动.md` next to the manual index — a table
     the dedup step can read in addition to the manual one.
  3. Diff against the manual index: folders not mentioned there are reported as
     未登记 (exit 1), and manual rows whose folder no longer exists as 指不到.

The frontmatter in these files is not strict YAML (multi-line values, emoji,
bold). The parser here is deliberately tolerant: `key: value` lines, with any
indented following lines joined onto the value.

Usage:
    python3 scripts/rebuild_published_index.py            # config.yaml
    python3 scripts/rebuild_published_index.py --config other.yaml
    python3 scripts/rebuild_published_index.py --dry-run  # report only, write nothing
"""

import argparse
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from check_paths import load_paths  # noqa: E402  (same tolerant config reader)

FOLDER = re.compile(r"^(?P<date>\d{8})-(?P<id>[^-]+)-(?P<title>.+)$")

# Which frontmatter keys feed which column, in order of preference.
FIELDS = {
    "conclusion": ["核心结论", "核心主张", "落点句", "落点"],
    "analogy": ["主类比"],
    "title": ["作品标题", "标题"],
    "platform": ["平台"],
    "published": ["发布", "发布日期"],
    "id": ["编号"],
}


def frontmatter(path: Path) -> dict:
    """Tolerant key/value read of the first --- block."""
    if not path.is_file():
        return {}
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if not lines or not lines[0].startswith("---"):
        return {}
    out, key = {}, None
    for line in lines[1:]:
        if line.startswith("---"):
            break
        m = re.match(r"^([^\s:：][^:：]{0,30})[:：]\s*(.*)$", line)
        if m and not line.startswith((" ", "\t")):
            key = m.group(1).strip()
            out[key] = m.group(2).strip()
        elif key and line.strip():
            out[key] += " " + line.strip()
    return out


def clean(v: str, limit: int = 160) -> str:
    v = re.sub(r"[*★✅🟢🔴⚠️📊]+", "", v)
    v = re.sub(r"\s+", " ", v).strip(" ·—-")
    return v[:limit] + ("…" if len(v) > limit else "")


def platform_from_status(status: str) -> str:
    """`状态: ✅ 已发布 2026-08-24（抖音）` — the platform often only lives here."""
    found = [p for p in ("抖音", "视频号", "小红书", "B站", "X") if p in status]
    return " / ".join(found)


def pick(fm_list, keys):
    for fm in fm_list:
        for k in keys:
            if fm.get(k):
                return fm[k]
    return ""


def collect(published_dir: Path):
    rows = []
    for d in sorted(p for p in published_dir.iterdir() if p.is_dir()):
        m = FOLDER.match(d.name)
        fm_script = frontmatter(d / "稿件.md")
        fm_record = frontmatter(d / "发布记录.md")
        fms = [fm_record, fm_script]
        row = {
            "folder": d.name,
            "date": (m.group("date") if m else ""),
            "id": clean(pick(fms, FIELDS["id"])) or (m.group("id") if m else ""),
            "platform": clean(pick(fms, FIELDS["platform"]), 20)
                        or platform_from_status(pick(fms, ["状态"]))
                        or ("X" if m and m.group("id") == "X" else ""),
            "title": clean(pick(fms, FIELDS["title"]), 40) or (m.group("title") if m else d.name),
            "conclusion": clean(pick(fms, FIELDS["conclusion"])),
            "analogy": clean(pick(fms, FIELDS["analogy"]), 60),
        }
        missing = [k for k in ("conclusion", "analogy", "platform") if not row[k]]
        row["missing"] = "、".join({"conclusion": "核心结论", "analogy": "主类比", "platform": "平台"}[k] for k in missing)
        if row["date"]:
            row["date"] = f"{row['date'][:4]}-{row['date'][4:6]}-{row['date'][6:]}"
        rows.append(row)
    return rows


def render(rows, published_dir: Path) -> str:
    head = [
        "---",
        "id: INDEX-已发布内容库-自动",
        "type: 生成物（不要手改）",
        f"来源: {published_dir}",
        "---",
        "",
        "# 已发布内容库（自动重建）",
        "",
        "> 由 `scripts/rebuild_published_index.py` 从每条内容的文件夹重建。**查重时和手工表一起看**：手工表有数据与备注，本表保证一条都不漏。",
        "> 「缺项」一栏非空的，说明那条稿件的 frontmatter 少写了字段 —— 补到 `稿件.md` 里，下次重建就有。",
        "",
        "| 发布日期 | 编号 | 平台 | 标题 | 核心结论（一句话） | 主类比 | 目录 | 缺项 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    body = [
        f"| {r['date']} | {r['id']} | {r['platform']} | {r['title']} | {r['conclusion']} | {r['analogy']} | `{r['folder']}` | {r['missing']} |"
        for r in rows
    ]
    return "\n".join(head + body) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    config_file = args.config or (REPO / "config.yaml")
    if not config_file.exists():
        config_file = REPO / "config.example.yaml"
    paths = load_paths(config_file)
    vault_raw = paths.get("vault_root") or ""
    vault = Path(os.path.expanduser(vault_raw)).resolve() if vault_raw else Path.cwd()
    drafts = vault / (paths.get("drafts") or "_草稿")
    manual_index = vault / (paths.get("published_index") or "_已发布/已发布内容库.md")

    # Where the one-folder-per-piece directories live. `config.paths.published_dir`
    # when set; otherwise the first candidate that actually holds dated folders.
    candidates = list(dict.fromkeys(c for c in (paths.get("published_dir"), "_草稿/已发布", paths.get("published"), "_已发布") if c))
    published_dir = None
    for c in candidates:
        if not c:
            continue
        d = vault / c
        if d.is_dir() and any(FOLDER.match(x.name) for x in d.iterdir() if x.is_dir()):
            published_dir = d
            break
    if published_dir is None:
        print("❌ 找不到放已发布文件夹的目录（按「YYYYMMDD-编号-短标题」命名的子目录）。查过：")
        for c in candidates:
            if c:
                print(f"   {vault / c}")
        print("   在 config.yaml 的 paths 里加 published_dir: \"<相对 vault 的目录>\" 指过去。")
        return 1

    rows = collect(published_dir)
    out_path = manual_index.with_name(manual_index.stem + ".自动.md")
    text = render(rows, published_dir)
    if not args.dry_run:
        out_path.write_text(text, encoding="utf-8")
    print(f"已发布目录 : {published_dir}  ({len(rows)} 条)")
    print(f"自动表     : {out_path}{'  (dry-run, 未写)' if args.dry_run else ''}")

    # diff against the manual index
    unregistered, dangling = [], []
    if manual_index.is_file():
        manual = manual_index.read_text(encoding="utf-8", errors="ignore")
        for r in rows:
            if r["folder"] not in manual:
                unregistered.append(r)
        # every backtick-quoted path that points into a published folder must
        # resolve from the vault root — this catches a wrong prefix
        # (`_草稿/_草稿/已发布/…`) as well as a folder that was renamed
        rel_pub = published_dir.relative_to(vault).as_posix()
        for m in re.finditer(r"`([^`\n]*" + re.escape(rel_pub.split("/")[-1]) + r"/[^`\n]+)`", manual):
            raw = m.group(1).strip()
            if "<" in raw:                  # template placeholder, not a folder
                continue
            if not (vault / raw).exists():
                dangling.append(raw)
    else:
        print(f"⚠️ 手工表不存在：{manual_index}（只生成自动表，不比对）")

    incomplete = [r for r in rows if r["missing"]]
    print()
    if unregistered:
        print(f"❌ 未登记到手工表（{len(unregistered)} 条）—— 去重闸门对它们是瞎的：")
        for r in unregistered:
            print(f"   {r['date']}  {r['id']}  {r['title']}   `{r['folder']}`")
    if dangling:
        print(f"⚠️ 手工表指到不存在的目录（{len(dangling)} 条）：")
        for d in sorted(set(dangling)):
            print(f"   {d}")
    if incomplete:
        print(f"⚠️ frontmatter 缺字段（{len(incomplete)} 条）—— 自动表里这几格是空的：")
        for r in incomplete:
            print(f"   {r['folder']}: 缺 {r['missing']}")
    if not (unregistered or dangling or incomplete):
        print("✅ 目录与手工表一致，字段齐全。" if manual_index.is_file() else "✅ 自动表已生成（没有手工表，未比对）。")
    return 1 if unregistered else 0


if __name__ == "__main__":
    sys.exit(main())
