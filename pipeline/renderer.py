"""
Bước 4: HTML + Audio → Video clip MP4 cho từng cảnh.
Dùng Playwright (headless) chụp từng frame → FFmpeg ghép video.
Không cần Xvfb / x11grab nữa.
"""

import asyncio
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from config import TEMP_DIR, VIDEO_WIDTH, VIDEO_HEIGHT, FPS

logger = logging.getLogger(__name__)


def render_scene(scene: dict) -> Optional[Path]:
    """
    Render 1 cảnh HTML + audio → clip video MP4.

    Args:
        scene: Scene dict (scene, duration, dialogues...)

    Returns:
        Path đến clip MP4 hoặc None nếu thất bại.
    """
    scene_num = scene["scene"]
    duration = scene.get("duration", 15.0)
    html_path = TEMP_DIR / "scenes" / f"scene_{scene_num}.html"
    audio_path = TEMP_DIR / "audio" / f"scene_{scene_num}.mp3"
    clip_path = TEMP_DIR / "clips" / f"clip_{scene_num}.mp4"
    frames_dir = TEMP_DIR / "clips" / f"frames_{scene_num}"

    # Kiểm tra file đầu vào
    if not html_path.exists():
        logger.error("Cảnh %d: Không tìm thấy HTML: %s", scene_num, html_path)
        return None

    if not audio_path.exists():
        logger.warning("Cảnh %d: Không tìm thấy audio: %s", scene_num, audio_path)
        # Không return None — vẫn render video không âm thanh

    # Xoá frames cũ nếu có
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)

    total_frames = int(duration * FPS)

    try:
        from playwright.async_api import async_playwright

        async def capture():
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.set_viewport_size({"width": VIDEO_WIDTH, "height": VIDEO_HEIGHT})
                await page.goto(f"file://{html_path.resolve()}")

                # Đợi load + animation đầu
                await page.wait_for_timeout(1000)

                logger.info("Cảnh %d: Chụp %d frames...", scene_num, total_frames)

                # Đợi CSS animations khởi tạo xong
                await page.wait_for_timeout(500)

                # Pause tất cả CSS animation để control bằng JS
                # (tránh desync giữa real-time capture và animation progress)
                try:
                    await page.evaluate("""
                        document.getAnimations().forEach(anim => anim.pause());
                    """)
                except Exception:
                    logger.warning(
                        "Cảnh %d: Không thể pause animations bằng JS — "
                        "có thể animation chưa load kịp",
                        scene_num,
                    )

                for i in range(total_frames):
                    # Đưa animation đến đúng vị trí dựa trên frame index
                    progress = i / total_frames if total_frames > 0 else 0
                    await page.evaluate(f"""
                        const p = {progress};
                        const totalDur = {duration};
                        document.getAnimations().forEach(anim => {{
                            anim.currentTime = p * totalDur * 1000;
                        }});
                    """)
                    await page.screenshot(
                        path=str(frames_dir / f"frame_{i:05d}.png")
                    )

                await browser.close()

        asyncio.run(capture())

    except ImportError:
        logger.error("Playwright chưa được cài. Chạy: pip install playwright && playwright install chromium")
        shutil.rmtree(frames_dir, ignore_errors=True)
        return None
    except Exception as e:
        logger.error("Cảnh %d: Lỗi Playwright capture: %s", scene_num, e)
        shutil.rmtree(frames_dir, ignore_errors=True)
        return None

    # Kiểm tra frames đã được tạo
    frame_files = sorted(frames_dir.glob("frame_*.png"))
    if len(frame_files) < total_frames * 0.5:
        logger.error("Cảnh %d: Chỉ chụp được %d/%d frames", scene_num, len(frame_files), total_frames)
        shutil.rmtree(frames_dir, ignore_errors=True)
        return None

    # Ghép frames + audio thành video
    logger.info("Cảnh %d: Ghép frames + audio → MP4...", scene_num)
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-framerate", str(FPS),
        "-i", str(frames_dir / "frame_%05d.png"),
    ]
    if audio_path.exists():
        ffmpeg_cmd += ["-i", str(audio_path)]

    ffmpeg_cmd += [
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
    ]
    if audio_path.exists():
        ffmpeg_cmd += ["-c:a", "aac", "-shortest"]
    ffmpeg_cmd.append(str(clip_path))

    try:
        subprocess.run(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        logger.info("Cảnh %d: Đã tạo clip → %s", scene_num, clip_path)
    except subprocess.CalledProcessError as e:
        logger.error("Cảnh %d: Lỗi FFmpeg ghép video: %s", scene_num, e)
        shutil.rmtree(frames_dir, ignore_errors=True)
        return None

    # Dọn frames tạm
    shutil.rmtree(frames_dir, ignore_errors=True)

    if not clip_path.exists() or clip_path.stat().st_size == 0:
        logger.error("Cảnh %d: Clip không được tạo hoặc rỗng", scene_num)
        return None

    return clip_path


def render_all(script: list) -> list:
    """
    Render tất cả các cảnh.

    Args:
        script: List scenes.

    Returns:
        Script (không thay đổi).
    """
    for scene in script:
        scene_num = scene["scene"]
        clip = render_scene(scene)
        if clip is None:
            logger.error("❌ Cảnh %d: Render thất bại", scene_num)
        else:
            logger.info("✅ Cảnh %d: Clip → %s", scene_num, clip)

    logger.info("✅ Hoàn tất render %d cảnh", len(script))
    return script