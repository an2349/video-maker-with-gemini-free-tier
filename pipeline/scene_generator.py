"""
Bước 3: JSON → HTML động cho từng cảnh.
Dùng dialogue_durations từ script để tính timing_hints.
"""

import asyncio
import logging
from typing import Optional

from config import PROMPT_DIR, TEMP_DIR, SILENCE_BETWEEN_DIALOGUES
from pipeline.gemini_pool import call_gemini, _call_gemini_async

logger = logging.getLogger(__name__)

# Số lượng scene được sinh đồng thời
CONCURRENT_SCENES = 5


def _build_timing_hints(dialogues: list, dialogue_durations: list[float]) -> str:
    """Tính timing_hints chi tiết — start_time + duration cho từng dialogue."""
    cumulative = 0.0
    hints = []
    for i, d in enumerate(dialogues):
        dur = dialogue_durations[i] if i < len(dialogue_durations) else 3.0
        end_time = cumulative + dur
        hints.append(f"đoạn {i+1} từ {cumulative:.1f}s đến {end_time:.1f}s (duration {dur:.1f}s)")
        cumulative = end_time + SILENCE_BETWEEN_DIALOGUES
    return "\n".join(hints)


def _build_dialogues_text(dialogues: list) -> str:
    """Tạo text hiển thị nội dung các dialogues."""
    lines = []
    for i, d in enumerate(dialogues):
        lines.append(f"[Đoạn {i+1}]: {d['text']}")
    return "\n".join(lines)


def validate_html(html: str, duration: float) -> bool:
    """Kiểm tra HTML có đủ các yếu tố cơ bản không."""
    if not html:
        return False
    checks = [
        "<!DOCTYPE" in html or "<html" in html,
        "1080" in html or "width" in html.lower(),
        "1920" in html or "height" in html.lower(),
        "animation" in html or "transition" in html,
        "@keyframes" in html,
    ]
    result = all(checks)
    if not result:
        missing = []
        if not checks[0]:
            missing.append("DOCTYPE/html")
        if not checks[1]:
            missing.append("1080px width")
        if not checks[2]:
            missing.append("1920px height")
        if not checks[3]:
            missing.append("animation/transition")
        if not checks[4]:
            missing.append("@keyframes")
        logger.warning("HTML thiếu: %s", ", ".join(missing))
    return result


def _build_prompt(scene: dict) -> str:
    """Xây dựng prompt cho 1 scene."""
    scene_num = scene["scene"]
    style_hint = scene.get("style_hint", "hiện đại, sáng tạo")
    duration = scene.get("duration", 15.0)
    dialogues = scene["dialogues"]
    dialogue_durations = scene.get("dialogue_durations", [])

    prompt_path = PROMPT_DIR / "gen_scene.txt"
    template = prompt_path.read_text(encoding="utf-8")

    dialogues_text = _build_dialogues_text(dialogues)
    timing_hints = _build_timing_hints(dialogues, dialogue_durations)

    prompt = template.format(
        duration=duration,
        dialogues_text=dialogues_text,
        style_hint=style_hint,
        timing_hints=timing_hints,
    )
    return prompt


def generate_scene(scene: dict) -> Optional[str]:
    """
    Sinh HTML cho 1 cảnh (đồng bộ).

    Args:
        scene: Scene dict (scene, style_hint, dialogues, duration,
               dialogue_durations, ...)

    Returns:
        HTML string hoặc None nếu thất bại.
    """
    scene_num = scene["scene"]
    duration = scene.get("duration", 15.0)

    # Đọc prompt template
    prompt_path = PROMPT_DIR / "gen_scene.txt"
    if not prompt_path.exists():
        logger.error("Không tìm thấy prompt file: %s", prompt_path)
        return None

    prompt = _build_prompt(scene)

    logger.info("Cảnh %d: đang sinh HTML (duration=%.1fs)...", scene_num, duration)

    for retry in range(30):
        html = call_gemini(prompt, temperature=0.7, label=f"SCENE_{scene_num}")
        if not html:
            logger.warning("  Lần %d: API trả về None", retry + 1)
            continue

        if validate_html(html, duration):
            logger.info("  ✅ Cảnh %d: HTML hợp lệ", scene_num)
            return html

        logger.warning("  Lần %d: HTML không hợp lệ, gửi lại prompt fix...", retry + 1)
        prompt = (
            f"Fix HTML theo đúng yêu cầu:\n"
            f"- Kích thước 1080x1920px\n"
            f"- Animation tự động chạy, có @keyframes\n"
            f"- Tổng thời gian {duration}s\n\n"
            f"Code hiện tại:\n{html}"
        )

    logger.error("  ❌ Cảnh %d: Không thể sinh HTML sau 3 lần retry", scene_num)
    return None


async def _generate_scene_async(scene: dict) -> tuple[int, Optional[str]]:
    """
    Sinh HTML cho 1 cảnh (async, dùng _call_gemini_async trực tiếp).

    Returns:
        (scene_num, html_string hoặc None)
    """
    scene_num = scene["scene"]
    duration = scene.get("duration", 15.0)

    prompt_path = PROMPT_DIR / "gen_scene.txt"
    if not prompt_path.exists():
        logger.error("Không tìm thấy prompt file: %s", prompt_path)
        return scene_num, None

    prompt = _build_prompt(scene)

    logger.info("Cảnh %d: đang sinh HTML (duration=%.1fs)...", scene_num, duration)

    for retry in range(3):
        html = await _call_gemini_async(prompt, temperature=0.7, label=f"SCENE_{scene_num}")
        if not html:
            logger.warning("  Cảnh %d lần %d: API trả về None", scene_num, retry + 1)
            continue

        if validate_html(html, duration):
            logger.info("  ✅ Cảnh %d: HTML hợp lệ", scene_num)
            return scene_num, html

        logger.warning("  Cảnh %d lần %d: HTML không hợp lệ, gửi lại prompt fix...", scene_num, retry + 1)
        prompt = (
            f"Fix HTML theo đúng yêu cầu:\n"
            f"- Kích thước 1080x1920px\n"
            f"- Animation tự động chạy, có @keyframes\n"
            f"- Tổng thời gian {duration}s\n\n"
            f"Code hiện tại:\n{html}"
        )

    logger.error("  ❌ Cảnh %d: Không thể sinh HTML sau 3 lần retry", scene_num)
    return scene_num, None


def _write_scene_html(scene_num: int, html: str):
    """Ghi HTML vào file."""
    out_path = TEMP_DIR / "scenes" / f"scene_{scene_num}.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info("  Đã ghi: %s", out_path)


def generate_all(script: list) -> list:
    """
    Sinh HTML cho tất cả các cảnh — chạy song song với CONCURRENT_SCENES luồng.

    Args:
        script: List scenes.

    Returns:
        Script (đã được cập nhật, không thay đổi cấu trúc).
    """
    # Chạy song song dùng async gather
    async def run_parallel():
        sem = asyncio.Semaphore(CONCURRENT_SCENES)

        async def limited(scene):
            async with sem:
                return await _generate_scene_async(scene)

        tasks = [limited(scene) for scene in script]
        results = await asyncio.gather(*tasks)
        return results

    results = asyncio.run(run_parallel())

    # Ghi kết quả ra file
    success_count = 0
    for scene_num, html in results:
        if html is None:
            logger.error("Bỏ qua cảnh %d do lỗi sinh HTML", scene_num)
            continue
        _write_scene_html(scene_num, html)
        success_count += 1

    logger.info("✅ Hoàn tất sinh HTML cho %d/%d cảnh", success_count, len(script))
    return script
