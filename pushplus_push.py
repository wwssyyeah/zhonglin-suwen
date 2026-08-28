#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通过 PushPlus (pushplus.plus) 把每日新闻图推送到微信。
支持两种模式:
  - 一对一: 仅 PUSHPLUS_TOKEN (用户Token)
  - 一对多: PUSHPLUS_TOKEN (用户Token) + PUSHPLUS_TOPIC (群组编码)
参数: 公开可访问的图片 URL (例如 GitHub Pages 上的 latest.png)
"""
import os
import sys
import requests


def push_image(url):
    token = os.environ.get("PUSHPLUS_TOKEN", "")
    topic = os.environ.get("PUSHPLUS_TOPIC", "")
    if not token:
        print("Missing PUSHPLUS_TOKEN env var", file=sys.stderr)
        sys.exit(1)
    content = (
        "# 钟林速闻 · 每日新闻\n\n"
        f"![钟林速闻]({url})\n\n"
        "> 图片加载失败可在 GitHub Actions 产物中下载 output.png"
    )
    payload = {
        "token": token,
        "title": "钟林速闻 · 每日新闻",
        "content": content,
        "template": "markdown",
    }
    if topic:
        payload["topic"] = topic
    r = requests.post("https://www.pushplus.plus/send", json=payload, timeout=30)
    r.raise_for_status()
    print(r.json())


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else ""
    if not url:
        print("Usage: python pushplus_push.py <public_image_url>", file=sys.stderr)
        sys.exit(1)
    push_image(url)
