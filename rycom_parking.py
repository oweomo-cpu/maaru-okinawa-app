"""
rycom_parking.py
~~~~~~~~~~~~~~~~
イオンモール沖縄ライカムの駐車場混雑情報を取得するスクリプト。

データソース（2026-02 確認）:
  - 画像 URL : https://cnt.parkingweb.jp/000100/000178/000001/001/0178parking_status.gif
  - 提供元   : アマノ株式会社「駐車場クラウドサービス Parking Web」
  - 形式     : 現在の駐車率を GIF 画像で動的生成（URL は固定、内容が変化）
  - alt 属性 : "現在の駐車率"（テキストに数値なし → 画像解析が必要）

取得方式（2 段階フォールバック）:
  1. OCR（pytesseract）  : GIF から駐車率(%) を数値で読み取る ← 主方式
  2. 色分析（PIL のみ）  : OCR 失敗時に主要色から空き/混雑/満車を推定 ← 予備

使い方:
    # 1 回取得して表示
    python rycom_parking.py

    # GitHub Actions 用：最新状況を rycom_status.json に上書き保存
    python rycom_parking.py --status-file rycom_status.json

必要パッケージ:
    pip install requests Pillow pytesseract
    # システムへの tesseract 本体のインストールも必要
    # Linux : sudo apt-get install -y tesseract-ocr tesseract-ocr-jpn
    # macOS : brew install tesseract tesseract-lang
"""

from __future__ import annotations

import argparse
import colorsys
import io
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from PIL import Image, ImageEnhance, ImageFilter

try:
    import pytesseract
    _TESSERACT_AVAILABLE = True
except ImportError:
    _TESSERACT_AVAILABLE = False

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

PARKING_IMAGE_URL = (
    "https://cnt.parkingweb.jp/000100/000178/000001/001/0178parking_status.gif"
)

# ライカム公式サイトを Referer に設定（CDN のホットリンク拒否を回避）
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

# OCR テキストから駐車率(%) を抽出する正規表現
_PCT_RE = re.compile(r"(\d{1,3})\s*%")

# 色名 → ステータス（色分析フォールバック用）
# AMANO の画像は信号色（赤=満車, 黄=混雑, 緑=空き）を使うことが多い
_COLOR_STATUS = {
    "green":  "available",
    "yellow": "crowded",
    "orange": "almost_full",
    "red":    "full",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# データモデル（parcocity_parking.py と共通フォーマット）
# ---------------------------------------------------------------------------

@dataclass
class ParkingSection:
    name: str
    occupancy_pct: Optional[int] = None
    status: str = "unknown"
    raw_ocr: str = ""                # OCR 生テキスト（デバッグ用）
    detection_method: str = "none"   # "ocr" | "color" | "none"


@dataclass
class ParkingSnapshot:
    fetched_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )
    sections: list[ParkingSection] = field(default_factory=list)
    fetch_ok: bool = True
    error_msg: str = ""


# ---------------------------------------------------------------------------
# 駐車率 → ステータス変換
# ---------------------------------------------------------------------------

def _pct_to_status(pct: int) -> str:
    if pct >= 100:
        return "full"
    if pct >= 80:
        return "almost_full"
    if pct >= 50:
        return "crowded"
    return "available"


# ---------------------------------------------------------------------------
# GIF 取得
# ---------------------------------------------------------------------------

def fetch_parking_gif(timeout: int = 15) -> bytes:
    """駐車場状況 GIF を取得してバイト列で返す。"""
    logger.info("GET %s", PARKING_IMAGE_URL)
    resp = requests.get(PARKING_IMAGE_URL, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    logger.info(
        "HTTP %d  Content-Type: %s  Size: %d bytes",
        resp.status_code,
        resp.headers.get("content-type", ""),
        len(resp.content),
    )
    return resp.content


# ---------------------------------------------------------------------------
# 方式 1：OCR
# ---------------------------------------------------------------------------

def _preprocess_image(gif_bytes: bytes) -> Image.Image:
    """OCR 精度を上げるため GIF を前処理する（3 倍拡大 + コントラスト強調）。"""
    img = Image.open(io.BytesIO(gif_bytes))
    img.seek(0)          # アニメーション GIF の場合は先頭フレームを使用
    img = img.convert("RGB")
    w, h = img.size
    img = img.resize((w * 3, h * 3), Image.LANCZOS)
    img = img.convert("L")                              # グレースケール
    img = ImageEnhance.Contrast(img).enhance(2.5)       # コントラスト強調
    img = img.filter(ImageFilter.SHARPEN)
    return img


def _parse_pct(text: str) -> Optional[int]:
    """OCR テキストから 0〜100 の整数を抽出する。"""
    # "50%" や "50 %" など
    m = _PCT_RE.search(text)
    if m:
        v = int(m.group(1))
        if 0 <= v <= 100:
            return v
    # "%" が認識されなかったケース：単独の数字を候補にする
    for token in re.findall(r"\b(\d{1,3})\b", text):
        v = int(token)
        if 0 <= v <= 100:
            return v
    return None


def try_ocr(gif_bytes: bytes) -> tuple[Optional[int], str]:
    """
    pytesseract で GIF を OCR する。

    Returns:
        (駐車率 or None, OCR 生テキスト)
    """
    if not _TESSERACT_AVAILABLE:
        logger.warning("pytesseract が見つかりません。pip install pytesseract でインストールしてください。")
        return None, ""
    try:
        img = _preprocess_image(gif_bytes)
        # 数字・% と日本語ステータス文字を対象に認識
        config = "--psm 6 -c tessedit_char_whitelist=0123456789%空満車混雑きあ"
        raw = pytesseract.image_to_string(img, lang="jpn+eng", config=config)
        logger.info("OCR 結果: %r", raw.strip())
        return _parse_pct(raw), raw.strip()
    except Exception as exc:
        logger.warning("OCR 失敗: %s", exc)
        return None, ""


# ---------------------------------------------------------------------------
# 方式 2：色分析（OCR フォールバック）
# ---------------------------------------------------------------------------

def _classify_hue(hue_deg: float) -> str:
    """色相角(0-360)を 'red' / 'orange' / 'yellow' / 'green' / 'other' に分類。"""
    if hue_deg < 15 or hue_deg >= 345:
        return "red"
    if hue_deg < 45:
        return "orange"
    if hue_deg < 75:
        return "yellow"
    if hue_deg < 165:
        return "green"
    return "other"


def try_color_analysis(gif_bytes: bytes) -> tuple[str, str]:
    """
    GIF の主要色から駐車ステータスを推定する。

    Returns:
        (status 文字列, 検出された色名)
    """
    try:
        img = Image.open(io.BytesIO(gif_bytes))
        img.seek(0)
        img = img.convert("RGB")
        w, h = img.size

        # 画像周辺（余白・背景）を除いた中央部のピクセルを分析
        mx, my = max(1, w // 8), max(1, h // 8)
        counts: dict[str, int] = {
            "red": 0, "orange": 0, "yellow": 0, "green": 0, "other": 0
        }
        for y in range(my, h - my):
            for x in range(mx, w - mx):
                r, g, b = img.getpixel((x, y))
                h_val, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
                if s < 0.3 or v < 0.3:   # 無彩色（白・黒・グレー）は除外
                    continue
                counts[_classify_hue(h_val * 360)] += 1

        logger.info("色分析: %s", counts)
        dominant = max(counts, key=counts.get)
        if counts[dominant] == 0:
            return "unknown", "none"
        status = _COLOR_STATUS.get(dominant, "unknown")
        return status, dominant
    except Exception as exc:
        logger.warning("色分析失敗: %s", exc)
        return "unknown", "error"


# ---------------------------------------------------------------------------
# スナップショット取得
# ---------------------------------------------------------------------------

def get_parking_snapshot() -> ParkingSnapshot:
    snapshot = ParkingSnapshot()
    try:
        gif_bytes = fetch_parking_gif()

        # --- 方式 1: OCR ---
        pct, raw_ocr = try_ocr(gif_bytes)
        if pct is not None:
            snapshot.sections = [
                ParkingSection(
                    name="イオンモール沖縄ライカム",
                    occupancy_pct=pct,
                    status=_pct_to_status(pct),
                    raw_ocr=raw_ocr,
                    detection_method="ocr",
                )
            ]
            return snapshot

        # --- 方式 2: 色分析（フォールバック）---
        logger.info("OCR で駐車率を取得できなかったため、色分析にフォールバックします。")
        status, color = try_color_analysis(gif_bytes)
        # 色分析では正確な % は得られないため中央値を推定値として使用
        pct_estimate = {"available": 25, "crowded": 65, "almost_full": 85, "full": 100}.get(status)
        snapshot.sections = [
            ParkingSection(
                name="イオンモール沖縄ライカム",
                occupancy_pct=pct_estimate,
                status=status,
                raw_ocr=raw_ocr or f"dominant_color={color}",
                detection_method="color",
            )
        ]
    except Exception as exc:
        logger.error("取得失敗: %s", exc)
        snapshot.fetch_ok = False
        snapshot.error_msg = str(exc)
    return snapshot


# ---------------------------------------------------------------------------
# 保存
# ---------------------------------------------------------------------------

def save_status_json(snapshot: ParkingSnapshot, path: Path) -> None:
    """最新の状況を JSON ファイルに上書き保存する（GitHub Actions 用）。"""
    record = {
        "fetched_at": snapshot.fetched_at,
        "fetch_ok": snapshot.fetch_ok,
        "error_msg": snapshot.error_msg,
        "sections": [asdict(s) for s in snapshot.sections],
    }
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("status JSON 保存: %s", path)


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
        method_tag = f"[{s.detection_method}]" if s.detection_method != "none" else ""
        print(f"  {s.name}: 駐車率 {pct_str}  →  {label}  {method_tag}")


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="イオンモール沖縄ライカム 駐車場モニター")
    parser.add_argument(
        "--status-file",
        metavar="PATH",
        help="最新状況を指定 JSON ファイルに上書き保存する（GitHub Actions 用）",
    )
    args = parser.parse_args()

    logger.info("=== ライカム 駐車場モニター 開始 ===")
    snapshot = get_parking_snapshot()
    _print_snapshot(snapshot)

    if args.status_file:
        save_status_json(snapshot, Path(args.status_file))

    logger.info("=== 終了 ===")


if __name__ == "__main__":
    main()
