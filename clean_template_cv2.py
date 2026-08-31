#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Remove the static date / weather icon / weather text from template.png using
the exact rectangles provided by the user, then heal with OpenCV inpainting.
Produces template_clean.png.

Rectangles are (x0, y0, x1, y1) in template pixels:
    date         80,370  -> 324,418
    weather icon 510,236 -> 750,418
    weather text 602,423 -> 731,456
"""
import cv2
import numpy as np

RECTS = [
    ("date", 80, 370, 324, 418),
    ("weather_icon", 510, 236, 750, 418),
    ("weather_text", 602, 423, 731, 456),
]


def build_mask(shape):
    h, w = shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    for _name, x0, y0, x1, y1 in RECTS:
        x0 = max(0, x0)
        y0 = max(0, y0)
        x1 = min(w, x1)
        y1 = min(h, y1)
        mask[y0:y1, x0:x1] = 255
    return mask


def main():
    img = cv2.imread("template.png", cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError("Cannot read template.png")

    mask = build_mask(img.shape)
    result = cv2.inpaint(img, mask, inpaintRadius=8, flags=cv2.INPAINT_TELEA)

    cv2.imwrite("template_clean.png", result)
    for name, x0, y0, x1, y1 in RECTS:
        print(f"cleaned {name}: ({x0},{y0})-({x1},{y1})  {x1-x0}x{y1-y0}")
    print("Saved template_clean.png")


if __name__ == "__main__":
    main()
