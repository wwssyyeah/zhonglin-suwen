#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Render daily news onto the cleaned template image (template_clean.png).
- Date / weather icon / weather text are fetched live (Suzhou) and drawn into
  the exact rectangles provided by the user.
- News list is auto-fitted to fill the white card with EXACT height accounting,
  so it never overflows the given region.

Changes vs prior version:
  * measure_height() now uses real font metrics (ascent+descent) for the last
    line, plus a 4 px safety margin, so the chosen layout is guaranteed to
    stay inside the region.
  * fit_news() now distributes leftover space to gap AND line height, then
    re-validates the total. If still over, line_h is pulled back. Last item
    is trimmed only as a final safety net.
  * render_news() pre-checks each line / item against the bottom boundary
    before drawing, so a misbehaving measure can never paint below max_y.
  * render_text_region() supports a stroke_width so date and weather text
    render as bold (PIL doesn't have real bold for the 宋体 file, stroke
    width gives a consistent cross-platform "粗" effect).
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

SAFETY_PX = 4  # safety margin (px) reserved below the last line of text
HORIZ_SAFETY_PX = 6  # horizontal safety (px) reserved on the right of text


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


def text_height(font):
    """Real pixel height of one line of text: ascent + descent."""
    a, d = font.getmetrics()
    return a + d


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


def _split_num(text):
    """Return (num_part, rest) if text starts with 'N. ', else (None, text)."""
    m = re.match(r"^(\d+\.\s*)(.*)$", text)
    if m:
        return m.group(1), m.group(2)
    return None, text


def continuation_indent(cfg, font, draw):
    """Left offset (px from region x) used for continuation lines.

    cfg["indent"]:
      "left" -> 0, every body line starts flush at the region's left edge.
      "hang" -> width of "99. ", i.e. hanging indent under the number column.
    """
    if cfg.get("indent", "left") == "hang":
        return text_width(draw, "99. ", font)
    return 0


def wrap_item(text, first_w, cont_w, font, draw):
    """Split one news item into (num_part, [body lines]).

    The first line is wrapped to `first_w` (it sits right after the "N. "
    prefix), every continuation line to `cont_w`. Both callers (fit and
    render) must use this so the measured height matches what is painted.
    """
    num_part, body = _split_num(text)
    lines = []
    cur = ""
    limit = first_w
    for ch in body:
        test = cur + ch
        if text_width(draw, test, font) <= limit:
            cur = test
        else:
            lines.append(cur)
            cur = ch
            limit = cont_w
    if cur:
        lines.append(cur)
    return (num_part or ""), (lines if lines else [""])


def item_line_widths(item, cfg, font, draw):
    """Return (num_part, num_actual_w, cont_off, first_w, cont_w) for an item."""
    num_part, _ = _split_num(item)
    num_actual_w = text_width(draw, num_part, font) if num_part else 0
    cont_off = continuation_indent(cfg, font, draw)
    max_w = cfg["max_width"]
    first_w = max_w - num_actual_w - HORIZ_SAFETY_PX
    cont_w = max_w - cont_off - HORIZ_SAFETY_PX
    return num_part or "", num_actual_w, cont_off, first_w, cont_w


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


def render_text_region(draw, text, region, font, align="left", color=None, stroke_width=0):
    x, y = region["x"], region["y"]
    max_w = region["max_width"]
    color = color or region["color"]
    if align == "right":
        x = x + max_w - text_width(draw, text, font)
    elif align == "center":
        x = x + (max_w - text_width(draw, text, font)) // 2
    if stroke_width > 0:
        draw.text((x, y), text, fill=color, font=font,
                  stroke_width=stroke_width, stroke_fill=color)
    else:
        draw.text((x, y), text, fill=color, font=font)


def render_news(draw, items, cfg, font, line_h, item_gap):
    x, y = cfg["x"], cfg["y"]
    max_w = cfg["max_width"]
    max_y = y + cfg["max_height"]  # 预留 SAFETY_PX 由 fit_news 负责
    color = cfg["color"]
    num_color = cfg["num_color"]
    th = text_height(font)

    cur_y = y

    for item in items:
        num_part, num_actual_w, cont_off, first_w, cont_w = item_line_widths(
            item, cfg, font, draw)
        _, body_lines = wrap_item(item, first_w, cont_w, font, draw)
        if cur_y + th > max_y:
            return
        for i, line in enumerate(body_lines):
            if cur_y + th > max_y:
                return
            if i == 0:
                if num_part:
                    draw.text((x, cur_y), num_part, fill=num_color, font=font)
                    draw.text((x + num_actual_w, cur_y), line, fill=color, font=font)
                else:
                    draw.text((x, cur_y), line, fill=color, font=font)
            else:
                draw.text((x + cont_off, cur_y), line, fill=color, font=font)
            cur_y += line_h
        # Gap check: only add the inter-item gap if the next item's first
        # line (line_h worth + text_h) would still fit.
        if cur_y + item_gap + th > max_y:
            return
        cur_y += item_gap


def actual_render_height(items, cfg, font, line_h, gap, draw):
    """Exact render height: (n_lines-1)*line_h + text_h + (n_items-1)*gap + safety.

    Wraps each item exactly the way render_news() does (first line vs
    continuation line have different available widths), so the measured
    height always matches what gets painted.
    """
    n_lines = 0
    for it in items:
        _, _, _, first_w, cont_w = item_line_widths(it, cfg, font, draw)
        n_lines += len(wrap_item(it, first_w, cont_w, font, draw)[1])
    if n_lines == 0:
        return 0
    th = text_height(font)
    n_items = len(items)
    gaps = max(0, n_items - 1) * gap
    return (n_lines - 1) * line_h + th + gaps + SAFETY_PX


def fit_news(items, cfg, fonts_cfg):
    max_h = cfg["max_height"]
    max_w = cfg["max_width"]
    base_ratio = cfg["line_height_ratio"]
    base_gap = cfg["item_gap"]
    fmax = cfg.get("font_size_max", cfg["font_size"])
    fmin = cfg.get("font_size_min", 16)
    max_ratio = cfg.get("max_line_height_ratio", base_ratio)
    max_gap = cfg.get("max_item_gap", base_gap)

    tmp = Image.new("RGBA", (1, 1))
    draw0 = ImageDraw.Draw(tmp)

    def lines_per_item(fs):
        font = find_font(fonts_cfg, fs)
        counts = []
        for it in items:
            _, _, _, fw, cw = item_line_widths(it, cfg, font, draw0)
            counts.append(len(wrap_item(it, fw, cw, font, draw0)[1]))
        return counts, font

    # 1) pick the largest font whose actual render height (with base gap) fits.
    chosen_fs = fmin
    chosen_font = find_font(fonts_cfg, fmin)
    for fs in range(fmax, fmin - 1, -1):
        lpe, f = lines_per_item(fs)
        line_h = int(fs * base_ratio)
        h = actual_render_height(items, cfg, f, line_h, base_gap, draw0)
        if h <= max_h:
            chosen_fs = fs
            chosen_font = f
            break

    line_h = int(chosen_fs * base_ratio)
    cur_h = actual_render_height(items, cfg, chosen_font, line_h, base_gap, draw0)
    leftover = max_h - cur_h

    # 2) under-fill: spread gap first, then line height, then re-validate.
    if leftover > 2 * SAFETY_PX and len(items) > 1:
        n_gaps = max(1, len(items) - 1)
        extra_gap = int(min(leftover / n_gaps, max_gap - base_gap))
        if extra_gap > 0:
            gap = base_gap + extra_gap
            # re-measure with new gap, then add the rest to line_h
            h2 = actual_render_height(items, cfg, chosen_font, line_h, gap, draw0)
            leftover2 = max_h - h2
            if leftover2 > 0:
                lpe, _ = lines_per_item(chosen_fs)
                n_lines = sum(lpe)
                if n_lines > 1:
                    # Distribute leftover2 across (n_lines-1) line spacings.
                    inc_ratio = leftover2 / (chosen_fs * (n_lines - 1))
                    ratio = min(base_ratio + inc_ratio, max_ratio)
                    line_h = int(chosen_fs * ratio)
            # final safety: pull line_h back if still over
            h3 = actual_render_height(items, cfg, chosen_font, line_h, gap, draw0)
            while h3 > max_h and line_h > int(chosen_fs * base_ratio):
                line_h -= 1
                h3 = actual_render_height(items, cfg, chosen_font, line_h, gap, draw0)
            return chosen_font, items, line_h, gap

    return chosen_font, items, line_h, base_gap


def build_display_date(news):
    if news.get("display_date"):
        return news["display_date"]
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    return f"{now.year}年{now.month}月{now.day}日 周{WEEKDAY_CN[now.weekday()]}"


def bold_stroke_width(font, region):
    """Decide stroke_width for a 'bold' region. Returns 0 if not bold."""
    if not region.get("bold"):
        return 0
    # ~8% of font size, clamped 1..3. 1 too thin to see, >3 starts to blur
    # Chinese strokes. Tested on simsun at fs=34 -> 2, fs=26 -> 2.
    fs = font.size
    sw = int(fs * 0.08)
    return max(1, min(3, sw))


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
        sw = bold_stroke_width(font, dcfg)
        render_text_region(draw, text, dcfg, font, dcfg.get("align", "left"),
                           stroke_width=sw)

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
            sw = bold_stroke_width(font, tcfg)
            render_text_region(draw, text, tcfg, font, tcfg.get("align", "left"),
                               stroke_width=sw)

    # 3) News list (exact-fit)
    items = news.get("items", [])
    if not items:
        print("No news items", file=sys.stderr)
        sys.exit(1)
    font, final_items, line_h, item_gap = fit_news(items, config["news"], config["fonts"])
    render_news(draw, final_items, config["news"], font, line_h, item_gap)

    output_path = config.get("output", "output.png")
    img.save(output_path, "PNG")
    print(f"Saved {output_path} | items={len(final_items)} | font={font.size} | "
          f"line_h={line_h} | gap={item_gap} | text_h={text_height(font)}")


if __name__ == "__main__":
    main()
