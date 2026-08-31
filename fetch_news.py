#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fetch daily news from Chinese RSS feeds (primary) and 60s API (fallback),
summarize with Zhipu AI based on article bodies, and write news.json.

Sources are authoritative Chinese newsrooms (中新网 / 人民日报 / 央视).
Only items with enough body text are sent for summarization, so the AI can
ground every sentence in real material instead of inventing details.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
import requests
import xml.etree.ElementTree as ET

SOFT_NEWS_KEYWORDS = [
    "娱乐", "八卦", "绯闻", "恋情", "结婚", "离婚", "出轨", "明星", "网红",
    "足球", "篮球", "NBA", "CBA", "联赛", "欧冠", "英超", "西甲", "意甲",
    "梅西", "C罗", "詹姆斯", "科比", "运动员", "夺冠", "金牌", "亚军",
    "热播", "综艺", "票房", "追剧", "电影", "上映", "演唱会", "粉丝",
    "横店", "主演", "包邮", "带货", "直播间", "促销", "团购", "秒杀",
]

RSS_SOURCES = [
    {"name": "中新网·滚动", "url": "http://www.chinanews.com/rss/scroll-news.xml"},
    {"name": "中新网·国内", "url": "http://www.chinanews.com/rss/china.xml"},
    {"name": "中新网·财经", "url": "http://www.chinanews.com/rss/finance.xml"},
    {"name": "中新网·国际", "url": "http://www.chinanews.com/rss/world.xml"},
    {"name": "中新网·社会", "url": "http://www.chinanews.com/rss/society.xml"},
    {"name": "人民日报", "url": "https://plink.anyfeeder.com/people-daily"},
    {"name": "央视新闻", "url": "https://plink.anyfeeder.com/weixin/cctvnewscenter"},
]

ENDPOINTS_60S = [
    "https://60s.viki.moe/v2/60s",
]

LINK_FETCH_ALLOWLIST = [
    "chinanews.com",
    "chinadaily.com.cn",
    "xinhuanet.com",
    "news.cn",
    "people.com.cn",
]

MIN_BODY_LEN = 60
MAX_BODY_LEN = 1200
MAX_SUMMARY_INPUT = 14

# Tried in order; glm-4.5-flash routes to the free glm-4.7-flash.
MODELS = ["glm-4.5-flash", "glm-4.5-air", "glm-4-flash"]


def now_sh():
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def strip_html(raw):
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    for old, new in [("&nbsp;", " "), ("&quot;", '"'), ("&amp;", "&"),
                     ("&lt;", "<"), ("&gt;", ">")]:
        text = text.replace(old, new)
    return re.sub(r"\s+", " ", text).strip()


def is_soft_news(title):
    return any(kw in title for kw in SOFT_NEWS_KEYWORDS)


def fetch_url(url, timeout=20):
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "zhonglin-news-bot/1.0"})
        r.raise_for_status()
        return r
    except Exception as e:
        print(f"fetch {url} failed: {e}", file=sys.stderr)
        return None


def fetch_article_body(link):
    if not link:
        return ""
    if not any(d in link for d in LINK_FETCH_ALLOWLIST):
        return ""
    r = fetch_url(link, timeout=10)
    if not r:
        return ""
    try:
        return strip_html(r.text)[:1200]
    except Exception:
        return ""


def parse_pubdate(raw):
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def parse_rss(xml_bytes):
    try:
        root = ET.fromstring(xml_bytes)
    except Exception as e:
        print(f"RSS parse error: {e}", file=sys.stderr)
        return []
    items = []
    for item in root.iter("item"):
        title = strip_html(item.findtext("title", default=""))
        link = item.findtext("link", default="") or ""
        desc = strip_html(item.findtext("description", default=""))
        pub_raw = item.findtext("pubDate", default="")
        if not title:
            continue
        body = desc
        if len(body) < MIN_BODY_LEN and link:
            fetched = fetch_article_body(link)
            if fetched:
                body = fetched
        items.append({
            "title": title,
            "link": link,
            "body": body[:MAX_BODY_LEN],
            "pub_dt": parse_pubdate(pub_raw),
        })
    return items


def fetch_rss_sources():
    all_items = []
    for src in RSS_SOURCES:
        r = fetch_url(src["url"], timeout=20)
        if not r:
            continue
        items = parse_rss(r.content)
        for it in items:
            it["source_name"] = src["name"]
        all_items.extend(items)
        print(f"RSS {src['name']}: {len(items)} items", file=sys.stderr)
    return all_items


def dedup(items):
    seen = set()
    out = []
    for it in items:
        key = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", it["title"])
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def enrich_body(it):
    """Fetch the full article when the RSS description is thin."""
    if it["link"] and any(d in it["link"] for d in LINK_FETCH_ALLOWLIST):
        fetched = fetch_article_body(it["link"])
        if fetched and len(fetched) > len(it["body"]):
            it["body"] = fetched[:MAX_BODY_LEN]
    return it


def select_items(items, limit=MAX_SUMMARY_INPUT):
    """Prefer non-soft news with enough body text, newest first."""
    kept = [it for it in items if not is_soft_news(it["title"])]
    rich = [it for it in kept if len(it["body"]) >= MIN_BODY_LEN]
    thin = [it for it in kept if len(it["body"]) < MIN_BODY_LEN]
    rich.sort(key=lambda x: x["pub_dt"] or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
    thin.sort(key=lambda x: x["pub_dt"] or datetime(1970, 1, 1, tzinfo=timezone.utc), reverse=True)
    ordered = (rich + thin)[:limit]
    # pull full article text so the AI has enough material for 3-5 sentences
    for it in ordered:
        enrich_body(it)
        print(f"  body[{len(it['body']):4d}] {it['title'][:30]}", file=sys.stderr)
    return ordered


def fetch_60s():
    today = now_sh().strftime("%Y-%m-%d")
    urls = ENDPOINTS_60S + [
        f"https://60s-static.viki.moe/60s/{today}.json",
        f"https://cdn.jsdelivr.net/gh/vikiboss/60s-static-host@main/static/60s/{today}.json",
    ]
    last_err = None
    for url in urls:
        try:
            r = requests.get(url, timeout=30, headers={"User-Agent": "zhonglin-news-bot/1.0"})
            r.raise_for_status()
            data = r.json()
            payload = data.get("data", data) if isinstance(data, dict) else {"news": []}
            return payload, payload.get("news", [])
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"All 60s endpoints failed. Last error: {last_err}")


def summarize_one(item, key, model):
    """Summarize a single news item; returns summary string or raises."""
    system_msg = (
        "你是一位严谨的新闻编辑。请根据下面新闻的【标题】和【正文】，"
        "写一段 25 到 50 个字的客观概括（通常 1 到 2 句话）。"
        "只使用材料中出现的事实（日期、地点、机构、人名、数字、政策名称），"
        "不编造、不推测、不评论、不添加材料之外的任何信息。\n"
        "直接输出概括文本，不要编号前缀，不要 JSON，不要解释。"
    )
    user_msg = (
        f"标题：{item['title']}\n"
        f"来源：{item.get('source_name', '')}\n"
        f"正文：{item['body']}"
    )
    r = requests.post(
        "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.3,
            "max_tokens": 256,
        },
        # short read timeout: blocked/sensitive items hang instead of erroring,
        # so fail fast and fall back to the title rather than stalling the run.
        timeout=(10, 25),
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"].strip()
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.S).strip()
    content = re.sub(r"^\d+[\.、]\s*", "", content)
    return content


def _is_rate_limit(exc):
    if isinstance(exc, requests.HTTPError):
        return getattr(exc.response, "status_code", None) == 429
    return False


def summarize_with_zhipu(items):
    """Summarize each item individually.

    - 200 with a summary -> use it.
    - 429 (rate limit) -> back off and retry the next model.
    - 400 content-filter / timeout / other -> give up on this item and fall
      back to its title (sensitive items make the API hang, so we must not
      retry them across models or the whole run stalls).
    """
    key = os.environ.get("ZHIPU_API_KEY", "")
    if not key or not items:
        return None

    import time
    results = []
    for i, it in enumerate(items):
        summary = None
        for model in MODELS:
            try:
                summary = summarize_one(it, key, model)
                if summary:
                    print(
                        f"summarized item {i + 1}/{len(items)} with {model}: "
                        f"{summary[:40]}...",
                        file=sys.stderr,
                    )
                    break
            except Exception as e:
                if _is_rate_limit(e):
                    print(f"{model} item {i + 1} rate limited, retry", file=sys.stderr)
                    time.sleep(5)
                    continue
                # blocked by content filter / network timeout -> fall back to title
                print(f"{model} item {i + 1} skipped ({type(e).__name__})", file=sys.stderr)
                break
        results.append(summary or it["title"])
        if i < len(items) - 1:
            time.sleep(0.5)

    if results:
        n_ok = sum(1 for s, it in zip(results, items) if s != it["title"])
        print(f"summarized {n_ok}/{len(items)} items with Zhipu", file=sys.stderr)
    return results if results else None


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "news.json"

    # 1) RSS primary
    rss_items = select_items(dedup(fetch_rss_sources()))
    summaries = None
    source_note = "60s.viki.moe / 60秒读懂世界"
    source_url = "https://60s.viki.moe/v2/60s"

    if rss_items:
        summaries = summarize_with_zhipu(rss_items)
        if summaries:
            names = sorted({it["source_name"] for it in rss_items if it.get("source_name")})
            source_note = "、".join(names)
            source_url = rss_items[0].get("link", "")

    # 2) Fallback: 60s
    if not summaries:
        payload, raw = fetch_60s()
        if not raw:
            raise RuntimeError("No news items returned from any source")
        titles = [t for t in raw if not is_soft_news(t)]
        if not titles:
            titles = raw[:]
        summaries = titles
        if rss_items:
            # keep RSS titles if AI failed but RSS worked
            summaries = [it["title"] for it in rss_items]
            names = sorted({it["source_name"] for it in rss_items if it.get("source_name")})
            source_note = "、".join(names)
            source_url = rss_items[0].get("link", "")

    # 3) Renumber
    items = [f"{i + 1}. {t}" for i, t in enumerate(summaries)]

    now = now_sh()
    weekday_cn = ['一', '二', '三', '四', '五', '六', '日'][now.weekday()]
    result = {
        "date": now.strftime("%Y-%m-%d"),
        "display_date": f"{now.year}年{now.month}月{now.day}日 周{weekday_cn}",
        "source": source_note,
        "source_url": source_url,
        "disclaimer": "内容源自公开网络聚合，仅供内部参考，不构成任何投资或决策依据。",
        "raw_count": len(rss_items),
        "kept_count": len(items),
        "items": items,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(items)} items to {out_path} (source: {source_note})")


if __name__ == "__main__":
    main()
