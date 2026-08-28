#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fetch daily news from 60s API, optionally polish with Zhipu AI,
and write a news.json for rendering.
"""
import json
import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
import requests

SOFT_NEWS_KEYWORDS = [
    "娱乐", "八卦", "绯闻", "恋情", "结婚", "离婚", "出轨", "明星", "网红",
    "足球", "篮球", "NBA", "CBA", "联赛", "欧冠", "英超", "西甲", "意甲",
    "梅西", "C罗", "詹姆斯", "科比", "运动员", "夺冠", "金牌", "亚军",
    "热播", "综艺", "票房", "追剧", "电影", "上映",
]

ENDPOINTS = [
    "https://60s.viki.moe/v2/60s",
]


def now_sh():
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def filter_soft_news(titles):
    """Remove items that look like soft/entertainment/sports news."""
    kept = []
    for t in titles:
        if any(kw in t for kw in SOFT_NEWS_KEYWORDS):
            continue
        kept.append(t)
    return kept


def fetch_60s():
    today = now_sh().strftime("%Y-%m-%d")
    urls = ENDPOINTS + [
        f"https://60s-static.viki.moe/60s/{today}.json",
        f"https://cdn.jsdelivr.net/gh/vikiboss/60s-static-host@main/static/60s/{today}.json",
    ]
    last_err = None
    for url in urls:
        try:
            r = requests.get(url, timeout=30, headers={"User-Agent": "zhonglin-news-bot/1.0"})
            r.raise_for_status()
            data = r.json()
            # normalize
            if isinstance(data, dict):
                if "data" in data and isinstance(data["data"], dict):
                    payload = data["data"]
                else:
                    payload = data
            else:
                payload = {"news": []}
            news = payload.get("news", [])
            if not news and "data" in data and "news" in data["data"]:
                news = data["data"]["news"]
            return payload, news
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"All 60s endpoints failed. Last error: {last_err}")


def polish_with_zhipu(titles):
    key = os.environ.get("ZHIPU_API_KEY", "")
    if not key:
        return None
    system_msg = (
        "你是一位严谨的新闻编辑。任务：\n"
        "1. 仅基于我提供的标题列表进行事实性润色，不编造任何内容、不添加未在标题中出现的信息；\n"
        "2. 删除明显娱乐八卦、明星绯闻、普通体育赛事等软新闻；保留时政、财经、科技、国际、重大事故/灾害类内容；\n"
        "3. 保持\"标题式\"表达，不要扩写成摘要；\n"
        "4. 为每条保留的新闻添加编号（1. 2. ...），输出为 JSON 数组，每个元素是一条完整字符串。\n"
        "输出只输出 JSON 数组，不要任何解释。"
    )
    user_msg = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
    try:
        r = requests.post(
            "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "glm-4-flash",
                "messages": [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                "temperature": 0.3,
                "max_tokens": 2048,
            },
            timeout=120,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        # try to extract JSON array
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.S).strip()
        # find first [ ... ]
        start = content.find("[")
        end = content.rfind("]")
        if start == -1 or end == -1:
            return None
        arr = json.loads(content[start:end+1])
        if not isinstance(arr, list):
            return None
        # strip numbering if AI already added it (renderer will re-number)
        cleaned = []
        for item in arr:
            s = str(item).strip()
            s = re.sub(r"^\d+[\.、]\s*", "", s)
            if s:
                cleaned.append(s)
        return cleaned
    except Exception as e:
        print(f"Zhipu polish failed: {e}", file=sys.stderr)
        return None


def renumber(items):
    return [f"{i+1}. {t}" for i, t in enumerate(items)]


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "news.json"
    payload, raw = fetch_60s()
    if not raw:
        raise RuntimeError("No news items returned from 60s API")

    filtered = filter_soft_news(raw)
    if not filtered:
        filtered = raw[:]

    polished = polish_with_zhipu(filtered)
    if polished:
        items = polished
    else:
        items = filtered

    items = renumber(items)

    now = now_sh()
    result = {
        "date": now.strftime("%Y-%m-%d"),
        "display_date": f"{now.month}月{now.day}日 周{['一','二','三','四','五','六','日'][now.weekday()]}",
        "lunar_date": payload.get("lunar_date", ""),
        "source": "60s.viki.moe / 60秒读懂世界",
        "source_url": "https://60s.viki.moe/v2/60s",
        "disclaimer": "内容源自公开网络聚合，仅供内部参考，不构成任何投资或决策依据。",
        "raw_count": len(raw),
        "kept_count": len(items),
        "items": items,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Wrote {len(items)} items to {out_path}")


if __name__ == "__main__":
    main()
