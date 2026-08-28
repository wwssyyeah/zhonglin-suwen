# 钟林速闻 · 全自动云版

完全脱离电脑，每天自动生成「钟林速闻」图片并通过 PushPlus 推送到个人微信（手机收图，无需开机）。

## 功能

- 每天早上 9:00（北京时间）自动运行
- 抓取「每天 60 秒读懂世界」免费新闻源
- 智谱 AI（glm-4-flash）做标题润色、编号、软新闻过滤
- 以你的原图 `template.png` 为背景，按固定坐标叠加新闻列表
- 自动字号拟合，保证新闻文字不溢出白底卡片
- 通过 PushPlus 推送到个人微信，手机直接收图

## 仓库文件说明

| 文件 | 作用 |
|------|------|
| `template.png` | 你的原图模版（已带白卡、标题、底部品牌） |
| `config.json` | 坐标、字号、颜色、字体路径配置 |
| `fetch_60s.py` | 拉取 60s 新闻，智谱润色，生成 `news.json` |
| `render.py` | 以原图为底，叠加新闻并输出 `output.png` |
| `pushplus_push.py` | 将图片（公开 URL）推送到 PushPlus → 微信 |
| `.github/workflows/news.yml` | 定时任务（北京时间 09:00） |
| `requirements.txt` | Python 依赖 |

## 快速部署

1. **建私有 GitHub 仓库**，把本目录全部文件推上去（注意 `template.png` 一起推）。
2. **注册 PushPlus**：https://www.pushplus.plus ，微信扫码登录 → 个人中心 → 密钥管理 → **复制 Token**；并去 verify.pushplus.plus 完成实名认证（**一次性 3.9 元，终身有效**，或在付款页选「开通会员免费实名」；不认证接口返回 905 无法发消息。认证后发消息本身免费，200 条/天）。
3. **设置 Secrets**（仓库 Settings → Secrets and variables → Actions → New repository secret）：
   - `ZHIPU_API_KEY`：你的智谱 API key
   - `PUSHPLUS_TOKEN`：你的 PushPlus **用户Token**（个人中心→密钥管理复制）
   - `PUSHPLUS_TOPIC`：**仅一对多需要**——填 PushPlus 一对多群组的「群组编码」（不填则为仅自己收的一对一模式）
4. **开启 GitHub Pages**：仓库 Settings → Pages → Branch 选 `main`、目录选 `/(root)` → Save。这样 `latest.png` 会生成公开地址 `https://<你的用户名>.github.io/<仓库名>/latest.png`，PushPlus 才能拉到图。
5. **手动触发一次** Actions → `钟林速闻每日自动生成` → Run workflow，观察是否出图、微信是否收到。
6. 以后每天 9:00 自动推送，无需电脑开机。

## 定位微调

如果第一次收到的图文字位置偏了：

1. 修改 `config.json` 里的 `news.x / news.y / news.max_width / news.max_height`。
2. 本机运行 `python render.py` 预览 `output.png`。
3. 满意后把 `config.json` 推回仓库。

> 默认坐标基于 `简报.png`（800×2400，白卡 left=38 top=529 w=724 h=1625）。若你换用其他尺寸模版，需要重新量坐标。

## 团队共享（一对多主题）

默认部署是「一对一」（只有你自己收）。如需同事也收到，改用 PushPlus **一对多群组**，代码已支持，只多填一个 Secret：

1. PushPlus 个人中心 → **发送消息 → 一对多消息** → 「创建的群组」标签 → 点 **新增群组**。
2. 填写：群组类型选「公开群组」、群组编码填如 `zhonglin-subao`（**这个编码就是 API 的 `topic` 值**）、群组名称 `钟林速闻`、联系方式、群组介绍。
3. 创建后点 **查看二维码**，把二维码发同事，他们微信扫码即**订阅**该群组（不订阅就收不到，这是最常见故障点）。
4. 仓库 Secrets 里：
   - `PUSHPLUS_TOKEN`：保持你的**用户Token**（不变）
   - 新增 `PUSHPLUS_TOPIC`：值填第 2 步的**群组编码**（如 `zhonglin-subao`）
5. 重新手动跑一次 Actions，所有已订阅同事的微信会**同时**收到图。

> 费用：一对多与一对一一样，只花那笔一次性 3.9 元实名费，**无需开会员**。免费额度 200 次/天、单主题最多 100 人、可建 5 个主题，日常绰绰有余。一次推送只算 1 次请求，与订阅人数无关。

## 关于日期/天气

你的原图里日期/天气是静态文字，为避免重影，`config.json` 中默认 `date.enabled` 和 `weather.enabled` 均为 `false`（不覆盖原图）。若日后想动态更新，需提供对应位置留空的模版底图，或在代码里先画遮盖块。

## 国内访问说明

图片经 GitHub Pages（`*.github.io`）分发，国内偶有不稳定的情况。若图片偶发加载失败，可在 GitHub Actions 的「Artifacts」里下载 `output.png` 原图；长期如需更稳，可改用 Gitee Pages 托管 `latest.png`。

## 免责声明

内容源自公开网络聚合，仅供内部参考，不构成任何投资或决策依据。
