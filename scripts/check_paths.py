#!/usr/bin/env python3
"""
Load-list health check — does every path the skills promise to read actually exist?

The family covenant (zmm/references/家族公约.md §一) lists every file a skill
reads before it works, and config.yaml `paths.*` can override any of them. A rule
file that is not on that list "does not exist" as far as the skills are
concerned — the repo already paid for that lesson once (a script was voided
twice because a rule file had moved). Nothing checked the list against disk
until now; this script does.

What it checks
  1. config.paths.* — every value resolves to an existing file or directory
     under vault_root (repo-relative entries such as zmm-*/references/… are
     checked against the repo instead).
  2. Every backtick path in the covenant's §一 table — same resolution rules;
     `config.paths.<key> → default` rows use the config value when set.
  3. Memory records marked 废弃 that are still referenced by another record
     (only when the memory directory exists).

Exit code 1 when anything required is missing, so it can gate a release step or
run at the start of a session.

Usage:
    python3 scripts/check_paths.py                # uses config.yaml, else config.example.yaml
    python3 scripts/check_paths.py --config path/to/config.yaml
    python3 scripts/check_paths.py --vault ~/somewhere   # override vault_root
"""

import argparse
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COVENANT = REPO / "zmm" / "references" / "家族公约.md"


# --------------------------------------------------------------------------- config
def load_paths(config_file: Path) -> dict:
    """Return config['paths'] as a dict. PyYAML when present, else a tiny parser
    that only understands the two-level `paths:` block this script needs."""
    text = config_file.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text) or {}
        return dict(data.get("paths") or {})
    except ImportError:
        pass
    paths, inside = {}, False
    for line in text.splitlines():
        if re.match(r"^paths:\s*(#.*)?$", line):
            inside = True
            continue
        if inside:
            if line and not line.startswith(" "):
                break
            m = re.match(r"^\s+([A-Za-z_]+):\s*(.*?)\s*(#.*)?$", line)
            if m:
                paths[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return paths


# --------------------------------------------------------------------------- covenant
ROW = re.compile(r"^\|\s*(?P<what>[^|]+?)\s*\|\s*(?P<where>[^|]+?)\s*\|\s*$")
TICK = re.compile(r"`([^`]+)`")
CONFIG_REF = re.compile(r"config\.paths\.([A-Za-z_]+)")


def covenant_entries(text: str):
    """Yield (label, config_key or None, [paths]) for each row of the §一 table."""
    if "## 一、" not in text:
        sys.exit("❌ 家族公约里找不到「## 一、」这一节，路径表的位置变了，先改本脚本的锚点。")
    section = text.split("## 一、", 1)[1].split("\n## ", 1)[0]
    for line in section.splitlines():
        m = ROW.match(line)
        if not m or m.group("what") in ("要什么", "---"):
            continue
        where = m.group("where")
        key = CONFIG_REF.search(where)
        ticks = TICK.findall(where)
        # command rows ("python3 …") are not files to stat, and `config.paths.x`
        # is the name of a config key, not a path
        ticks = [t for t in ticks
                 if not t.startswith(("python3", "bash", "npx", "config.paths."))]
        # "`dir/`（`a.md`、`b.md`）" — the parenthesised files live inside the dir
        expanded = []
        base = None
        for t in ticks:
            if t.endswith("/"):
                base = t
                expanded.append(t)
            elif base and "/" not in t:
                expanded.append(base + t)
            else:
                expanded.append(t)
        yield m.group("what").strip("* "), (key.group(1) if key else None), expanded


def is_repo_relative(p: str) -> bool:
    return p.startswith(("zmm/", "zmm-")) or p == "zmm"


def resolve(p: str, vault: Path) -> Path:
    if is_repo_relative(p):
        return REPO / p
    return vault / p


# --------------------------------------------------------------------------- memory
def stale_memory_refs(memory_dir: Path):
    """Records marked 废弃 whose file name is still mentioned by another record."""
    if not memory_dir.is_dir():
        return []
    records = list(memory_dir.rglob("*.md"))
    deprecated = []
    for f in records:
        head = f.read_text(encoding="utf-8", errors="ignore")[:800]
        if re.search(r"^status:\s*废弃", head, re.M):
            deprecated.append(f)
    hits = []
    for d in deprecated:
        for f in records:
            if f == d:
                continue
            if d.stem in f.read_text(encoding="utf-8", errors="ignore"):
                hits.append((d.relative_to(memory_dir), f.relative_to(memory_dir)))
    return hits


# --------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path)
    ap.add_argument("--vault", type=Path)
    args = ap.parse_args()

    config_file = args.config or (REPO / "config.yaml")
    if not config_file.exists():
        config_file = REPO / "config.example.yaml"
    paths = load_paths(config_file)

    vault_raw = str(args.vault) if args.vault else paths.get("vault_root", "") or ""
    vault = Path(os.path.expanduser(vault_raw)).resolve() if vault_raw else Path.cwd()
    print(f"config : {config_file.relative_to(REPO) if config_file.is_relative_to(REPO) else config_file}")
    print(f"vault  : {vault}" + ("   ⚠️ vault_root 未设，按当前目录" if not vault_raw else ""))
    if not vault.is_dir():
        print(f"\n❌ vault 目录不存在：{vault}")
        return 1

    missing, ok = [], 0

    # 1. config.paths.*
    print("\n── config.paths ──")
    for key, val in paths.items():
        if key == "vault_root" or not val:
            continue
        target = resolve(val, vault)
        if target.exists():
            ok += 1
        else:
            missing.append(("config.paths." + key, val))
            print(f"  ❌ {key}: {val}")

    # 2. covenant §一
    print("── 家族公约 §一 ──")
    covenant = COVENANT.read_text(encoding="utf-8")
    for label, key, ticks in covenant_entries(covenant):
        # config value wins when the key is set; otherwise the covenant's own
        # default path(s) — an older config.yaml that lacks a newer key must not
        # be reported as "missing", the default location is still valid
        candidates = [paths[key]] if (key and paths.get(key)) else ticks
        for p in candidates:
            target = resolve(p, vault)
            # a wildcard row (`zmm-*/references/规则卡.md`) passes when it matches at least one file
            if "*" in p:
                base = REPO if is_repo_relative(p) else vault
                if any(base.glob(p)):
                    ok += 1
                    continue
            if target.exists():
                ok += 1
            else:
                missing.append((label, p))
                print(f"  ❌ {label}: {p}")

    # 3. memory
    memory_dir = vault / (paths.get("memory") or "08-技能记忆")
    stale = stale_memory_refs(memory_dir)
    if stale:
        print("── 技能记忆：已废弃但仍被引用 ──")
        for d, f in stale:
            print(f"  ⚠️ {d}  ← 仍被 {f} 引用")

    print("\n" + "=" * 60)
    print(f"存在 {ok} 项，缺失 {len(missing)} 项，废弃仍被引用 {len(stale)} 项")
    if missing:
        print("❌ 加载清单与磁盘不一致。要么把文件放回去，要么改 config.paths / 公约表，别让技能带着一条指不到的路径开工。")
        return 1
    print("✅ 加载清单全部指得到。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
