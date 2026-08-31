#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Render daily news onto the cleaned template image (template_clean.png).
- Date / weather icon / weather text are fetched live (Suzhou) and drawn into
  the exact rectangles provided by the user.
- News list is auto-fitted to fill the white card:
    * if it underfills, increase font/line spacing/gap to spread out;
    * if it overflows, shrink font while keeping all items (dense is OK).
Outputs output.png ready for PushPlus push.
"""
import json
import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from PIL import Image, ImageDraw, ImageFont

WEATHER_CODE_CN = {
    0: ("晴", "clear"), 1: ("晴", "clear"), 2: ("多云", "cloudy"),
    3: ("阴", "overcast"),
    45: ("雾", "overcast"), 48: ("雾", "overcast"),
    51: ("小雨", "rain"), 53: ("小雨", "rain"), 55: ("中雨", "rain"),
    56: ("冻雨", "rain"), 57: ("冻雨", "rain"),
    61: ("小雨", "rain"), 63: ("中雨", "rain"), 65: ("大雨", "rain"),
    66: ("冻雨", "rain"), 67: ("冻雨", "rain"),
    71: ("小雪", "snow"), 73: ("中雪", "snow"), 75: ("大雪", "snow"),
    77: ("小雪", "snow"),
    80: ("阵雨", "rain"), 81: ("阵雨", "rain"), 82: ("雷阵雨", "thunder"),
    85: ("阵雪", "snow"), 86: ("阵雪", "snow"),
    95: ("雷阵雨", "thunder"), 96: ("雷阵雨", "thunder"), 99: ("雷暴", "thunder"),
}
WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]


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
    return ImageFont.load_default()


def text_width(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def wrap_text(text, max_width, font, draw):
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
        if temp is None or code is None:
            return None
        desc, cat = WEATHER_CODE_CN.get(code, ("阴", "overcast"))
        return {"temp": int(round(temp)), "desc": desc, "cat": cat}
    except Exception as e:
        print(f"Weather fetch failed: {e}", file=sys.stderr)
        return None


def draw_weather_icon(draw, cat, cx, cy, s):
    import math
    if cat == "clear":
        r = s * 0.32
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 200, 40))
        for k in range(8):
            a = k * math.pi / 4
            x1 = cx + (r + 4) * math.cos(a)
            y1 = cy + (r + 4) * math.sin(a)
            x2 = cx + (r + s * 0.22) * math.cos(a)
            y2 = cy + (r + s * 0.22) * math.sin(a)
            draw.line([(x1, y1), (x2, y2)], fill=(255, 200, 40), width=max(2, int(s * 0.06)))
    elif cat in ("cloudy", "overcast"):
        col = (240, 245, 250) if cat == "cloudy" else (210, 218, 228)
        r = s * 0.26
        draw.ellipse([cx - r, cy - r * 0.4, cx + r, cy + r * 0.9], fill=col)
        draw.ellipse([cx - r * 0.6, cy - r * 0.7, cx + r * 0.8, cy + r * 0.4], fill=col)
        draw.ellipse([cx - r * 1.1, cy - r * 0.2, cx + r * 0.5, cy + r], fill=col)
    elif cat == "rain":
        r = s * 0.24
        col = (225, 232, 240)
        draw.ellipse([cx - r, cy - r * 0.5, cx + r, cy + r * 0.7], fill=col)
        draw.ellipse([cx - r * 0.5, cy - r * 0.9, cx + r * 0.9, cy + r * 0.1], fill=col)
        for i in range(3):
            xoff = (i - 1) * r * 0.6
            draw.line([(cx + xoff, cy + r * 0.7), (cx + xoff - r * 0.25, cy + r * 1.15)],
                      fill=(80, 145, 235), width=max(2, int(s * 0.05)))
    elif cat == "snow":
        r = s * 0.24
        col = (240, 246, 252)
        draw.ellipse([cx - r, cy - r * 0.5, cx + r, cy + r * 0.7], fill=col)
        draw.ellipse([cx - r * 0.5, cy - r * 0.9, cx + r * 0.9, cy + r * 0.1], fill=col)
        for i in range(3):
            xoff = (i - 1) * r * 0.6
            draw.ellipse([cx + xoff - 2, cy + r * 0.9, cx + xoff + 2, cy + r * 1.15], fill=(250, 250, 255))
    elif cat == "thunder":
        r = s * 0.24
        col = (200, 208, 218)
        draw.ellipse([cx - r, cy - r * 0.5, cx + r, cy + r * 0.7], fill=col)
        draw.ellipse([cx - r * 0.5, cy - r * 0.9, cx + r * 0.9, cy + r * 0.1], fill=col)
        draw.polygon([(cx + r * 0.1, cy + r * 0.6), (cx - r * 0.4, cy + r * 1.05),
                      (cx + r * 0.05, cy + r * 1.05), (cx - r * 0.1, cy + r * 1.5)],
                     fill=(255, 210, 40))


def render_text_region(draw, text, region, font, align="left", color=None):
    x, y = region["x"], region["y"]
    max_w = region["max_width"]
    color = color or region["color"]
    if align == "right":
        x = x + max_w - text_width(draw, text, font)
    elif align == "center":
        x = x + (max_w - text_width(draw, text, font)) // 2
    draw.text((x, y), text, fill=color, font=font)


def render_news(draw, items, cfg, font, line_h, item_gap):
    x, y = cfg["x"], cfg["y"]
    max_w = cfg["max_width"]
    color = cfg["color"]
    num_color = cfg["num_color"]
    number_match = re.compile(r"^(\d+\.\s*)(.*)$")

    cur_y = y
    for item in items:
        lines = wrap_text(item, max_w, font, draw)
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
        if cur_y > y + cfg["max_height"]:
            break


def measure_height(items, cfg, fonts_cfg, font_size, line_h, item_gap):
    tmp = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(tmp)
    font = find_font(fonts_cfg, font_size)
    x, y = cfg["x"], cfg["y"]
    max_w = cfg["max_width"]
    cur_y = y
    for item in items:
        lines = wrap_text(item, max_w, font, draw)
        cur_y += len(lines) * line_h + item_gap
    return cur_y - y - item_gap


def fit_news(items, cfg, fonts_cfg):
    """Bidirectional fit:
    - If content overflows, shrink font (keep all items, dense OK).
    - If content underfills, increase font / gap / line spacing to spread out.
    """
    max_h = cfg["max_height"]
    max_w = cfg["max_width"]
    base_ratio = cfg["line_height_ratio"]
    base_gap = cfg["item_gap"]
    fmax = cfg.get("font_size_max", cfg["font_size"])
    fmin = cfg.get("font_size_min", 16)
    max_ratio = cfg.get("max_line_height_ratio", base_ratio)
    max_gap = cfg.get("max_item_gap", base_gap)

    # 1) find largest font that fits with base spacing (preserve all items)
    chosen_font = None
    for fs in range(fmax, fmin - 1, -1):
        line_h = int(fs * base_ratio)
        h = measure_height(items, cfg, fonts_cfg, fs, line_h, base_gap)
        if h <= max_h:
            chosen_font = find_font(fonts_cfg, fs)
            chosen_fs = fs
            break

    if chosen_font is None:
        # even min font overflows -> trim items as last resort
        chosen_fs = fmin
        line_h = int(chosen_fs * base_ratio)
        while len(items) > 1 and measure_height(items, cfg, fonts_cfg, chosen_fs, line_h, base_gap) > max_h:
            items = items[:-1]
        return find_font(fonts_cfg, chosen_fs), items, line_h, base_gap

    line_h = int(chosen_fs * base_ratio)
    h = measure_height(items, cfg, fonts_cfg, chosen_fs, line_h, base_gap)
    leftover = max_h - h

    # 2) if underfilled, spread out: first gap, then line height
    if leftover > 0 and len(items) > 1:
        n_gaps = max(1, len(items) - 1)
        extra_gap = int(min(leftover / n_gaps, max_gap - base_gap))
        gap = base_gap + extra_gap
        h2 = measure_height(items, cfg, fonts_cfg, chosen_fs, line_h, gap)
        leftover2 = max_h - h2
        if leftover2 > 0:
            n_lines = sum(len(wrap_text(item, max_w, chosen_font, ImageDraw.Draw(Image.new("RGBA", (1, 1)))))
                           for item in items)
            if n_lines > 0:
                extra_per_line = leftover2 / n_lines
                ratio = base_ratio + extra_per_line / chosen_fs
                ratio = min(ratio, max_ratio)
                line_h = int(chosen_fs * ratio)
        return chosen_font, items, line_h, gap

    return chosen_font, items, line_h, base_gap


def build_display_date(news):
    if news.get("display_date"):
        return news["display_date"]
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    return f"{now.year}年{now.month}月{now.day}日 周{WEEKDAY_CN[now.weekday()]}"


def main():
    config = load_config()
    news = load_news()
    template_path = config["template"]
    img = Image.open(template_path).convert("RGBA")
    draw = ImageDraw.Draw(img)

    # 1) Date overlay (live)
    if config.get("date", {}).get("enabled"):
        dcfg = config["date"]
        text = build_display_date(news)
        font = find_font(config["fonts"], dcfg["font_size"])
        render_text_region(draw, text, dcfg, font, dcfg.get("align", "left"))

    # 2) Weather overlay (live Suzhou) + icon
    if config.get("weather", {}).get("enabled"):
        wcfg = config["weather"]
        wx = fetch_weather(wcfg["location"])
        if wx:
            ic = wcfg.get("icon", {})
            if ic:
                draw_weather_icon(draw, wx["cat"], ic["x"] + ic["size"] // 2,
                                  ic["y"] + ic["size"] // 2, ic["size"])
            tcfg = wcfg.get("text", {})
            text = f"{wx['desc']} {wx['temp']}°C"
            font = find_font(config["fonts"], tcfg["font_size"])
            render_text_region(draw, text, tcfg, font, tcfg.get("align", "left"))

    # 3) News list (bidirectional fit)
    items = news.get("items", [])
    if not items:
        print("No news items", file=sys.stderr)
        sys.exit(1)
    font, final_items, line_h, item_gap = fit_news(items, config["news"], config["fonts"])
    render_news(draw, final_items, config["news"], font, line_h, item_gap)

    output_path = config.get("output", "output.png")
    img.save(output_path, "PNG")
    print(f"Saved {output_path} | items={len(final_items)} | font={font.size} | line_h={line_h} | gap={item_gap}")


if __name__ == "__main__":
    main()
