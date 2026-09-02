#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Grab the day's news from authoritative, free sources and write news.json.

Sources (all free, no paid plan needed):
  1. 中国政府网·国务院政策文件库  —— 官方接口，自带发文单位与发文字号
  2. 中新网 7 个频道 RSS + 人民日报 + 央视新闻  —— 实测 24 小时内条目、带正文
  3. GDELT（免费、无需 Key）—— 作为人民网/新华网等站的发现层；
     这两家自有 RSS 已停更，但网站每日更新，故经 GDELT 索引后再拉正文。
     取不到正文的条目直接丢弃，只保留能支撑客观概括的素材。

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
    # 生活休闲 / 服务资讯类（非专业新闻，按钟林速闻既有标准剔除）
    "预警信号", "气象台", "避暑", "文旅", "景区", "古镇", "美食", "打卡",
    "萌宠", "萌娃", "宠物", "走红", "吸睛", "解锁", "新体验", "花海",
    "赏花", "采摘", "夜市", "奇闻", "趣事", "搞笑", "短视频", "赶海",
]

# 频道优先级：数值越小越靠前。专业源全在第一档。
SOURCE_PRIORITY = {
    "中国政府网·国务院政策文件库": 0,
    "中新网·要闻": 1,
    "中新网·财经": 1,
    "中新网·国内": 1,
    "中新网·国际": 1,
    "人民日报": 1,
    "央视新闻": 1,
    "中新网·社会": 3,
    "中新网·滚动": 4,
    "中新网·健康": 5,
}
DEFAULT_PRIORITY = 4

# GDELT 来源域名按同一套优先级归类
GDELT_DOMAIN_PRIORITY = [
    (("gov.cn", "chinatax.gov.cn", "samr.gov.cn", "cnipa.gov.cn"), 0),
    (("people.com.cn", "xinhuanet.com", "news.cn"), 2),
    (("ce.cn",), 1),
]


def priority_of(item):
    name = item.get("source_name", "")
    if name in SOURCE_PRIORITY:
        return SOURCE_PRIORITY[name]
    for domains, prio in GDELT_DOMAIN_PRIORITY:
        if any(d in name for d in domains):
            return prio
    return DEFAULT_PRIORITY

# 实时性已实测（2026-09-02）：以下源 24 小时内条目占比高、且带正文。
# 人民网/新华网自有 RSS 已停更（内容为 2020 年旧闻、无 pubDate），故不采用；
# 这两家的当日新闻改由下面的 GDELT 发现层抓取。
RSS_SOURCES = [
    {"name": "中新网·要闻", "url": "http://www.chinanews.com/rss/importnews.xml"},
    {"name": "中新网·国内", "url": "http://www.chinanews.com/rss/china.xml"},
    {"name": "中新网·财经", "url": "http://www.chinanews.com/rss/finance.xml"},
    {"name": "中新网·国际", "url": "http://www.chinanews.com/rss/world.xml"},
    {"name": "中新网·社会", "url": "http://www.chinanews.com/rss/society.xml"},
    {"name": "中新网·滚动", "url": "http://www.chinanews.com/rss/scroll-news.xml"},
    {"name": "中新网·健康", "url": "http://www.chinanews.com/rss/health.xml"},
    {"name": "人民日报", "url": "https://plink.anyfeeder.com/people-daily"},
    {"name": "央视新闻", "url": "https://plink.anyfeeder.com/weixin/cctvnewscenter"},
]

# 国务院政策文件库（中国政府网官方接口，免费、无需 Key，返回发文单位与发文字号）
GOV_POLICY_API = "https://sousuo.www.gov.cn/search-gov/data"
GOV_POLICY_LIMIT = 4

# GDELT：免费、无需 Key 的全球新闻数据库。用作人民网/新华网等站的「发现层」——
# 这些站点自有 RSS 已失效，但网站本身每日更新。取不到就静默跳过，不影响主流程。
GDELT_API = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_DOMAINS = [
    "people.com.cn", "xinhuanet.com", "news.cn", "gov.cn",
    "ce.cn", "chinanews.com.cn", "chinatax.gov.cn", "samr.gov.cn",
]

LINK_FETCH_ALLOWLIST = [
    "chinanews.com",
    "chinanews.com.cn",
    "chinadaily.com.cn",
    "xinhuanet.com",
    "news.cn",
    "people.com.cn",
    "ce.cn",
    "gov.cn",
    "cctv.com",
    "cntv.cn",
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
    if any(kw in title for kw in SOFT_NEWS_KEYWORDS):
        return True
    # 以问号收尾的中文标题多为评论、情感类稿件，非事实新闻
    return title.rstrip().endswith(("？", "?"))


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


def fetch_gov_policy():
    """国务院政策文件库——权威、免费、无 Key，且自带发文单位与发文字号。

    只拼接接口返回的真实元数据，不做任何推断或补充。
    """
    try:
        r = requests.get(
            GOV_POLICY_API,
            params={
                "t": "zhengcelibrary_gw", "q": "", "sort": "pubtime",
                "sortType": "1", "searchfield": "title",
                "p": "1", "n": str(GOV_POLICY_LIMIT),
            },
            headers={"User-Agent": "zhonglin-news-bot/1.0"},
            timeout=25,
        )
        r.raise_for_status()
        rows = r.json()["searchVO"]["catMap"]["gongwen"]["listVO"]
    except Exception as e:
        print(f"gov policy fetch failed: {e}", file=sys.stderr)
        return []

    out = []
    for a in rows[:GOV_POLICY_LIMIT]:
        title = strip_html(a.get("title") or "").strip()
        if not title or is_soft_news(title):
            continue
        puborg = (a.get("puborg") or "").strip()          # 发文单位
        pcode = (a.get("pcode") or "").strip()            # 发文字号
        pubtime = (a.get("pubtimeStr") or "").strip()     # 发布日期
        summary = strip_html(a.get("summary") or "").strip()
        # body 只由接口返回的真实字段拼成，供 AI 概括时取材，不做任何推断补充
        body = "；".join(
            p for p in [
                f"发文单位：{puborg}" if puborg else "",
                f"发文字号：{pcode}" if pcode else "",
                f"发布日期：{pubtime}" if pubtime else "",
                f"标题：{title}",
                f"原文摘要：{summary[:400]}" if summary else "",
            ] if p
        )
        out.append({
            "title": title,
            "link": a.get("url") or "https://www.gov.cn/zhengce/zuixin.htm",
            "body": body,
            "pub_dt": None,
            "source_name": "中国政府网·国务院政策文件库",
        })
    if out:
        print(f"gov policy: {len(out)} items", file=sys.stderr)
    return out


def fetch_gdelt():
    """GDELT 发现层：抓取人民网/新华网等站当日新闻，需成功取到正文才保留。

    GDELT 免费且无需 Key；不可达时静默返回空列表，不影响主流程。
    """
    try:
        r = requests.get(
            GDELT_API,
            params={
                "query": "sourcelang:chinese", "mode": "ArtList",
                "maxrecords": "75", "format": "json", "timespan": "1d",
                "sort": "DateDesc",
            },
            headers={"User-Agent": "zhonglin-news-bot/1.0"},
            timeout=25,
        )
        r.raise_for_status()
        arts = r.json().get("articles", [])
    except Exception as e:
        print(f"gdelt unavailable ({type(e).__name__}), skipped", file=sys.stderr)
        return []

    out = []
    for a in arts:
        url = a.get("url") or ""
        domain = a.get("domain") or ""
        if not any(d in domain for d in GDELT_DOMAINS):
            continue
        title = (a.get("title") or "").strip()
        if not title or is_soft_news(title):
            continue
        body = strip_html(fetch_article_body(url) or "")
        # 取不到正文就丢弃：只有标题的条目无法支撑客观概括
        if len(body) < MIN_BODY_LEN:
            continue
        pub_dt = None
        try:
            pub_dt = datetime.strptime(
                a.get("seendate", ""), "%Y%m%dT%H%M%SZ"
            ).replace(tzinfo=timezone.utc)
        except Exception:
            pass
        out.append({
            "title": title,
            "link": url,
            "body": body[:MAX_BODY_LEN],
            "pub_dt": pub_dt,
            "source_name": f"GDELT·{domain}",
        })
        if len(out) >= 8:
            break
    if out:
        print(f"gdelt: {len(out)} items with body", file=sys.stderr)
    return out


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
    """按「政策 > 财经/要闻 > 时政 > 社会」优先级筛选，再按源轮询保证多样性。

    之前单纯按 (优先级, 时间) 排序，会让数量最多的源（如中新网财经）占满版面，
    权威党媒因 RSS 描述偏短反而被挤掉。这里改成：
      1) 先按 (优先级, 时间倒序) 全局排序；
      2) 取前 40 条为候选池，逐条 enrich_body 补齐正文；
      3) 按"优先级升序的源顺序"轮询取条，确保每个源都至少露脸。
    """
    kept = [it for it in items if not is_soft_news(it["title"])]

    def sort_key(x):
        ts = x["pub_dt"].timestamp() if x.get("pub_dt") else 0
        return (priority_of(x), -ts)

    kept.sort(key=sort_key)

    candidates = kept[:40]
    for it in candidates:
        if len(it["body"]) < MAX_BODY_LEN:
            enrich_body(it)

    usable = [it for it in candidates
              if len(it["body"]) >= MIN_BODY_LEN or priority_of(it) <= 1]

    buckets = {}
    for it in usable:
        buckets.setdefault(it.get("source_name", "?"), []).append(it)

    src_min_prio = {s: min(priority_of(it) for it in lst) for s, lst in buckets.items()}
    sources = sorted(buckets.keys(), key=lambda s: src_min_prio[s])

    out = []
    while len(out) < limit and any(buckets[s] for s in sources):
        for s in sources:
            if buckets[s] and len(out) < limit:
                out.append(buckets[s].pop(0))

    for it in out:
        print(f"  body[{len(it['body']):4d}] prio={priority_of(it)} "
              f"{it.get('source_name','')[:14]} | {it['title'][:30]}", file=sys.stderr)
    return out


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


def collect_items():
    """按优先级汇聚：国务院政策 → 中新网/人民日报/央视 RSS → GDELT 发现层。"""
    policy = fetch_gov_policy()

    pool_items = fetch_rss_sources() + fetch_gdelt()
    pool = select_items(dedup(pool_items), limit=max(MAX_SUMMARY_INPUT - len(policy), 6))

    return policy + pool


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "news.json"

    picked = collect_items()
    if not picked:
        raise RuntimeError("No news items returned from any source")

    names = sorted({it.get("source_name", "") for it in picked if it.get("source_name")})
    source_note = "、".join(names) if names else "中新网"
    source_url = next((it.get("link", "") for it in picked if it.get("link")), "")

    # AI 概括失败（额度耗尽/限流）时，降级为原始标题，绝不写入无来源内容
    summaries = summarize_with_zhipu(picked) or [it["title"] for it in picked]

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
        "raw_count": len(picked),
        "kept_count": len(items),
        "items": items,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(items)} items to {out_path} (source: {source_note})")


if __name__ == "__main__":
    main()
