"""
Bước 5: Ghép tất cả clip → video cuối.
"""

import logging
import shutil
import subprocess
from pathlib import Path

from config import TEMP_DIR, OUTPUT_DIR, CLEANUP_TEMP

logger = logging.getLogger(__name__)


def merge_all(script: list) -> Path:
    """
    Ghép tất cả clip MP4 thành video cuối.

    Args:
        script: List scenes (có scene numbers).

    Returns:
        Path đến file video cuối.
    """
    final_path = OUTPUT_DIR / "final_video.mp4"
    filelist_path = TEMP_DIR / "clips" / "filelist.txt"

    # Tạo file list
    clip_paths = []
    for scene in script:
        scene_num = scene["scene"]
        clip_path = TEMP_DIR / "clips" / f"clip_{scene_num}.mp4"
        if clip_path.exists():
            clip_paths.append(clip_path)
        else:
            logger.warning("Cảnh %d: Không tìm thấy clip: %s", scene_num, clip_path)

    if not clip_paths:
        logger.error("Không có clip nào để ghép!")
        return final_path

    # Ghi file list
    with open(filelist_path, "w", encoding="utf-8") as f:
        for cp in clip_paths:
            f.write(f"file '{cp.resolve()}'\n")

    logger.info("Đang ghép %d clip → %s", len(clip_paths), final_path)

    # FFmpeg concat demuxer
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(filelist_path),
        "-c", "copy",
        str(final_path),
    ]

    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except subprocess.CalledProcessError as e:
        logger.error("Lỗi ghép video: %s", e)
        return final_path

    # In thông tin video cuối
    if final_path.exists():
        size_mb = final_path.stat().st_size / (1024 * 1024)
        logger.info("✅ Video cuối: %s", final_path)
        logger.info("   Kích thước: %.2f MB", size_mb)

        # Lấy tổng thời lượng
        try:
            dur_cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(final_path),
            ]
            result = subprocess.run(dur_cmd, capture_output=True, text=True, check=True)
            duration = float(result.stdout.strip())
            logger.info("   Thời lượng: %.1f giây (%.1f phút)", duration, duration / 60)
        except (subprocess.CalledProcessError, ValueError):
            pass
    else:
        logger.error("❌ Video cuối không được tạo!")

    # Cleanup temp
    if CLEANUP_TEMP and TEMP_DIR.exists():
        logger.info("Dọn dẹp temp/...")
        # Chỉ xóa nội dung, giữ lại cấu trúc thư mục
        for item in TEMP_DIR.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
                item.mkdir(parents=True, exist_ok=True)
        logger.info("✅ Đã dọn temp/")

    return final_path