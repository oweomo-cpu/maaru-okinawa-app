"""
rycom_parking.py
~~~~~~~~~~~~~~~~
イオンモール沖縄ライカムの駐車場混雑 GIF 画像を取得するスクリプト。

固定 URL の GIF 画像をそのまま rycom_now.gif として保存する。
（画像の中身がどんな内容でも公式の見た目通りに表示できる）

使い方:
    python rycom_parking.py

必要パッケージ:
    pip install requests
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import requests

PARKING_IMAGE_URL = (
    "https://cnt.parkingweb.jp/000100/000178/000001/001/0178parking_status.gif"
)
OUTPUT_FILE = Path("rycom_now.gif")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "image/gif,image/webp,image/*,*/*;q=0.8",
    "Referer": "https://okinawarycom-aeonmall.com/",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("GET %s", PARKING_IMAGE_URL)
    resp = requests.get(PARKING_IMAGE_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    OUTPUT_FILE.write_bytes(resp.content)
    logger.info("保存完了: %s (%d bytes)", OUTPUT_FILE, len(resp.content))


if __name__ == "__main__":
    main()
