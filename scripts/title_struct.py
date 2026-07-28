#!/usr/bin/env python3
"""
Rebuild the title formula library from self-collected data.

The old library was derived from a third-party formula set and cannot be redistributed.
This script derives structural patterns instead: it measures which *shapes* of title
over-perform, across two independently-styled benchmark pools plus the author's own
account, and reports lift with sample counts.

Output is structure only — no source title text is emitted, so nothing here carries
third-party expression into a publishable artifact.
"""

import csv
import re
import statistics
from pathlib import Path

# Usage:
#   python3 scripts/title_struct.py data.csv --title 标题 --metric 收藏率
#   python3 scripts/title_struct.py a.csv b.csv --title title --metric save_intent
#
# Two files means a cross-source replication check, which is the whole point:
# a pattern that only holds in one source is a property of that source, not a rule.
MIN_TOTAL = 100      # below this, do not draw conclusions
MIN_HIGH  = 25
MIN_HITS  = 12       # a pattern needs this many hits in the HIGH group to count

# Structural patterns. Each is a *shape* a title can take, not a topic.
STRUCT = {
 "S1 数量清单":        r"^\D{0,10}\d+\s*(?:个|条|种|招|步|点|件|款|类|个字)",
 "S2 数字带单位":      r"\d+\s*(?:天|周|月|年|分钟|小时|块|元|万|倍|%)",
 "S3 圈定人群":        r"^(?:.{0,6})?(?:你|你们|普通人|新手|小白|老板|打工|上班族|宝妈|学生|中年|年轻人)",
 "S4 疑问开头":        r"^(?:为什么|怎么|如何|凭什么|是不是|能不能|要不要|该不该)",
 "S5 否定祈使":        r"^(?:别|不要|千万别|再也不|停止)",
 "S6 纠错通念":        r"(?:错了|搞反|想错|误区|白干|白费|其实不|并不|根本不)",
 "S7 揭示隐藏":        r"(?:真相|背后|内幕|秘密|没人告诉|不会告诉|真实原因|底层)",
 "S8 对照结构":        r"(?:不是.{1,12}(?:而是|是)|.{1,8}vs|比.{1,10}还|与其.{1,10}不如)",
 "S9 亲历自述":        r"^(?:我|我们)(?!们?好)",
 "S10 结果前置":       r"^.{0,12}(?:做到|做成|赚到|涨到|拿到|干到|做出)",
 "S11 条件承诺":       r"(?:只要|哪怕|即使|就算|不用|不需要|零基础|不花钱)",
 "S12 时间限定":       r"(?:今年|明年|现在|马上|立刻|当天|一天|一周|第一次|最后)",
}


def f(v, d=0.0):
    try: return float(v)
    except (TypeError, ValueError): return d


def load(path, tkey, skey):
    out = []
    for r in csv.DictReader(path.open(encoding="utf-8-sig")):
        if (r.get("is_live_replay") or "").lower() not in ("false", "0", ""):
            continue
        t = (r.get(tkey) or "").strip()
        s = f(r.get(skey))
        if t and s > 0:
            out.append((t, s))
    return out


def analyse(data, label):
    data.sort(key=lambda d: -d[1])
    cut = max(1, int(len(data) * 0.25))
    hi, ba = data[:cut], data[cut:]
    res = {}
    for name, pat in STRUCT.items():
        h = sum(1 for t, _ in hi if re.search(pat, t))
        b = sum(1 for t, _ in ba if re.search(pat, t))
        hp, bp = 100*h/len(hi), 100*b/len(ba) if ba else 0
        res[name] = (hp, bp, (hp/bp if bp else float("inf")), h)
    return res, len(data), len(hi)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="算出你自己账号的标题结构规律")
    ap.add_argument("csv", nargs="+", help="一个或两个 CSV。给两个会做跨源复现检验")
    ap.add_argument("--title", default="title", help="标题列名")
    ap.add_argument("--metric", default="save_intent", help="效果指标列名（收藏率/完播率/点击率都行）")
    args = ap.parse_args()

    print("# 标题结构实证\n")
    print("> 只统计结构，不输出任何原始标题。\n")
    allres = {}
    for i, fp in enumerate(args.csv[:2]):
        label = f"源{chr(65+i)}"
        path = Path(fp)
        if not path.exists():
            print(f"（{label} 找不到文件 {fp}，跳过）"); continue
        data = load(path, args.title, args.metric)
        if len(data) < MIN_TOTAL:
            print(f"⚠️ {label} 只有 {len(data)} 条，少于 {MIN_TOTAL} 条**不要下结论**——"
                  f"这不是「没效果」，是没测到。\n")
        res, n, nh = analyse(data, label)
        allres[label] = res
        print(f"## {label}（n={n}，HIGH=TOP25% n={nh}）\n")
        print("| 结构 | HIGH | BASE | 提升 | 命中 |")
        print("|---|---|---|---|---|")
        for name, (hp, bp, lift, h) in sorted(res.items(), key=lambda x: -x[1][2]):
            mark = " ✅" if (h >= MIN_HITS and lift >= 1.35) else (" ⛔" if (h >= MIN_HITS and lift <= 0.74) else " —样本不足" if h < MIN_HITS else "")
            ls = "∞" if lift == float("inf") else f"{lift:.2f}×"
            print(f"| {name} | {hp:.0f}% | {bp:.0f}% | {ls} | {h}{mark} |")
        print()

    if len(allres) == 2:
        (_, a), (_, b) = sorted(allres.items())
        print("## 跨源判定（硬标准：风格互不相同的两个源上同向才算复现）\n")
        print("| 结构 | 源A | 源B | 判定 |")
        print("|---|---|---|---|")
        for name in STRUCT:
            la, ha = a[name][2], a[name][3]
            lb, hb = b[name][2], b[name][3]
            same_up = la >= 1.35 and lb >= 1.35
            same_dn = la <= 0.74 and lb <= 0.74
            enough = ha >= MIN_HITS and hb >= MIN_HITS
            if same_up and enough: v = "✅ 复现·正向"
            elif same_dn and enough: v = "⛔ 复现·负向"
            elif same_up or same_dn: v = "⚠️ 同向但样本不足"
            else: v = "— 不复现"
            fa = "∞" if la == float("inf") else f"{la:.2f}"
            fb = "∞" if lb == float("inf") else f"{lb:.2f}"
            print(f"| {name} | {fa}× (n={ha}) | {fb}× (n={hb}) | {v} |")


if __name__ == "__main__":
    main()

# 只给了一个源时的提醒
