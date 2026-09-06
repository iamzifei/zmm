#!/usr/bin/env python3
"""
benchmark_fetch.py — pull a benchmark creator's whole post list, then cut it into
the three batches /zmm-benchmark reasons over: earliest, best-performing, latest.

Standard library only. No pip install, no virtualenv — a non-technical user can
run it with the python3 that ships with macOS.

  export TIKHUB_API_KEY=...            # or put it in ~/.env, this reads that too

  # 1. find candidate accounts by keyword (douyin / xiaohongshu)
  python3 benchmark_fetch.py search --platform douyin --kw "AI 副业"

  # 2. what will pulling this account cost, before spending anything
  python3 benchmark_fetch.py list --platform douyin --id <sec_user_id> \
      --out 对标-某某 --dry-run

  # 3. pull the full post list -> 01-全量列表.csv + _raw/*.json
  python3 benchmark_fetch.py list --platform douyin --id <sec_user_id> --out 对标-某某

  # 4. cut into the three batches -> 10-0到1/ 20-爆款/ 30-最新/
  python3 benchmark_fetch.py pick --out 对标-某某

  # 5. download covers (and optionally the videos themselves)
  python3 benchmark_fetch.py media --out 对标-某某 [--video]

Every network call is counted and reported. `list` refuses to exceed
--max-requests (default 30) so a 2000-video account cannot silently burn credit.
"""

import argparse
import csv
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

API_BASE = "https://api.tikhub.io"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
CN = timezone(timedelta(hours=8))

# Every request costs money. Counted here so the user is told the real number
# rather than an estimate, and so --max-requests can actually stop the loop.
CALLS = {"n": 0}


# --------------------------------------------------------------------------
# key handling
# --------------------------------------------------------------------------

def load_key(explicit=None):
    """Key from --key, then TIKHUB_API_KEY, then a KEY=VALUE line in ~/.env."""
    if explicit:
        return explicit.strip()
    if os.environ.get("TIKHUB_API_KEY"):
        return os.environ["TIKHUB_API_KEY"].strip()
    dotenv = Path.home() / ".env"
    if dotenv.is_file():
        for line in dotenv.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = re.match(r"\s*(?:export\s+)?TIKHUB_API_KEY\s*=\s*(.+)", line)
            if m:
                return m.group(1).strip().strip("'\"")
    die("找不到 TIKHUB_API_KEY。\n"
        "  临时用：export TIKHUB_API_KEY=你的key\n"
        "  长期用：把  TIKHUB_API_KEY=你的key  写进 ~/.env\n"
        "  还没有 key：去 https://tikhub.io 注册，控制台里「API Keys」新建一个。")


def die(msg, code=1):
    print(f"\n❌ {msg}\n", file=sys.stderr)
    sys.exit(code)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

class AuthError(RuntimeError):
    """Key or balance problem. Retrying cannot fix it and each try still hits the API."""


def _request(req, tries=5):
    last = None
    for i in range(tries):
        # Counted here, not in api_get/api_post: a retry is another real request.
        # The cost number this produces is what the skill shows the user before
        # asking permission to spend, so it must not undercount.
        CALLS["n"] += 1
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")
            if e.code in (401, 402, 403):
                raise AuthError(f"HTTP {e.code}: {detail[:400]}") from None
            last = RuntimeError(f"HTTP {e.code}: {detail[:200]}")
            time.sleep(1.5 * (i + 1))
            continue
        except Exception as e:  # noqa: BLE001 - network flake, retry
            last = e
            time.sleep(1.5 * (i + 1))
            continue

        # TikHub reports upstream failures as HTTP 200 with a "detail" envelope,
        # so not raising is not the same as succeeding.
        det = body.get("detail")
        if isinstance(det, dict) and det.get("code") not in (None, 200):
            code = det.get("code")
            msg = det.get("message_zh") or det.get("message") or ""
            if code in (401, 402, 403):
                raise AuthError(f"TikHub {code}: {msg}")
            last = RuntimeError(f"TikHub {code}: {str(msg)[:120]}")
            time.sleep(1.5 * (i + 1))
            continue
        return body
    raise last if last else RuntimeError("请求失败，且没有拿到错误信息")


def api_get(path, params, key):
    url = f"{API_BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {key}", "User-Agent": UA, "Accept": "application/json"})
    return _request(req)


def api_post(path, body, key):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"{API_BASE}{path}", data=data, headers={
        "Authorization": f"Bearer {key}", "User-Agent": UA,
        "Content-Type": "application/json", "Accept": "application/json"})
    return _request(req)


# --------------------------------------------------------------------------
# id extraction — users paste homepage links, not raw ids
# --------------------------------------------------------------------------

def _resolve_short_link(raw):
    """Pull the URL out of a share blob and follow it. Returns "" on failure."""
    m = re.search(r"https?://[^\s，,）)】]+", raw)
    if not m:
        return ""
    try:
        req = urllib.request.Request(m.group(0), headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.geturl()
    except Exception:  # noqa: BLE001 - a dead short link is the caller's problem
        return ""


def extract_id(platform, raw):
    """Accept a raw id or a homepage URL and return the id the API wants."""
    raw = raw.strip()
    if platform == "douyin":
        m = re.search(r"/user/([A-Za-z0-9_\-]+)", raw)
        if m:
            return m.group(1)
        # The App's "copy link" gives a whole Chinese sentence wrapped around a
        # v.douyin.com short link — which is exactly what the skill tells the
        # user to send. Follow it rather than posting the sentence as an id.
        if "v.douyin.com" in raw:
            resolved = _resolve_short_link(raw)
            m = re.search(r"/user/([A-Za-z0-9_\-]+)", resolved or "")
            if m:
                return m.group(1)
            die("这个抖音短链没指向账号主页"
                + (f"（它跳到了 {resolved[:80]}）" if resolved else "（打不开）") + "。\n"
                "   在 App 里点头像进他主页，再从**主页**点分享→复制链接；\n"
                "   或者在电脑浏览器打开他主页，把地址栏里 douyin.com/user/… 那串发我。")
        if raw.startswith("http"):
            die("这个链接里没有账号 id。要的是主页链接（douyin.com/user/…），"
                "不是单条视频的链接。")
        return raw  # a sec_user_id (MS4wLjABAAA…)
    if platform == "xiaohongshu":
        m = re.search(r"/user/profile/([0-9a-f]{16,})", raw)
        if m:
            return m.group(1)
        if "xhslink.com" in raw:
            die("这是小红书的短链，里面没有账号 id。\n"
                "   在浏览器里打开它，等跳转完之后复制地址栏里那个"
                " xiaohongshu.com/user/profile/… 的完整地址给我。")
        return raw
    if platform == "wechat_channels":
        if "@finder" in raw:
            m = re.search(r"(v2_[0-9a-f]+@finder)", raw)
            return m.group(1) if m else raw.strip()
        die("视频号要的是 finder username（形如 v2_06000…@finder），不是昵称或链接。\n"
            "   拿法：TikHub 的 fetch_channel_id_to_username 接口可以把 sph 开头的\n"
            "   Channel ID 转成它；Channel ID 在视频号主页分享出来的链接里。")
    return raw


# --------------------------------------------------------------------------
# normalisation — one row shape for every platform
# --------------------------------------------------------------------------

def _ts(sec):
    try:
        return datetime.fromtimestamp(int(sec), CN).strftime("%Y-%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        return ""


def norm_douyin(a):
    st = a.get("statistics") or {}
    v = a.get("video") or {}

    def first(node):
        return ((node or {}).get("url_list") or [""])[0]

    return {
        "platform": "douyin",
        "id": a.get("aweme_id", ""),
        "title": (a.get("desc") or "").replace("\n", " ").strip(),
        "created_ts": int(a.get("create_time") or 0),
        "created": _ts(a.get("create_time")),
        # Douyin reports duration in milliseconds.
        "duration_s": round((a.get("duration") or v.get("duration") or 0) / 1000, 1),
        "digg": st.get("digg_count") or 0,
        "comment": st.get("comment_count") or 0,
        "collect": st.get("collect_count") or 0,
        "share": st.get("share_count") or 0,
        # NOTE: the Douyin *web* endpoint always returns play_count = 0. Verified
        # 2026-09-03 across a full page. Do not present it as a real number.
        "play": st.get("play_count") or 0,
        "is_top": 1 if a.get("is_top") else 0,
        "url": f"https://www.douyin.com/video/{a.get('aweme_id','')}",
        "cover_url": first(v.get("origin_cover")) or first(v.get("cover")),
        "play_url": first(v.get("play_addr")),
    }


def norm_xhs(n):
    """Field paths verified 2026-09-03 against app_v2/get_user_posted_notes."""
    imgs = n.get("images_list") or []
    cover = ""
    if imgs:
        cover = imgs[0].get("url_size_large") or imgs[0].get("url") or ""
    ts = n.get("create_time") or 0
    if ts and int(ts) > 10 ** 12:      # some fields come back in milliseconds
        ts = int(ts) // 1000
    return {
        "platform": "xiaohongshu",
        "id": n.get("id") or n.get("note_id") or "",
        "title": (n.get("display_title") or n.get("title") or "").replace("\n", " ").strip(),
        "created_ts": int(ts or 0),
        "created": _ts(ts),
        # The notes list carries no duration for video notes.
        "duration_s": 0,
        "digg": n.get("likes") or 0,
        "comment": n.get("comments_count") or 0,
        "collect": n.get("collected_count") or 0,
        "share": n.get("share_count") or 0,
        # Verified 0 across a whole page, same as Douyin web. Not a real number.
        "play": n.get("view_count") or 0,
        "is_top": 1 if n.get("sticky") else 0,
        "url": f"https://www.xiaohongshu.com/explore/{n.get('id') or ''}",
        "cover_url": cover,
        "play_url": "",
        # normal = 图文, video = 视频. Worth keeping: the two forms are not
        # comparable, and a benchmark that switched from one to the other is a
        # finding in its own right.
        "note_type": n.get("type") or "",
    }


def norm_channels(v):
    """Field paths verified 2026-09-03 against wechat_channels/v2 with raw=false.

    The raw=true shape is completely different (objectDesc/likeCount/…); this
    reads the parsed shape, which is what the fetcher asks for.
    """
    m = v.get("media") or {}
    cover = (m.get("cover_url") or "") + (m.get("cover_url_token") or "")
    return {
        "platform": "wechat_channels",
        "id": str(v.get("id") or ""),
        "title": (v.get("title") or v.get("description") or "").replace("\n", " ").strip(),
        "created_ts": int(v.get("create_time") or 0),
        "created": _ts(v.get("create_time")),
        "duration_s": m.get("duration") or 0,
        "digg": v.get("like_count") or 0,
        "comment": v.get("comment_count") or 0,
        "collect": v.get("fav_count") or 0,
        "share": v.get("forward_count") or 0,
        # Verified 0 across two pages, same as the other two platforms.
        "play": v.get("read_count") or 0,
        "is_top": 0,
        "url": "",          # a share URL costs a separate fetch_video_share_url call
        "cover_url": cover,
        # Deliberately empty. The bytes behind media.url are ENCRYPTED — verified
        # 2026-09-03: no ftyp box, and the payload needs media.decode_key. Handing
        # this to the downloader would write a .mp4 that cannot be played, and the
        # completeness report would count it as a success.
        "play_url": "",
        "note_type": "",
    }


# --------------------------------------------------------------------------
# platform fetchers
# --------------------------------------------------------------------------

def _fans_text(sub_title):
    """"Fans 21.6k" -> 21600. Returns the raw string if it will not parse."""
    m = re.search(r"([\d.]+)\s*([kKwWmM万])?", sub_title or "")
    if not m:
        return sub_title or 0
    mult = {"k": 1e3, "m": 1e6, "w": 1e4, "万": 1e4}.get((m.group(2) or "").lower(), 1)
    try:
        return int(float(m.group(1)) * mult)
    except ValueError:
        return sub_title


def search_accounts(platform, kw, key, limit=30):
    if platform == "douyin":
        r = api_post("/api/v1/douyin/search/fetch_user_search_v2",
                     {"keyword": kw, "cursor": 0}, key)
        users = (((r.get("data") or {}).get("data") or {}).get("user_list")) or []
        return [{
            "name": u.get("nick_name", ""),
            "id": u.get("user_id", ""),          # this is the sec_user_id
            "fans": u.get("fans_cnt", 0),
            "likes": u.get("like_cnt", 0),
            "posts": u.get("publish_cnt", 0),
            "home": f"https://www.douyin.com/user/{u.get('user_id','')}",
        } for u in users[:limit]]

    if platform == "xiaohongshu":
        r = api_get("/api/v1/xiaohongshu/app_v2/search_users",
                    {"keyword": kw, "page": 1}, key)
        users = ((r.get("data") or {}).get("data") or {}).get("users") or []
        # Verified 2026-09-03: this endpoint returns follower count only, and only
        # as an abbreviated string ("Fans 21.6k"). No like total, no note count —
        # those need one get_user_info call per account.
        return [{
            "name": u.get("name", ""),
            "id": u.get("id", ""),
            "fans": _fans_text(u.get("sub_title", "")),
            "likes": None,          # printed as "—", not as 0
            "posts": None,
            "home": f"https://www.xiaohongshu.com/user/profile/{u.get('id','')}",
        } for u in users[:limit]]

    die("视频号没有「按关键词搜账号」的接口（TikHub 只提供号内搜）。\n"
        "   找视频号对标要么先在微信里搜到账号、把主页链接给我，\n"
        "   要么先在抖音/小红书找到同一个人，再回视频号看他有没有号。")


def _fetch_page(platform, uid, cursor, page_size, key, page, verbose):
    """One page. Returns (rows, has_more, next_cursor). Raises on hard failure."""
    if platform == "douyin":
        # Verified 2026-09-03: the same cursor intermittently comes back as
        # {"status_code": 0} — charged, but with no aweme_list and no has_more.
        # Reading that as "end of list" would silently fake the earliest-10
        # batch, so retry the cursor before believing it.
        for attempt in range(4):
            r = api_get("/api/v1/douyin/web/fetch_user_post_videos",
                        {"sec_user_id": uid, "max_cursor": cursor,
                         "count": page_size}, key)
            d = r.get("data") or {}
            if "aweme_list" in d or "has_more" in d:
                return ([norm_douyin(a) for a in (d.get("aweme_list") or [])],
                        bool(d.get("has_more")), str(d.get("max_cursor") or ""))
            if verbose and attempt < 3:
                print(f"  第 {page} 页返回空壳，重试 {attempt + 1}/3")
            time.sleep(2 + attempt)
        raise RuntimeError("同一游标连续 4 次返回空页")

    if platform == "xiaohongshu":
        params = {"user_id": uid}
        if cursor and cursor != "0":
            params["cursor"] = cursor
        r = api_get("/api/v1/xiaohongshu/app_v2/get_user_posted_notes", params, key)
        d = (r.get("data") or {}).get("data") or {}
        items = d.get("notes") or []
        # Verified 2026-09-03: there is NO top-level cursor. The cursor for the
        # next page hangs off the LAST note in this one. Reading a top-level key
        # returns "" and stops the pull after page 1 — which would silently make
        # the earliest-10 batch nothing but "the oldest of the first 20".
        nxt = str(items[-1].get("cursor") or "") if items else ""
        return [norm_xhs(n) for n in items], bool(d.get("has_more")), nxt

    if platform == "wechat_channels":
        body = {"username": uid, "raw": False}
        if cursor and cursor != "0":
            body["last_buffer"] = cursor
        r = api_post("/api/v1/wechat_channels/v2/fetch_user_videos", body, key)
        d = r.get("data") or {}
        items = d.get("videos") or []
        nxt = str(d.get("last_buffer") or "")
        # Verified 2026-09-03: `up_continue` is 0 even when more pages exist, so
        # it is NOT the has-more flag. The real signal is a fresh last_buffer plus
        # a non-empty page — page 2 came back with 15 new ids and 0 overlap.
        return [norm_channels(v) for v in items], bool(items and nxt), nxt

    die(f"不认识的平台：{platform}")
    return [], False, ""


def list_posts(platform, uid, key, max_requests, page_size=20, verbose=True):
    """Pull the whole post list, oldest first.

    Returns (rows, complete). `complete` is True ONLY when the API explicitly
    said there is no next page — a failed or truncated pull must never be
    presented as the account's full history, because the earliest-10 batch is
    read straight off the tail of this list.
    """
    rows, seen = [], set()
    cursor, page = "0", 0
    complete = False

    while True:
        if CALLS["n"] >= max_requests:
            if verbose:
                print(f"⚠️  已达请求上限 {max_requests} 次，停在第 {page} 页。"
                      f"要拉全请加大 --max-requests")
            break
        page += 1
        try:
            batch, has_more, cursor = _fetch_page(
                platform, uid, cursor, page_size, key, page, verbose)
        except RuntimeError as e:
            if verbose:
                print(f"  ⚠️  第 {page} 页取不到（{str(e)[:90]}）"
                      f"—— 保留已拉到的 {len(rows)} 条")
            break

        new = [x for x in batch if x["id"] and x["id"] not in seen]
        for x in new:
            seen.add(x["id"])
        rows.extend(new)
        if verbose:
            print(f"  第 {page} 页：+{len(new)} 条（累计 {len(rows)}）")

        if not has_more:
            complete = True   # the only trustworthy end-of-list signal
            break
        if not new or not cursor:
            if verbose:
                print("  ⚠️  还说有下一页，但游标没往前走 —— 列表不完整")
            break

    rows.sort(key=lambda x: x["created_ts"])
    return rows, complete


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------

def engagement(r):
    """Unweighted sum of the four interactions we can actually read.

    Deliberately unweighted: any weighting (e.g. share x5) would be an invented
    constant with nothing validating it. The per-field columns stay in the CSV so
    a human can see WHICH interaction carried a video.
    """
    return r["digg"] + r["comment"] + r["collect"] + r["share"]


def save_intent(r):
    """Collects per like. Reads as 'worth keeping' rather than 'worth applauding'."""
    return round(r["collect"] / r["digg"], 3) if r["digg"] else 0.0


CSV_COLS = ["created", "title", "digg", "comment", "collect", "share", "play",
            "engagement", "save_intent", "duration_s", "note_type", "is_top",
            "id", "url", "cover_url", "play_url", "platform", "created_ts"]


def write_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            r = dict(r)
            r["engagement"] = engagement(r)
            r["save_intent"] = save_intent(r)
            w.writerow(r)


def read_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in ("digg", "comment", "collect", "share", "play", "is_top",
                  "created_ts", "engagement"):
            r[k] = int(float(r.get(k) or 0))
        r["duration_s"] = float(r.get("duration_s") or 0)
    return rows


def pool_stats(rows):
    """The denominator. Without it a 'top 10' list is just survivorship bias."""
    eng = sorted(engagement(r) for r in rows)
    if not eng:
        return {}
    q = statistics.quantiles(eng, n=4) if len(eng) >= 4 else [eng[0], eng[len(eng) // 2], eng[-1]]
    durs = [r["duration_s"] for r in rows if r["duration_s"]]
    return {
        "n": len(rows),
        "eng_median": q[1],
        "eng_p25": q[0],
        "eng_p75": q[2],
        "eng_max": eng[-1],
        "eng_mean": round(statistics.fmean(eng), 1),
        "duration_median": round(statistics.median(durs), 1) if durs else 0,
        "first_post": min(r["created"] for r in rows),
        "last_post": max(r["created"] for r in rows),
    }


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def safe_name(s, n=24):
    s = re.sub(r"[\\/:*?\"<>|\n\r\t]", "", s).strip()
    s = re.sub(r"\s+", " ", s)
    return (s[:n] or "无标题")


def cmd_search(a):
    key = load_key(a.key)
    res = search_accounts(a.platform, a.kw, key, a.limit)
    if not res:
        print("没搜到账号。换个关键词，或者直接把主页链接给我。")
        return
    print(f"\n关键词「{a.kw}」· {a.platform} · {len(res)} 个候选\n")
    def cell(v):
        return "—" if v is None else str(v)

    print(f"{'账号名':<22}{'粉丝':>10}{'总赞':>12}{'作品':>7}  主页")
    for u in res:
        print(f"{u['name'][:20]:<22}{cell(u['fans']):>10}"
              f"{cell(u['likes']):>12}{cell(u['posts']):>7}  {u['home']}")
    if any(u["likes"] is None for u in res):
        print("\n（小红书的搜索接口只给粉丝数，总赞和作品数标「—」= 拿不到，不是 0）")
    print(f"\n（{CALLS['n']} 次请求，约 ${CALLS['n'] * 0.001:.3f}）")
    print("⚠️  粉丝多 ≠ 赚钱。下一步要判的是他靠什么收钱，不是他有多少粉。")


def cmd_list(a):
    key = load_key(a.key)
    uid = extract_id(a.platform, a.id)
    out = Path(a.out)

    if a.dry_run:
        if a.posts:
            n = a.posts
        else:
            die("--dry-run 需要你告诉我他大概发了多少条：加 --posts 67\n"
                "   （搜索结果里的「作品」那一列就是）")
        pages = -(-n // 20)
        print(f"\n他大约 {n} 条作品 → 需要翻 {pages} 页 → {pages} 次请求 ≈ ${pages * 0.001:.3f}")
        print(f"当前 --max-requests={a.max_requests}"
              f"{'（够）' if pages <= a.max_requests else '（不够，要调大，否则拿不到最早的那 10 条）'}")
        print("\n🔴 「最早 10 条」必须翻到列表最底才拿得到——这是这一步花钱的地方。")
        return

    out.mkdir(parents=True, exist_ok=True)
    (out / "_raw").mkdir(exist_ok=True)
    print(f"\n拉取 {a.platform} · {uid}")
    rows, complete = list_posts(a.platform, uid, key, a.max_requests)
    if not rows:
        die("一条都没拉到。检查 ID/链接是否正确，或该账号是否设了隐私。")

    write_csv(rows, out / "01-全量列表.csv")
    (out / "_raw" / "posts.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    st = pool_stats(rows)
    (out / "_raw" / "stats.json").write_text(
        json.dumps({**st, "complete": complete, "requests": CALLS["n"]},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n✅ {len(rows)} 条 → {out / '01-全量列表.csv'}")
    print(f"   时间跨度：{st['first_post']} → {st['last_post']}")
    print(f"   互动总量：中位 {st['eng_median']:.0f}｜四分位 {st['eng_p25']:.0f}–{st['eng_p75']:.0f}｜最高 {st['eng_max']}")
    print(f"   时长中位：{st['duration_median']}s")
    print(f"   {CALLS['n']} 次请求，约 ${CALLS['n'] * 0.001:.3f}")
    if not complete:
        print("\n🔴 列表没拉完 —— 「最早 10 条」这一批现在是假的（只是已拉到的里面最早的）。")
        print("   要么调大 --max-requests 重拉，要么在报告里注明 0-1 批不可用。")


def cmd_pick(a):
    out = Path(a.out)
    csv_path = out / "01-全量列表.csv"
    if not csv_path.is_file():
        die(f"找不到 {csv_path}，先跑 list")
    rows = read_csv(csv_path)
    if not rows:
        die(f"{csv_path} 里一条内容都没有（只有表头）。\n"
            "   A 轨：重跑 list。\n"
            "   B 轨：先把手工整理的内容填进这个 CSV 再跑 pick。")
    complete = True
    stats_file = out / "_raw" / "stats.json"
    if stats_file.is_file():
        complete = json.loads(stats_file.read_text(encoding="utf-8")).get("complete", True)

    n = a.n
    # A missing timestamp normalises to 0, which would sort that row to the very
    # front — straight into the 0-1 batch, the one batch the whole skill treats
    # as directly copyable. Keep undated rows out of both time-ordered batches.
    dated = sorted((r for r in rows if r["created_ts"] > 0),
                   key=lambda r: r["created_ts"])
    undated = [r for r in rows if r["created_ts"] <= 0]
    batches = {
        "10-0到1": dated[:n],
        "20-爆款": sorted(rows, key=lambda r: r["engagement"], reverse=True)[:n],
        "30-最新": dated[-n:][::-1],
    }
    st = pool_stats(rows)
    median = st["eng_median"] or 1
    kept = 0

    for bname, items in batches.items():
        bdir = out / bname
        bdir.mkdir(parents=True, exist_ok=True)
        for i, r in enumerate(items, 1):
            d = bdir / f"{i:02d}-{safe_name(r['title'])}"
            d.mkdir(exist_ok=True)
            # Re-running pick (e.g. with a different --n) must not wipe the
            # 封面大字 and 逐字稿 the user filled in by hand — on the manual track
            # that is the only work product in the whole flow.
            if (d / "meta.md").exists():
                kept += 1
                continue
            mult = engagement(r) / median
            (d / "meta.md").write_text(f"""---
platform: {r['platform']}
id: {r['id']}
created: {r['created']}
duration_s: {r['duration_s']}
digg: {r['digg']}
comment: {r['comment']}
collect: {r['collect']}
share: {r['share']}
play: {r['play']}
engagement: {r['engagement']}
engagement_vs_median: {mult:.2f}
save_intent: {save_intent(r)}
batch: {bname}
url: {r['url']}
---

# {r['title']}

- 发布：{r['created']}　时长：{r['duration_s']}s
- 赞 {r['digg']}　评 {r['comment']}　藏 {r['collect']}　转 {r['share']}
- 互动总量 {r['engagement']}，是这个号中位数的 **{mult:.2f} 倍**
- 收藏倾向（藏/赞）：{save_intent(r)}
- 链接：{r['url']}

## 封面大字（OCR / 人读）

（cover.jpg 下载后填这里）

## 逐字稿

（transcript.md）
""", encoding="utf-8")

    ov = set(x["id"] for x in batches["10-0到1"]) & set(x["id"] for x in batches["20-爆款"])
    print(f"\n✅ 三批已建（每批 {n} 条）：")
    for bname, items in batches.items():
        print(f"   {bname}：{len(items)} 条")
    if kept:
        print(f"\n📌 {kept} 条已有 meta.md，原样保留（你手填的封面大字和逐字稿没被覆盖）。"
              f"\n   要重新生成某条，先把它的 meta.md 删掉再跑。")
    if undated:
        print(f"\n⚠️  {len(undated)} 条没有发布时间，已排除在 0-1 批和最新批之外"
              f"（仍参与爆款排序和分母）。")
    print(f"\n全量分母：n={st['n']}，互动中位数 {st['eng_median']:.0f}")
    if ov and complete:
        print(f"⚠️  0-1 批和爆款批有 {len(ov)} 条重合 —— 说明他最早那批就是他最好的一批，"
              f"这本身是个结论。")
    if not complete:
        # Saying "his earliest batch is also his best" off a truncated list would
        # be a fabricated finding: the "earliest" here is just the oldest of what
        # happened to get pulled.
        print("🔴 列表未拉完，**0-1 批不可信** —— 它只是已拉到的那些里面最早的，"
              "不是这个号最早的。\n"
              "   加大 --max-requests 重拉，或者在报告里写明 0-1 批不可用。")


def parse_frontmatter(text):
    """Key/value pairs from the leading --- block only.

    Deliberately not a whole-file scan: meta.md's body is where the user pastes
    cover text and transcripts, and a pasted "id: ..." line must never be able to
    override the real id.
    """
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    block = text[3:end] if end != -1 else text[3:]
    return dict(re.findall(r"^(\w+): (.*)$", block, re.M))


def _download(url, dest, referer=None):
    if not url:
        return False, "没有链接"
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    # Stream to a .part file and only rename on success. A truncated cover.jpg
    # left on disk would make cmd_media's exists() check skip it forever, and the
    # multimodal read of 封面大字 would silently get a broken image.
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
        if tmp.stat().st_size == 0:
            tmp.unlink(missing_ok=True)
            return False, "0 字节"
        tmp.replace(dest)
        return True, ""
    except Exception as e:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        return False, str(e)[:120]


def cmd_media(a):
    out = Path(a.out)
    csv_path = out / "01-全量列表.csv"
    if not csv_path.is_file():
        die(f"找不到 {csv_path}，先跑 list")
    rows = {r["id"]: r for r in read_csv(csv_path)}
    if not list(out.glob("*/*/meta.md")):
        die("三批目录还没建，先跑 pick")
    ok = fail = skipped = 0
    referer = {"douyin": "https://www.douyin.com/",
               "xiaohongshu": "https://www.xiaohongshu.com/"}
    for meta in sorted(out.glob("*/*/meta.md")):
        fm = parse_frontmatter(meta.read_text(encoding="utf-8"))
        r = rows.get(fm.get("id", ""))
        if not r:
            print(f"  ⚠️  跳过 {meta.parent.name}：meta.md 的 id 在全量列表里找不到"
                  f"（id={fm.get('id', '空')}）")
            skipped += 1
            continue
        d = meta.parent
        if not (d / "cover.jpg").exists():
            good, err = _download(r["cover_url"], d / "cover.jpg",
                                  referer.get(r["platform"]))
            print(("  ✅ 封面 " if good else f"  ❌ 封面（{err}）") + d.name)
            ok, fail = (ok + 1, fail) if good else (ok, fail + 1)
        if a.video and r["platform"] == "wechat_channels":
            print(f"  ⏭  跳过视频 {d.name}：视频号的视频是加密的（要 decode_key 解），"
                  f"下下来放不了")
        elif a.video and not (d / "source.mp4").exists():
            good, err = _download(r["play_url"], d / "source.mp4",
                                  referer.get(r["platform"]))
            print(("  ✅ 视频 " if good else f"  ❌ 视频（{err}）") + d.name)
            ok, fail = (ok + 1, fail) if good else (ok, fail + 1)
    print(f"\n完成：{ok} 成功，{fail} 失败"
          + (f"，{skipped} 条对不上全量列表（跳过）" if skipped else ""))
    if fail:
        print("失败多半是链接过期（抖音 play_addr/cover 的签名有有效期）——重跑一次 list 再 media。")
    print("\n下一步：封面大字让 AI 直接看 cover.jpg 读出来（不用装 OCR），"
          "写进 meta.md 的「封面大字」段。")


def main():
    p = argparse.ArgumentParser(description="对标账号内容抓取（TikHub）")
    p.add_argument("--key", help="TikHub API key（默认读环境变量或 ~/.env）")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="按关键词找候选账号")
    s.add_argument("--platform", default="douyin",
                   choices=["douyin", "xiaohongshu", "wechat_channels"])
    s.add_argument("--kw", required=True)
    s.add_argument("--limit", type=int, default=30)
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("list", help="拉全量作品列表")
    s.add_argument("--platform", default="douyin",
                   choices=["douyin", "xiaohongshu", "wechat_channels"])
    s.add_argument("--id", required=True, help="sec_user_id / 主页链接 / finder username")
    s.add_argument("--out", required=True)
    s.add_argument("--max-requests", type=int, default=30)
    s.add_argument("--dry-run", action="store_true", help="只估成本不花钱")
    s.add_argument("--posts", type=int, help="配合 --dry-run：他大约有多少条作品")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("pick", help="切成 0-1 / 爆款 / 最新 三批")
    s.add_argument("--out", required=True)
    s.add_argument("--n", type=int, default=10)
    s.set_defaults(func=cmd_pick)

    s = sub.add_parser("media", help="下载封面（可选视频）")
    s.add_argument("--out", required=True)
    s.add_argument("--video", action="store_true", help="连视频一起下（很占空间）")
    s.set_defaults(func=cmd_media)

    a = p.parse_args()
    try:
        a.func(a)
    except (AuthError, RuntimeError) as e:
        msg = str(e)
        if "402" in msg or "Insufficient balance" in msg:
            die("这个接口不吃免费额度，要 TikHub 账户里有余额才能调。\n"
                "   实测（2026-09-03）：免费额度只够跑**抖音**（web + search）；\n"
                "   **小红书和视频号的接口一律要充值**。\n"
                "   充值：https://user.tikhub.io/users/add_credit （$0.001/次请求）\n"
                "   不想充：这个平台走 B 轨（轻抖手动），见技能里的〈抓取手册〉。")
        if "401" in msg or "403" in msg:
            die(f"key 不对或没权限：{msg[:200]}")
        die(msg)


if __name__ == "__main__":
    main()
