# 人民日报每日摘要机器人

每天早上自动抓取《人民日报》电子版全部版面，抽取全部文章内容，使用 AI 以“人民日报总编辑”口吻汇总为知识点摘要，并推送到 Telegram。

## 功能

- 根据当天日期自动生成目录页地址
- 自动解析当天全部版面，无需预设版面数量
- 抓取每个版面下全部文章正文
- 使用 OpenAI 兼容接口进行分层摘要
- 自动拆分长消息并发送到 Telegram
- 保存当天原始数据与摘要结果，便于审计与回看
- 支持本地运行与 GitHub Actions 定时运行

## 目录结构

```text
.
├── .env.example
├── .github/workflows/daily_digest.yml
├── main.py
├── requirements.txt
└── output/
```

## 环境变量

参考 [`.env.example`](/Users/xuxiaoming/Documents/Playground/.env.example)：

```bash
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1-mini
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
RMRB_SEND_TIMEZONE=Asia/Shanghai
RMRB_OUTPUT_DIR=output
RMRB_REQUEST_TIMEOUT=30
RMRB_MAX_ARTICLE_CHARS=4000
```

## 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY=...
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...
python3 main.py --dry-run
python3 main.py
```

指定日期回放：

```bash
python3 main.py --date 2026-03-25 --dry-run
```

## GitHub Actions 定时任务

项目已包含 workflow：

- 每天北京时间 `07:10` 自动运行
- 支持手动触发并指定日期

需要在 GitHub 仓库中配置以下 Secrets：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Telegram 机器人准备

1. 使用 `@BotFather` 创建机器人并拿到 `TELEGRAM_BOT_TOKEN`
2. 将机器人拉进你的群组或频道，或直接与机器人对话
3. 获取目标会话的 `chat_id`
4. 将 `TELEGRAM_BOT_TOKEN` 和 `TELEGRAM_CHAT_ID` 配置到环境变量或 GitHub Secrets

## 运行产物

每天执行后会生成：

- `output/YYYY-MM-DD/raw.json`
- `output/YYYY-MM-DD/summary.md`

## 合规提醒

《人民日报》电子版页面带有版权声明。当前方案适合个人学习研究型自动化阅读和摘要使用，请按站点规则控制抓取频率并谨慎使用内容。
