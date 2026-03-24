#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://paper.people.com.cn"
LAYOUT_URL_TEMPLATE = BASE_URL + "/rmrb/pc/layout/{yyyymm}/{dd}/node_01.html"
SECTION_LINK_RE = re.compile(r"/rmrb/pc/layout/\d{6}/\d{2}/node_(\d+)\.html")
ARTICLE_LINK_RE = re.compile(r"/rmrb/pc/content/\d{6}/\d{2}/content_\d+\.html")


@dataclass
class Article:
    section_no: int
    section_name: str
    title: str
    url: str
    content: str


@dataclass
class Section:
    section_no: int
    section_name: str
    url: str
    articles: list[Article]


class RMRBClient:
    def __init__(self, timeout: int = 30) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (compatible; RMRBDigestBot/1.0; +https://github.com)"
                )
            }
        )
        self.timeout = timeout

    def get_html(self, url: str) -> str:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or response.encoding
        return response.text

    def get_layout_url(self, target_date: datetime) -> str:
        return LAYOUT_URL_TEMPLATE.format(
            yyyymm=target_date.strftime("%Y%m"),
            dd=target_date.strftime("%d"),
        )

    def fetch_sections(self, target_date: datetime) -> list[Section]:
        layout_url = self.get_layout_url(target_date)
        soup = BeautifulSoup(self.get_html(layout_url), "html.parser")

        section_map: dict[int, Section] = {}
        for anchor in soup.select("a[href]"):
            href = anchor.get("href", "").strip()
            match = SECTION_LINK_RE.search(href)
            if not match:
                continue
            section_no = int(match.group(1))
            absolute_url = urljoin(layout_url, href)
            section_name = self._clean_text(anchor.get_text(" ", strip=True)) or f"{section_no:02d}版"
            section_map[section_no] = Section(
                section_no=section_no,
                section_name=section_name,
                url=absolute_url,
                articles=[],
            )

        if not section_map:
            raise RuntimeError(f"未能从目录页解析出版面链接: {layout_url}")

        sections = [section_map[key] for key in sorted(section_map)]
        for section in sections:
            section.articles = self.fetch_articles(section)
        return sections

    def fetch_articles(self, section: Section) -> list[Article]:
        soup = BeautifulSoup(self.get_html(section.url), "html.parser")
        articles: list[Article] = []
        seen_urls: set[str] = set()

        for anchor in soup.select("a[href]"):
            href = anchor.get("href", "").strip()
            if not ARTICLE_LINK_RE.search(href):
                continue
            article_url = urljoin(section.url, href)
            if article_url in seen_urls:
                continue
            seen_urls.add(article_url)
            title = self._clean_text(anchor.get_text(" ", strip=True))
            if not title:
                continue
            content = self.fetch_article_content(article_url)
            articles.append(
                Article(
                    section_no=section.section_no,
                    section_name=section.section_name,
                    title=title,
                    url=article_url,
                    content=content,
                )
            )

        return articles

    def fetch_article_content(self, url: str) -> str:
        soup = BeautifulSoup(self.get_html(url), "html.parser")
        selectors = [
            "#ozoom",
            ".rm_txt_con",
            ".text_c",
            ".article",
            "article",
            ".content",
        ]

        for selector in selectors:
            node = soup.select_one(selector)
            text = self._extract_text(node)
            if text:
                return text

        body_text = self._clean_text(soup.get_text("\n", strip=True))
        return body_text[:12000]

    def _extract_text(self, node) -> str:
        if node is None:
            return ""
        paragraphs = [
            self._clean_text(p.get_text(" ", strip=True))
            for p in node.select("p")
        ]
        paragraphs = [item for item in paragraphs if item]
        if paragraphs:
            return "\n".join(paragraphs)
        return self._clean_text(node.get_text("\n", strip=True))

    @staticmethod
    def _clean_text(text: str) -> str:
        text = re.sub(r"[ \t\r\f\v]+", " ", text or "")
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


class OpenAICompatClient:
    def __init__(self, api_key: str, base_url: str, model: str, timeout: int = 60) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )

    def summarize(self, target_date: str, sections: list[Section], max_article_chars: int) -> str:
        section_summaries = []
        for section in sections:
            payload = self._build_section_payload(section, max_article_chars)
            section_summaries.append(
                {
                    "section_no": section.section_no,
                    "section_name": section.section_name,
                    "summary": self._chat(
                        system_prompt=SECTION_SYSTEM_PROMPT,
                        user_prompt=payload,
                    ),
                }
            )

        final_payload = {
            "date": target_date,
            "section_summaries": section_summaries,
        }
        return self._chat(
            system_prompt=FINAL_SYSTEM_PROMPT,
            user_prompt=json.dumps(final_payload, ensure_ascii=False, indent=2),
        )

    def _build_section_payload(self, section: Section, max_article_chars: int) -> str:
        section_payload = {
            "section_no": section.section_no,
            "section_name": section.section_name,
            "articles": [
                {
                    "title": article.title,
                    "url": article.url,
                    "content": article.content[:max_article_chars],
                }
                for article in section.articles
            ],
        }
        return json.dumps(section_payload, ensure_ascii=False, indent=2)

    def _chat(self, system_prompt: str, user_prompt: str) -> str:
        response = self.session.post(
            f"{self.base_url}/chat/completions",
            timeout=self.timeout,
            json={
                "model": self.model,
                "temperature": 0.3,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()


SECTION_SYSTEM_PROMPT = """你是《人民日报》总编辑。你将阅读一个版面的全部文章内容，并产出该版面知识点摘要。

要求：
1. 口吻庄重、准确、凝练，符合人民日报总编辑身份。
2. 只根据提供材料总结，不补充站外事实。
3. 输出 3-6 条知识点，必要时补充一句“本版总体判断”。
4. 广告或信息量明显偏低时，直接说明“本版信息量较低”。
5. 输出使用 Markdown，适合后续拼接到 Telegram 消息。
"""


FINAL_SYSTEM_PROMPT = """你是《人民日报》总编辑。请基于当天全部版面摘要，撰写一份《人民日报今日知识点摘要》。

输出结构必须为：
# 人民日报每日摘要｜{date}

## 一、今日总览
- 5 到 8 条全局要点

## 二、版面摘要
按版面顺序列出，每个版面 2 到 5 条知识点

## 三、今日重点结论
- 从政策信号、经济动向、社会民生、国际局势、文化思想等角度提炼关键判断

要求：
1. 用中文输出。
2. 风格庄重、凝练、可读，适合 Telegram。
3. 不要编造，不要脱离输入材料。
4. 如果个别版面信息较少，可简写。
"""


def build_raw_payload(target_date: str, sections: list[Section]) -> dict:
    return {
        "date": target_date,
        "layout_url": LAYOUT_URL_TEMPLATE.format(
            yyyymm=target_date.replace("-", "")[:6],
            dd=target_date[-2:],
        ),
        "sections": [
            {
                "section_no": section.section_no,
                "section_name": section.section_name,
                "url": section.url,
                "articles": [asdict(article) for article in section.articles],
            }
            for section in sections
        ],
    }


def save_outputs(output_dir: Path, target_date: str, raw_payload: dict, summary: str) -> tuple[Path, Path]:
    day_dir = output_dir / target_date
    day_dir.mkdir(parents=True, exist_ok=True)

    raw_path = day_dir / "raw.json"
    summary_path = day_dir / "summary.md"

    raw_path.write_text(
        json.dumps(raw_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary_path.write_text(summary, encoding="utf-8")
    return raw_path, summary_path


def split_telegram_message(text: str, limit: int = 3500) -> list[str]:
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) <= limit:
            current += line
            continue
        if current:
            chunks.append(current.rstrip())
            current = ""
        while len(line) > limit:
            chunks.append(line[:limit])
            line = line[limit:]
        current += line
    if current.strip():
        chunks.append(current.rstrip())
    return chunks or [text[:limit]]


def send_telegram_message(bot_token: str, chat_id: str, text: str, timeout: int = 30) -> None:
    session = requests.Session()
    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    for chunk in split_telegram_message(text):
        response = session.post(
            api_url,
            timeout=timeout,
            json={
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            },
        )
        response.raise_for_status()


def resolve_target_date(cli_date: str | None, tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name)
    if cli_date:
        return datetime.strptime(cli_date, "%Y-%m-%d").replace(tzinfo=tz)
    return datetime.now(tz)


def positive_int_from_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    return int(raw)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="人民日报每日抓取、AI 摘要与 Telegram 推送")
    parser.add_argument("--date", help="抓取日期，格式 YYYY-MM-DD，默认使用当前时区日期")
    parser.add_argument("--dry-run", action="store_true", help="只抓取和生成摘要，不发送 Telegram")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    timezone_name = os.getenv("RMRB_SEND_TIMEZONE", "Asia/Shanghai")
    output_dir = Path(os.getenv("RMRB_OUTPUT_DIR", "output"))
    timeout = positive_int_from_env("RMRB_REQUEST_TIMEOUT", 30)
    max_article_chars = positive_int_from_env("RMRB_MAX_ARTICLE_CHARS", 4000)

    target_date_dt = resolve_target_date(args.date, timezone_name)
    target_date = target_date_dt.strftime("%Y-%m-%d")

    rmrb_client = RMRBClient(timeout=timeout)
    sections = rmrb_client.fetch_sections(target_date_dt)

    raw_payload = build_raw_payload(target_date, sections)

    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    if not api_key:
        raise RuntimeError("缺少环境变量 OPENAI_API_KEY")

    ai_client = OpenAICompatClient(api_key=api_key, base_url=base_url, model=model, timeout=max(timeout, 60))
    summary = ai_client.summarize(target_date=target_date, sections=sections, max_article_chars=max_article_chars)

    raw_path, summary_path = save_outputs(output_dir, target_date, raw_payload, summary)
    print(f"已保存原始数据: {raw_path}")
    print(f"已保存摘要文件: {summary_path}")

    if args.dry_run:
        print("dry-run 模式，未发送 Telegram。")
        return 0

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        raise RuntimeError("缺少 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID")

    send_telegram_message(bot_token=bot_token, chat_id=chat_id, text=summary, timeout=timeout)
    print("Telegram 推送完成。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except requests.HTTPError as exc:
        response = exc.response
        if response is not None:
            sys.stderr.write(f"HTTP 错误 {response.status_code}: {response.text[:1000]}\n")
        else:
            sys.stderr.write(f"HTTP 错误: {exc}\n")
        raise
    except Exception as exc:
        sys.stderr.write(f"执行失败: {exc}\n")
        raise
