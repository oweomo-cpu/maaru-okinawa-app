"""
parcocity_parking.py
~~~~~~~~~~~~~~~~~~~~
サンエー浦添西海岸 PARCO CITY の駐車場混雑情報を XML から取得するスクリプト。

駐車場管理システム (cnt.parkingweb.jp) の XML エンドポイントを直接叩き、
解析結果を parco_status.json に保存する。

使い方:
    python parcocity_parking.py

必要パッケージ:
    pip install requests
"""

from __future__ import annotations

import json
import logging
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

XML_URL = (
    "https://cnt.parkingweb.jp/000400/000427/000001/001/0427parking_status.xml"
)
OUTPUT_FILE = Path("parco_status.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/xml,text/xml,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": "https://www.parcocity.jp/",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_parking_xml(xml_text: str) -> dict:
    """XML を解析して全要素を辞書で返す。"""
    root = ET.fromstring(xml_text)
    data: dict = {}
    for elem in root.iter():
        text = (elem.text or "").strip()
        if text:
            data[elem.tag] = text
            logger.info("  XML要素  %s = %s", elem.tag, text)
    return data


def main() -> None:
    # キャッシュバスター付き URL（ブラウザと同じ挙動）
    url = f"{XML_URL}?_={int(time.time() * 1000)}"
    logger.info("GET %s", url)

    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    logger.info("取得完了 (%d bytes)", len(resp.content))

    # デバッグ用: 生の XML をログ出力
    logger.info("Raw XML:\n%s", resp.text)

    data = parse_parking_xml(resp.text)
    if not data:
        logger.error("XML の解析結果が空でした。")
        sys.exit(1)

    OUTPUT_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("保存完了: %s", OUTPUT_FILE)


if __name__ == "__main__":
    main()
