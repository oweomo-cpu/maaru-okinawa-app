"""
parcocity_parking.py
~~~~~~~~~~~~~~~~~~~~
サンエー浦添西海岸 PARCO CITY の駐車場混雑情報を取得するスクリプト。

アクセスページから駐車率 SVG 画像の URL を特定し、
その画像を parco_now.svg としてダウンロード保存する。

使い方:
    python parcocity_parking.py

必要パッケージ:
    pip install requests beautifulsoup4 lxml
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

TARGET_URL  = "https://www.parcocity.jp/access/"
BASE_URL    = "https://www.parcocity.jp"
OUTPUT_FILE = Path("parco_now.svg")

# src 属性に含まれていれば駐車場画像とみなすキーワード（いずれか一致）
SVG_KEYWORDS = ("parking", "per.svg")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": "https://www.parcocity.jp/",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _is_parking_svg(src: str) -> bool:
    """src 属性がキーワードを含む SVG かどうかを判定する。"""
    return any(kw in src for kw in SVG_KEYWORDS) and src.endswith(".svg")


def find_svg_url(html: str) -> str | None:
    """
    HTML 内のすべての img タグを走査し、駐車率 SVG 画像の URL を返す。

    探索優先順位:
      1. #factory-car-pc 配下（PC 用コンテナ）
      2. ページ全体

    src にキーワード（parking / per.svg）を含み、拡張子が .svg の
    最初の img タグを採用する。
    """
    soup = BeautifulSoup(html, "lxml")

    def resolve(src: str) -> str:
        return src if src.startswith("http") else BASE_URL + src

    # ── 優先: #factory-car-pc コンテナ内を探す ──────────────────
    container = soup.find(id="factory-car-pc")
    if container:
        for img in container.find_all("img"):
            src = img.get("src", "")
            if _is_parking_svg(src):
                logger.info("#factory-car-pc コンテナ内で SVG を発見: %s", src)
                return resolve(src)
        logger.warning(
            "#factory-car-pc は存在しますが、駐車場 SVG が見つかりませんでした。"
            " ページ全体を検索します。"
        )
    else:
        logger.warning(
            "#factory-car-pc が見つかりません。ページ全体から img を検索します。"
        )

    # ── フォールバック: ページ内すべての img を検索 ───────────────
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if _is_parking_svg(src):
            logger.info("ページ全体の検索で SVG を発見: %s", src)
            return resolve(src)

    logger.error(
        "駐車場 SVG 画像が見つかりませんでした。"
        " キーワード: %s, 拡張子: .svg", SVG_KEYWORDS
    )
    return None


def main() -> None:
    logger.info("GET %s", TARGET_URL)
    resp = requests.get(TARGET_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    svg_url = find_svg_url(resp.text)
    if svg_url is None:
        logger.error("SVG URL の取得に失敗しました。")
        sys.exit(1)

    logger.info("SVG URL: %s", svg_url)
    svg_resp = requests.get(
        svg_url,
        headers={**HEADERS, "Accept": "image/svg+xml,*/*"},
        timeout=15,
    )
    svg_resp.raise_for_status()

    OUTPUT_FILE.write_bytes(svg_resp.content)
    logger.info("保存完了: %s (%d bytes)", OUTPUT_FILE, len(svg_resp.content))


if __name__ == "__main__":
    main()
