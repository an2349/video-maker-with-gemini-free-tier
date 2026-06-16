#!/usr/bin/env python3
"""
🎬 Video Pipeline — Điều phối toàn bộ pipeline sinh video tự động.

Usage:
    python main.py --topic "Chủ đề" --scenes 5 --style "tech tối màu"
    python main.py --script input/script.json
    python main.py --script input/script.json --from-step 3
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from config import INPUT_DIR, TIKTOKTTS_HOST, TIKTOKTTS_VOICE
from pipeline import script_generator, tts, scene_generator, renderer, merger

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─── Banner ────────────────────────────────────────────────────────────────────
BANNER = r"""
╔══════════════════════════════════════════════════════╗
║              🎬 VIDEO PIPELINE v1.0                  ║
║       HTML + TikTokTTS + FFmpeg → TikTok/Reels Video  ║
╚══════════════════════════════════════════════════════╝
"""


def print_banner():
    print(BANNER)
    print(f"  TTS:     {TIKTOKTTS_HOST} (voice: {TIKTOKTTS_VOICE})")
    print(f"  Output:  output/final_video.mp4")
    print("─" * 54)


# ─── CLI ──────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="🎬 Video Pipeline — sinh video TikTok/Reels tự động"
    )
    parser.add_argument(
        "--topic", type=str, default="Trí tuệ nhân tạo năm 2025",
        help="Chủ đề video (mặc định: 'Trí tuệ nhân tạo năm 2025')"
    )
    parser.add_argument(
        "--scenes", type=int, default=5,
        help="Số cảnh (mặc định: 5)"
    )
    parser.add_argument(
        "--style", type=str, default="tech tối màu, dramatic",
        help="Phong cách thiết kế (mặc định: 'tech tối màu, dramatic')"
    )
    parser.add_argument(
        "--script", type=str, default=None,
        help="Đường dẫn đến script.json có sẵn (bỏ qua bước 1)"
    )
    parser.add_argument(
        "--from-step", type=int, default=1, choices=range(1, 6),
        help="Chạy từ bước số mấy (1-5, mặc định: 1)"
    )
    return parser.parse_args()


# ─── Main ──────────────────────────────────────────────────────────────────────
def main():
    args = parse_args()
    print_banner()

    script = None

    # ─── Bước 1: Sinh kịch bản ──────────────────────────────────────────────
    if not args.script:
        if args.from_step <= 1:
            logger.info("═" * 54)
            logger.info("BƯỚC 1/5: Sinh kịch bản JSON từ chủ đề...")
            script = script_generator.generate(
                topic=args.topic,
                num_scenes=args.scenes,
                style=args.style,
            )
            if script is None:
                logger.error("❌ Bước 1 thất bại. Dừng pipeline.")
                sys.exit(1)
        else:
            # Đọc script từ file
            script_path = INPUT_DIR / "script.json"
            if not script_path.exists():
                logger.error("❌ Không tìm thấy %s. Chạy từ bước %d cần script có sẵn.",
                             script_path, args.from_step)
                sys.exit(1)
            with open(script_path, "r", encoding="utf-8") as f:
                script = json.load(f)
            logger.info("📄 Đã đọc script từ %s (%d cảnh)", script_path, len(script))
    else:
        # Đọc từ --script
        script_path = Path(args.script)
        if not script_path.exists():
            logger.error("❌ Không tìm thấy file script: %s", script_path)
            sys.exit(1)
        with open(script_path, "r", encoding="utf-8") as f:
            script = json.load(f)
        logger.info("📄 Đã đọc script từ %s (%d cảnh)", script_path, len(script))

    # ─── Bước 2: TTS ─────────────────────────────────────────────────────────
    if args.from_step <= 2:
        logger.info("═" * 54)
        logger.info("BƯỚC 2/5: Text → Audio (TikTokTTS)...")
        script = tts.generate_all(script)

    # ─── Bước 3: Sinh HTML ───────────────────────────────────────────────────
    if args.from_step <= 3:
        logger.info("═" * 54)
        logger.info("BƯỚC 3/5: JSON → HTML động...")
        script = scene_generator.generate_all(script)

    # ─── Bước 4: Render ──────────────────────────────────────────────────────
    if args.from_step <= 4:
        logger.info("═" * 54)
        logger.info("BƯỚC 4/5: HTML → Video clip...")
        script = renderer.render_all(script)

    # ─── Bước 5: Merge ───────────────────────────────────────────────────────
    if args.from_step <= 5:
        logger.info("═" * 54)
        logger.info("BƯỚC 5/5: Ghép clip → Video cuối...")
        final_path = merger.merge_all(script)

    # ─── Hoàn thành ──────────────────────────────────────────────────────────
    logger.info("═" * 54)
    logger.info("✅ PIPELINE HOÀN THÀNH!")
    logger.info("   Output: output/final_video.mp4")

    # In tổng kết
    total_duration = sum(s.get("duration", 0) for s in script)
    logger.info("   Tổng số cảnh: %d", len(script))
    logger.info("   Tổng thời lượng: %.1f giây (%.1f phút)", total_duration, total_duration / 60)


if __name__ == "__main__":
    main()