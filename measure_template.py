from PIL import Image
import sys

img = Image.open(r"D:\workbuddy程序\钟林速闻-auto\template.png").convert("RGBA")
print(f"size: {img.size}")

# 找白色卡片区：每个像素 RGB 都接近 255，透明度>200
# 先转成二值 mask：白色区域为 1
w, h = img.size
mask = [[0]*h for _ in range(w)]
for x in range(w):
    for y in range(h):
        r, g, b, a = img.getpixel((x, y))
        if r > 245 and g > 245 and b > 245 and a > 200:
            mask[x][y] = 1

# 找最大连续白色矩形（简化：按行找白色连续段）
from collections import Counter
# 统计每列白色像素数
col_white = [sum(mask[x][y] for y in range(h)) for x in range(w)]
# 统计每行白色像素数
row_white = [sum(mask[x][y] for x in range(w)) for y in range(h)]

print("col white max/min samples:", max(col_white), min(col_white))
print("row white max/min samples:", max(row_white), min(row_white))

# 找白色像素较多的行/列
left = next(i for i, v in enumerate(col_white) if v > h*0.3)
right = next(i for i in range(w-1, -1, -1) if col_white[i] > h*0.3)
top = next(i for i, v in enumerate(row_white) if v > w*0.3)
bottom = next(i for i in range(h-1, -1, -1) if row_white[i] > w*0.3)
print(f"rough white card: left={left} top={top} right={right} bottom={bottom}  w={right-left} h={bottom-top}")

# 找出白色占比最高的矩形区（可能是卡片主体），打印 top 5 的白色行区间
# 这里直接按行打印白色像素数分布，帮助判断
print("\nrow distribution (y: count):")
for y in range(0, h, h//20):
    print(f"  y={y}: {row_white[y]}")
