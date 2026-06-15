"""
Bước 2: Text → Audio dùng TikTokTTS local server.
Pattern tham khảo từ generate_tts_safe() trong tts_video.py — case TIKTOKTTS.
"""

import asyncio
import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

import aiohttp
from mutagen.mp3 import MP3

from config import (
    INPUT_DIR,
    TEMP_DIR,
    TIKTOKTTS_HOST,
    TIKTOKTTS_VOICE,
    TIKTOKTTS_SPEED,
    SILENCE_BETWEEN_DIALOGUES,
    MAX_CONCURRENT_TTS,
    MAX_RETRIES,
)

logger = logging.getLogger(__name__)

SILENCE_FILE = TEMP_DIR / "audio" / "silence.mp3"
semaphore = asyncio.Semaphore(MAX_CONCURRENT_TTS)


# ─── TTS generator ────────────────────────────────────────────────────────────
async def generate_tts_tiktoktts(text: str, output_path: str) -> bool:
    """
    Gọi TikTokTTS local server để sinh audio cho 1 đoạn text.

    Args:
        text: Nội dung cần đọc.
        output_path: Đường dẫn file output .mp3.

    Returns:
        True nếu thành công, False nếu thất bại.
    """
    async with semaphore:
        for attempt in range(MAX_RETRIES):
            try:
                async with aiohttp.ClientSession() as session:
                    url = f"{TIKTOKTTS_HOST}/v2/synthesize"
                    body = {
                        "text": text,
                        "speaker": TIKTOKTTS_VOICE,
                        "speed": TIKTOKTTS_SPEED,
                        "volume": 1000,
                        "method": "buffer",
                    }
                    async with session.post(
                        url, json=body, timeout=aiohttp.ClientTimeout(total=30)
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            if data:
                                with open(output_path, "wb") as f:
                                    f.write(data)
                                logger.debug("  TikTokTTS OK: %s", output_path)
                                return True
                            else:
                                logger.warning("  TikTokTTS attempt %d: empty response", attempt)
                        else:
                            logger.warning("  TikTokTTS attempt %d: status %d",
                                           attempt, resp.status)

                await asyncio.sleep(min(2 * (attempt + 1), 10))

            except asyncio.TimeoutError:
                logger.warning("  TikTokTTS attempt %d: timeout", attempt)
                await asyncio.sleep(2)
            except aiohttp.ClientError as e:
                logger.warning("  TikTokTTS attempt %d: %s", attempt, e)
                await asyncio.sleep(2)
            except Exception as e:
                logger.warning("  TikTokTTS attempt %d: %s", attempt, e)
                await asyncio.sleep(2)

        logger.error("  ❌ TikTokTTS thất bại sau %d lần: '%s...'", MAX_RETRIES, text[:30])
        return False


# ─── Silence file ─────────────────────────────────────────────────────────────
def _ensure_silence_file():
    """Tạo file silence nếu chưa có."""
    if not SILENCE_FILE.exists():
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", "anullsrc=r=24000:cl=mono",
                "-t", str(SILENCE_BETWEEN_DIALOGUES),
                str(SILENCE_FILE),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        logger.info("Đã tạo silence file: %s", SILENCE_FILE)


# ─── Duration ─────────────────────────────────────────────────────────────────
def get_mp3_duration(path: Path) -> float:
    """Đọc duration của file MP3 bằng mutagen."""
    try:
        audio = MP3(str(path))
        return audio.info.length
    except Exception as e:
        logger.warning("Không đọc được duration %s: %s", path, e)
        return 0.0


# ─── Scene processing ─────────────────────────────────────────────────────────
async def process_scene(scene: dict) -> dict:
    """Xử lý TTS cho 1 cảnh: tạo audio dialogues + ghép + đo duration."""
    scene_idx = scene["scene"]
    dialogues = scene["dialogues"]
    dialogue_paths: list[Path] = []
    dialogue_durations: list[float] = []
    silence_path = SILENCE_FILE

    # 1. Tạo audio từng dialogue song song
    tasks = []
    for d in dialogues:
        out_path = TEMP_DIR / "audio" / f"audio_{scene_idx}_{d['id']}.mp3"
        dialogue_paths.append(out_path)
        tasks.append(generate_tts_tiktoktts(d["text"], str(out_path)))

    results = await asyncio.gather(*tasks)
    for i, success in enumerate(results):
        if not success:
            logger.error("  Cảnh %d: dialogue %d thất bại", scene_idx, i + 1)

    # 2. Đo duration từng dialogue
    for path in dialogue_paths:
        if path.exists():
            dur = get_mp3_duration(path)
            dialogue_durations.append(dur if dur > 0 else 2.0)
        else:
            dialogue_durations.append(2.0)  # fallback

    # 3. Ghép audio cảnh: dialogue_1 + silence + dialogue_2 + silence + ...
    #    (KHÔNG có silence ở cuối)
    inputs: list[str] = []
    n_inputs = 0
    for i, p in enumerate(dialogue_paths):
        if p.exists():
            inputs += ["-i", str(p)]
            n_inputs += 1
            if i < len(dialogue_paths) - 1:
                inputs += ["-i", str(silence_path)]
                n_inputs += 1

    scene_audio_path = TEMP_DIR / "audio" / f"scene_{scene_idx}.mp3"

    if n_inputs > 0:
        filter_str = f"concat=n={n_inputs}:v=0:a=1[aout]"
        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_str,
            "-map", "[aout]",
            str(scene_audio_path),
        ]
        try:
            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            logger.info("  Đã ghép audio cảnh %d → %s", scene_idx, scene_audio_path)
        except subprocess.CalledProcessError as e:
            logger.error("  Lỗi ghép audio cảnh %d: %s", scene_idx, e)

    # 4. Đo tổng duration cảnh
    if scene_audio_path.exists():
        total_duration = get_mp3_duration(scene_audio_path)
    else:
        total_duration = sum(dialogue_durations) + SILENCE_BETWEEN_DIALOGUES * (len(dialogue_durations) - 1)

    # 5. Ghi lại vào scene dict
    scene["duration"] = total_duration
    scene["dialogue_durations"] = dialogue_durations

    logger.info("  Cảnh %d: %.2fs, %d dialogues",
                scene_idx, total_duration, len(dialogues))
    return scene


# ─── Public API ───────────────────────────────────────────────────────────────
def generate_all(script: list) -> list:
    """
    Chạy toàn bộ bước TTS: sinh audio và ghép cho tất cả cảnh.

    Args:
        script: List scenes.

    Returns:
        Script đã cập nhật với duration + dialogue_durations.
    """
    # Tạo silence file
    _ensure_silence_file()

    # Chạy async
    async def run():
        tasks = [process_scene(s) for s in script]
        return await asyncio.gather(*tasks)

    updated = asyncio.run(run())

    # Ghi lại script với duration
    output_path = INPUT_DIR / "script.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(list(updated), f, ensure_ascii=False, indent=2)
    logger.info("✅ Đã cập nhật script với duration → %s", output_path)

    return list(updated)