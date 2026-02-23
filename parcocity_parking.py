"""
parcocity_parking.py
~~~~~~~~~~~~~~~~~~~~
サンエー浦添西海岸 PARCO CITY の駐車場混雑情報を XML から取得するスクリプト。

駐車場管理システム (cnt.parkingweb.jp) の XML エンドポイントを直接叩き、
解析結果を parco_status.json に保存する。

FullStatus の値と駐車率の対応:
    16 = 50%,  17 = 60%,  18 = 70%,  19 = 80%,  20 = 90%+
    計算式: 駐車率(%) = (FullStatus - 11) × 10

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

# FullStatus=16 → 50%, 17 → 60%, ..., 20 → 90%
FULL_STATUS_OFFSET = 11

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


def full_status_to_rate(full_status_str: str) -> int | None:
    """FullStatus の値を駐車率(%)に変換する。

    対応表: 16=50%, 17=60%, 18=70%, 19=80%, 20=90%
    計算式: (FullStatus - 11) × 10
    """
    try:
        val = int(full_status_str)
        rate = (val - FULL_STATUS_OFFSET) * 10
        return max(0, min(100, rate))
    except (ValueError, TypeError):
        return None


def rate_to_label(rate: int) -> str:
    """駐車率から混雑ラベルを返す。"""
    if rate >= 90:
        return "非常に混雑"
    elif rate >= 70:
        return "混雑"
    elif rate >= 50:
        return "やや混雑"
    else:
        return "空いています"


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

    data = parse_parking_xml(resp.text)
    if not data:
        logger.error("XML の解析結果が空でした。")
        sys.exit(1)

    # 駐車率を計算して追加
    rate = full_status_to_rate(data.get("FullStatus", ""))
    if rate is not None:
        label = rate_to_label(rate)
        data["parking_rate"] = rate
        data["parking_label"] = label
        logger.info("=" * 40)
        logger.info("  駐車率: %d%%  [%s]", rate, label)
        logger.info("  更新: %s", data.get("UpdateDate", "不明"))
        logger.info("=" * 40)
    else:
        logger.warning("FullStatus の変換に失敗しました: %s", data.get("FullStatus"))

    OUTPUT_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("保存完了: %s", OUTPUT_FILE)


if __name__ == "__main__":
    main()
