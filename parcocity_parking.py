"""
parcocity_parking.py
~~~~~~~~~~~~~~~~~~~~
サンエー浦添西海岸 PARCO CITY の駐車場混雑情報を取得するスクリプト。

ページ構造（2026-02 確認）:
  - 要素 ID : #factory-car-pc
  - 子要素  : <img src="/images/parking/pc/parking_<N>per.svg">
  - <N> が駐車率(%) を表す（例: 10, 50, 80, 100 など）

使い方:
    # 1 回だけ取得して表示
    python parcocity_parking.py

    # 最新状況を status.json に上書き保存（GitHub Actions 用）
    python parcocity_parking.py --status-file status.json

    # 5 分おきに無限ループ（Ctrl+C で停止）
    python parcocity_parking.py --loop

必要パッケージ:
    pip install requests beautifulsoup4 lxml
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

TARGET_URL = "https://www.parcocity.jp/access/"

# リクエスト間隔（秒）― サーバーへの負荷を抑えるため 60 秒以上推奨
FETCH_INTERVAL_SEC = 300

# データ保存先
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

# 駐車率画像の src に含まれるパーセント値を抽出する正規表現
# 例: /images/parking/pc/parking_10per.svg  →  10
_OCCUPANCY_RE = re.compile(r"/parking_(\d+)per\.svg", re.IGNORECASE)

# 駐車率 → ステータス文字列
def _pct_to_status(pct: int) -> str:
    if pct >= 100:
        return "full"
    if pct >= 80:
        return "almost_full"
    if pct >= 50:
        return "crowded"
    return "available"

# 403 を避けるため、一般的なブラウザに近いヘッダーを送る
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


# ---------------------------------------------------------------------------
# データモデル
# ---------------------------------------------------------------------------

@dataclass
class ParkingSection:
    """駐車場エリアの状態。"""

    name: str                              # エリア名（現状は施設全体のみ）
    occupancy_pct: Optional[int] = None   # 駐車率 0〜100（取得できない場合 None）
    status: str = "unknown"               # available / crowded / almost_full / full / unknown
    img_src: str = ""                     # 取得した img src（デバッグ用）


@dataclass
class ParkingSnapshot:
    """ある時点のスナップショット。"""

    fetched_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )
    sections: list[ParkingSection] = field(default_factory=list)
    fetch_ok: bool = True
    error_msg: str = ""


# ---------------------------------------------------------------------------
# スクレイピング
# ---------------------------------------------------------------------------

def fetch_html(url: str, timeout: int = 15) -> str:
    """指定 URL の HTML を取得して返す。失敗時は requests.HTTPError を送出。"""
    logger.info("GET %s", url)
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.text


def parse_parking_html(html: str) -> list[ParkingSection]:
    """
    HTML 内の #factory-car-pc に含まれる img 要素の src から駐車率を取得する。

    ページ例:
        <div id="factory-car-pc">
          <img src="/images/parking/pc/parking_50per.svg" alt="...">
        </div>

    Returns:
        ParkingSection のリスト（現状は施設全体の 1 要素のみ）
    """
    soup = BeautifulSoup(html, "lxml")

    container = soup.find(id="factory-car-pc")
    if container is None:
        logger.warning("#factory-car-pc が見つかりません。ページ構造が変わった可能性があります。")
        return [ParkingSection(name="パルコシティ全体", status="unknown")]

    img = container.find("img")
    if img is None:
        logger.warning("#factory-car-pc 内に img タグが見つかりません。")
        return [ParkingSection(name="パルコシティ全体", status="unknown")]

    src = img.get("src", "")
    logger.debug("img src: %s", src)

    match = _OCCUPANCY_RE.search(src)
    if match is None:
        logger.warning("src からパーセント値を抽出できませんでした: %s", src)
        return [ParkingSection(name="パルコシティ全体", img_src=src, status="unknown")]

    pct = int(match.group(1))
    return [
        ParkingSection(
            name="パルコシティ全体",
            occupancy_pct=pct,
            status=_pct_to_status(pct),
            img_src=src,
        )
    ]


def get_parking_snapshot() -> ParkingSnapshot:
    """1 回分の駐車場情報を取得して ParkingSnapshot を返す。"""
    snapshot = ParkingSnapshot()
    try:
        html = fetch_html(TARGET_URL)
        snapshot.sections = parse_parking_html(html)
    except Exception as exc:  # noqa: BLE001
        logger.error("取得失敗: %s", exc)
        snapshot.fetch_ok = False
        snapshot.error_msg = str(exc)
    return snapshot


# ---------------------------------------------------------------------------
# 保存
# ---------------------------------------------------------------------------

def save_status_json(snapshot: ParkingSnapshot, path: Path) -> None:
    """最新の駐車状況を JSON ファイルに上書き保存する（GitHub Actions 用）。

    parking_log.jsonl と異なり追記ではなく上書きするため、
    常に「現在の状態」だけが保存される。
    """
    record = {
        "fetched_at": snapshot.fetched_at,
        "fetch_ok": snapshot.fetch_ok,
        "error_msg": snapshot.error_msg,
        "sections": [asdict(s) for s in snapshot.sections],
    }
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("status JSON 保存: %s", path)


def save_jsonl(snapshot: ParkingSnapshot) -> Path:
    """スナップショットを JSONL（1 行 1 レコード）に追記保存する。"""
    path = DATA_DIR / "parking_log.jsonl"
    record = {
        "fetched_at": snapshot.fetched_at,
        "fetch_ok": snapshot.fetch_ok,
        "error_msg": snapshot.error_msg,
        "sections": [asdict(s) for s in snapshot.sections],
    }
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(record, ensure_ascii=False) + "\n")
    logger.info("JSONL 保存: %s", path)
    return path


def save_csv(snapshot: ParkingSnapshot) -> Path:
    """スナップショットを CSV に追記保存する。"""
    path = DATA_DIR / "parking_log.csv"
    fieldnames = ["fetched_at", "section_name", "occupancy_pct", "status", "img_src"]
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        for s in snapshot.sections:
            writer.writerow(
                {
                    "fetched_at": snapshot.fetched_at,
                    "section_name": s.name,
                    "occupancy_pct": s.occupancy_pct,
                    "status": s.status,
                    "img_src": s.img_src,
                }
            )
    logger.info("CSV 保存: %s", path)
    return path


# ---------------------------------------------------------------------------
# 表示
# ---------------------------------------------------------------------------

_STATUS_LABEL = {
    "available":   "空き あり",
    "crowded":     "混雑",
    "almost_full": "ほぼ満車",
    "full":        "満車",
    "unknown":     "不明",
}

def _print_snapshot(snapshot: ParkingSnapshot) -> None:
    print(f"\n--- {snapshot.fetched_at} ---")
    if not snapshot.fetch_ok:
        print(f"  [ERROR] {snapshot.error_msg}")
        return
    for s in snapshot.sections:
        pct_str = f"{s.occupancy_pct}%" if s.occupancy_pct is not None else "不明"
        label = _STATUS_LABEL.get(s.status, s.status)
        print(f"  {s.name}: 駐車率 {pct_str}  →  {label}")


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="パルコシティ 駐車場モニター")
    parser.add_argument(
        "--loop",
        action="store_true",
        help=f"Ctrl+C まで {FETCH_INTERVAL_SEC} 秒おきに繰り返し取得する",
    )
    parser.add_argument(
        "--status-file",
        metavar="PATH",
        help="最新状況を指定 JSON ファイルに上書き保存する（GitHub Actions 用）",
    )
    args = parser.parse_args()

    logger.info("=== パルコシティ 駐車場モニター 開始 ===")

    count = 0
    try:
        while True:
            snapshot = get_parking_snapshot()
            _print_snapshot(snapshot)

            if args.status_file:
                save_status_json(snapshot, Path(args.status_file))
            else:
                save_jsonl(snapshot)
                save_csv(snapshot)

            count += 1

            if not args.loop:
                break
            logger.info("%d 秒後に再取得します...", FETCH_INTERVAL_SEC)
            time.sleep(FETCH_INTERVAL_SEC)
    except KeyboardInterrupt:
        logger.info("中断しました。")

    logger.info("=== 終了 (取得回数: %d) ===", count)


if __name__ == "__main__":
    main()
