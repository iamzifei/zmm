#!/usr/bin/env python3
"""
Leak scan — refuse to publish anything carrying private detail.

Run before extracting a public repo. Every pattern below is something that must not
leave this machine: the author's identity, product and customer names, revenue
figures, local paths, credentials, and the names of benchmark accounts that the
red lines say must never be named.

Exit code 1 if anything is found, so this can gate a release step.

Usage:
    python3 scripts/leak_scan.py [path ...]      # defaults to the repo root
"""

import re
import sys
from pathlib import Path

# Files that are allowed to contain private values, because they never ship.
ALLOWLIST = {
    "config.yaml",            # private config, excluded from the public repo
    "leak_scan.py",           # this file names the patterns it looks for
}
ALLOWLIST_DIRS = {".git", "node_modules", "docs/runs", "docs/reviews", "docs/plans"}

PATTERNS = [
    # identity
    # 2026-09-01 James 定：对外版本署名。IP 名「詹明明」是署名，不是泄漏。
    # 仍然是泄漏的：真名 James（也是本机用户名，路径检测靠它）、法律实体 Orris。
    # 旧 IP 名「詹有才」由 build_public.sh 归一成「詹明明」，公开树里不该再出现。
    ("作者身份", r"詹有才|James\b|Orris|OrrisTech"),
    # product / repo names
    ("产品与仓库名", r"musicapi|aimusicapi|sunoapi|imaginepro|adwhiz|ccapi|orrisapi|"
                     r"letitrun|figviz|conceptviz|poseup|kolfind|askusers|clipstack"),
    # benchmark creators — the red lines forbid naming these anywhere
    ("对标真名", r"李永乐|瑶瑶|李同学|dontbesilent|dbs-"),
    # money
    ("金额", r"\$\s?\d[\d,]{2,}|月流水|六位数美金|\d{4,}\s*(?:美金|美元|刀)"),
    # infrastructure identifiers
    # An env-var NAME carries no secret and setup docs must be able to print it
    # ("put TIKHUB_API_KEY in ~/.env"). What leaks is a VALUE assigned to one, so
    # the key-name pattern only fires when an actual key-shaped value follows.
    ("账号与密钥", r"acct_[A-Za-z0-9]|sk-[A-Za-z0-9]|pk_[A-Za-z0-9]|"
                   r"[A-Z_]{3,}_API_KEY\s*[:=]\s*['\"]?[A-Za-z0-9][A-Za-z0-9_.\-]{11,}|"
                   r"Bearer\s+[A-Za-z0-9]"),
    # local machine paths. `~/.claude/skills/` is the standard install location and
    # carries no identity, so it is only a leak inside a skill body (where it would be
    # a hardcoded cross-skill path) — install docs are expected to name it.
    ("本机路径", r"/Users/[a-z]+/|~/Dev/"),
    ("技能内硬编码路径", r"~/\.claude/skills/", ("SETUP.md", "README.md", "install.sh")),
    # unpublished drafts. A published script is public record and may keep its
    # number; an unpublished one identifies work that has not shipped. Zero-padded
    # (N01-N15) and the specific unpublished two-digit numbers are listed here.
    # Single-digit N1/N2/N3 are empirical-rule ids in 实证规律库.md, not scripts —
    # the word boundary and the padding keep them out of this pattern.
    ("未发布稿引用", r"\bN(?:0[1-9]|1[0-5]|17|18|21|2[4-9]|3[01])\b"),
]


def scan(path: Path):
    hits = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return hits
    for lineno, line in enumerate(text.splitlines(), 1):
        for entry in PATTERNS:
            label, pat = entry[0], entry[1]
            exempt = entry[2] if len(entry) > 2 else ()
            if path.name in exempt:
                continue
            m = re.search(pat, line, re.I)
            if m:
                snippet = line.strip()
                if len(snippet) > 96:
                    snippet = snippet[:96] + "…"
                hits.append((lineno, label, m.group(0), snippet))
    return hits


def main():
    roots = [Path(a) for a in sys.argv[1:]] or [Path(__file__).resolve().parent.parent]
    total = 0
    files = 0
    for root in roots:
        # .py is scanned too: the published tree ships helper scripts, and those
        # are exactly the files that touch ~/.env and API keys.
        targets = [root] if root.is_file() else sorted(
            f for pat in ("*.md", "*.yaml", "*.py", "*.sh") for f in root.rglob(pat))
        for f in targets:
            rel = f.relative_to(root) if not root.is_file() else f
            if f.name in ALLOWLIST:
                continue
            if any(part in ALLOWLIST_DIRS for part in rel.parts) or \
               any(str(rel).startswith(d) for d in ALLOWLIST_DIRS):
                continue
            hits = scan(f)
            if hits:
                files += 1
                print(f"\n── {rel} ── {len(hits)} 处")
                for lineno, label, found, snippet in hits[:8]:
                    print(f"   {lineno:>4}  [{label}] {found}")
                    print(f"         {snippet}")
                if len(hits) > 8:
                    print(f"         … 另有 {len(hits) - 8} 处")
                total += len(hits)

    print("\n" + "=" * 60)
    if total:
        print(f"❌ 发现 {total} 处泄漏，分布在 {files} 个文件。**不可发布。**")
        print("   允许保留的文件：" + "、".join(sorted(ALLOWLIST)))
        print("   跳过的目录（内部文档）：" + "、".join(sorted(ALLOWLIST_DIRS - {'.git', 'node_modules'})))
        return 1
    print("✅ 未发现泄漏，可以发布。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
