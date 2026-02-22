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

TARGET_URL = "https://www.parcocity.jp/access/"
BASE_URL   = "https://www.parcocity.jp"
OUTPUT_FILE = Path("parco_now.svg")

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


def find_svg_url(html: str) -> str | None:
    """HTML から駐車率 SVG 画像の URL を探して返す。"""
    soup = BeautifulSoup(html, "lxml")

    # PC 用コンテナを優先、なければページ全体から探す
    container = soup.find(id="factory_car-pc") or soup.body
    if container is None:
        logger.warning("ページ本文が見つかりません。")
        return None

    for img in container.find_all("img"):
        src = img.get("src", "")
        if "parking" in src and src.endswith(".svg"):
            if src.startswith("http"):
                return src
            return BASE_URL + src

    logger.warning("駐車場 SVG 画像が見つかりません。")
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
