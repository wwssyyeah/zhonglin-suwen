#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Render daily news onto the original template image.
Outputs output.png ready for WeChat webhook push.
"""
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from PIL import Image, ImageDraw, ImageFont

WEATHER_CODE_CN = {
    0: "晴", 1: "晴", 2: "多云", 3: "阴",
    45: "雾", 48: "雾",
    51: "小雨", 53: "小雨", 55: "中雨", 56: "冻雨", 57: "冻雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "小雪",
    80: "阵雨", 81: "阵雨", 82: "雷阵雨", 85: "阵雪", 86: "阵雪",
    95: "雷阵雨", 96: "雷阵雨", 99: "雷暴",
}


def load_config():
    with open("config.json", "r", encoding="utf-8") as f:
        return json.load(f)


def load_news(path="news.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_font(fonts_cfg, size):
    candidates = []
    if fonts_cfg.get("path"):
        candidates.append(fonts_cfg["path"])
    import platform
    system = platform.system()
    if system == "Windows":
        candidates.extend(fonts_cfg["fallback_windows"])
    elif system == "Linux":
        candidates.extend(fonts_cfg["fallback_linux"])
    elif system == "Darwin":
        candidates.extend(fonts_cfg["fallback_macos"])
    for p in candidates:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    # last resort: default font (often doesn't support CJK)
    return ImageFont.load_default()


def text_width(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def text_height(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[3] - bbox[1]


def wrap_text(text, max_width, font, draw):
    """Simple greedy char-by-char wrapping."""
    if not text:
        return [""]
    lines = []
    current = ""
    for ch in text:
        test = current + ch
        if text_width(draw, test, font) <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines if lines else [text]


def fetch_weather(loc):
    try:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={loc['latitude']}&longitude={loc['longitude']}"
            "&current=temperature_2m,weather_code"
            "&timezone=Asia%2FShanghai"
        )
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        cur = r.json().get("current", {})
        temp = cur.get("temperature_2m")
        code = cur.get("weather_code")
        desc = WEATHER_CODE_CN.get(code, "阴")
        if temp is None:
            return None
        return f"{int(round(temp))}°C/{desc}"
    except Exception as e:
        print(f"Weather fetch failed: {e}", file=sys.stderr)
        return None


def render_text_region(draw, text, region, font, align="left"):
    x, y = region["x"], region["y"]
    max_w = region["max_width"]
    color = region["color"]
    if align == "right":
        x = x + max_w - text_width(draw, text, font)
    elif align == "center":
        x = x + (max_w - text_width(draw, text, font)) // 2
    draw.text((x, y), text, fill=color, font=font)


def render_news(draw, items, cfg, font):
    x, y = cfg["x"], cfg["y"]
    max_w, max_h = cfg["max_width"], cfg["max_height"]
    line_h = int(cfg["font_size"] * cfg["line_height_ratio"])
    item_gap = cfg["item_gap"]
    color = cfg["color"]
    num_color = cfg["num_color"]
    number_match = re.compile(r"^(\d+\.\s*)(.*)$")

    cur_y = y
    for item in items:
        lines = wrap_text(item, max_w, font, draw)
        # width of a sample number "99. " for hanging indent
        num_sample = "99. "
        num_w = text_width(draw, num_sample, font)
        for i, line in enumerate(lines):
            if i == 0:
                m = number_match.match(line)
                if m:
                    num_part, rest = m.group(1), m.group(2)
                    draw.text((x, cur_y), num_part, fill=num_color, font=font)
                    rest_x = x + text_width(draw, num_part, font)
                    draw.text((rest_x, cur_y), rest, fill=color, font=font)
                else:
                    draw.text((x, cur_y), line, fill=color, font=font)
            else:
                draw.text((x + num_w, cur_y), line, fill=color, font=font)
            cur_y += line_h
        cur_y += item_gap
        # safety: don't draw beyond region
        if cur_y > y + max_h:
            break


def fit_news(items, cfg, fonts_cfg, tmp_img):
    """Reduce font size and/or trim items until they fit."""
    draw = ImageDraw.Draw(tmp_img)
    max_font = cfg["font_size"]
    min_font = 16
    max_h = cfg["max_height"]
    max_w = cfg["max_width"]
    line_h_ratio = cfg["line_height_ratio"]
    item_gap = cfg["item_gap"]

    for attempt_items in [items, items[:-1] if len(items) > 1 else items]:
        for font_size in range(max_font, min_font - 1, -1):
            font = find_font(fonts_cfg, font_size)
            line_h = int(font_size * line_h_ratio)
            total_h = 0
            for item in attempt_items:
                lines = wrap_text(item, max_w, font, draw)
                total_h += len(lines) * line_h + item_gap
            total_h -= item_gap  # remove trailing gap
            if total_h <= max_h:
                return font, attempt_items
        # if still too big, loop will drop another item below
    # progressive trimming
    while len(items) > 1:
        items = items[:-1]
        for font_size in range(max_font, min_font - 1, -1):
            font = find_font(fonts_cfg, font_size)
            line_h = int(font_size * line_h_ratio)
            total_h = sum((len(wrap_text(it, max_w, font, draw)) * line_h + item_gap) for it in items) - item_gap
            if total_h <= max_h:
                return font, items
    font = find_font(fonts_cfg, min_font)
    return font, items[:1]


def main():
    config = load_config()
    news = load_news()
    template_path = config["template"]
    img = Image.open(template_path).convert("RGBA")
    draw = ImageDraw.Draw(img)

    # Date overlay
    if config.get("date", {}).get("enabled"):
        dcfg = config["date"]
        text = news.get("display_date") or datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%m月%d日")
        font = find_font(config["fonts"], dcfg["font_size"])
        render_text_region(draw, text, dcfg, font, dcfg.get("align", "left"))

    # Weather overlay
    if config.get("weather", {}).get("enabled"):
        wcfg = config["weather"]
        weather_text = fetch_weather(wcfg["location"]) or "--°C/--"
        font = find_font(config["fonts"], wcfg["font_size"])
        render_text_region(draw, weather_text, wcfg, font, wcfg.get("align", "right"))

    # News list
    items = news.get("items", [])
    if not items:
        print("No news items", file=sys.stderr)
        sys.exit(1)
    tmp = Image.new("RGBA", (1, 1))
    font, final_items = fit_news(items, config["news"], config["fonts"], tmp)
    render_news(draw, final_items, config["news"], font)

    output_path = config.get("output", "output.png")
    img.save(output_path, "PNG")
    print(f"Saved {output_path}")


if __name__ == "__main__":
    main()
