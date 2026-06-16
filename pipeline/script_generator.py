"""
Bước 1: Sinh kịch bản — 2 bước (Thô → JSON)

B1a: Sinh kịch bản THÔ (văn xuôi, toàn bộ 1 lần qua Gemini)
B1b: Parse kịch bản thô → JSON từng scene (bằng Python thuần)
"""

import json
import logging
import re
from typing import Optional

from config import INPUT_DIR, PROMPT_DIR
from pipeline.gemini_pool import call_gemini

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Bước 1a — Sinh kịch bản thô
# ═══════════════════════════════════════════════════════════════════

def generate_raw(topic: str, num_scenes: int, style: str) -> Optional[str]:
    """
    B1a: Gọi Gemini 1 lần duy nhất, sinh kịch bản thô dạng văn xuôi
    có đánh dấu [Scene X].

    Args:
        topic: Chủ đề video.
        num_scenes: Số cảnh.
        style: Phong cách thiết kế.

    Returns:
        Raw text kịch bản thô hoặc None nếu thất bại.
    """
    prompt_path = PROMPT_DIR / "gen_script_raw.txt"
    if not prompt_path.exists():
        logger.error("Không tìm thấy prompt file: %s", prompt_path)
        return None

    template = prompt_path.read_text(encoding="utf-8")
    prompt = template.format(
        topic=topic,
        num_scenes=num_scenes,
        style=style,
    )

    logger.info("B1a: Đang sinh kịch bản thô cho '%s' | %d cảnh | style: %s",
                topic, num_scenes, style)

    # Gọi Gemini 1 lần duy nhất, temperature=0.8 cho output đa dạng
    raw_text = call_gemini(prompt, temperature=0.8, label="SCRIPT_RAW")
    if not raw_text:
        logger.error("B1a: Gemini trả về None")
        return None

    logger.info("B1a: Đã sinh %d ký tự raw script", len(raw_text))

    # Lưu raw script để debug
    raw_path = INPUT_DIR / "script_raw.txt"
    raw_path.write_text(raw_text, encoding="utf-8")
    logger.info("B1a: Đã lưu raw script → %s", raw_path)

    return raw_text


# ═══════════════════════════════════════════════════════════════════
# Bước 1b — Parse thô → JSON (Python thuần, không cần AI)
# ═══════════════════════════════════════════════════════════════════

def parse_raw_script(raw_text: str) -> list[dict]:
    """
    B1b: Parse kịch bản thô dạng [Scene X]... thành JSON chuẩn.

    Args:
        raw_text: Raw text có cấu trúc:
            [Scene 1]
            dòng thoại 1
            dòng thoại 2
            ...

            [Scene 2]
            ...

    Returns:
        List scene dict theo format:
        [
            {"scene": 1, "style_hint": "", "dialogues": [{"id": 1, "text": "..."}, ...]},
            ...
        ]
    """
    scenes = []

    # Regex tách [Scene X] và nội dung
    blocks = re.split(r'\[Scene (\d+)\]', raw_text.strip())
    # blocks = ['', '1', 'nội dung scene 1', '2', 'nội dung scene 2', ...]

    i = 1
    while i < len(blocks) - 1:
        scene_num = int(blocks[i])
        content = blocks[i + 1].strip()
        lines = [l.strip() for l in content.split('\n') if l.strip()]

        dialogues = [{"id": j + 1, "text": line} for j, line in enumerate(lines)]
        scenes.append({
            "scene": scene_num,
            "style_hint": "",  # scene_generator sẽ điền sau
            "dialogues": dialogues,
        })
        i += 2

    logger.info("B1b: Parse được %d scene từ raw script", len(scenes))
    return scenes


# ═══════════════════════════════════════════════════════════════════
# Hàm hỗ trợ (giữ lại từ pipeline cũ)
# ═══════════════════════════════════════════════════════════════════

def extract_json(text: str) -> Optional[str]:
    """
    Trích xuất JSON array từ text AI trả về.
    Xử lý 3 trường hợp:
      1. Text thừa trước/sau JSON
      2. JSON bọc trong ```json ... ```
      3. JSON thuần túy

    Chiến lược:
      - Ưu tiên parse trực tiếp
      - Nếu lỗi, thử strip markdown fences
      - Nếu vẫn lỗi, dùng regex tìm array [] ngoài cùng
    """
    if not text or not text.strip():
        return None

    text = text.strip()

    # TH1: Thử parse trực tiếp
    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        pass

    # TH2: Bọc trong ``` ... ``` → lấy nội dung bên trong
    code_block = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", text)
    if code_block:
        inner = code_block.group(1).strip()
        try:
            json.loads(inner)
            return inner
        except json.JSONDecodeError:
            text = inner  # fall through to regex

    # TH3: Dùng regex tìm array [] ngoài cùng
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        candidate = text[start:end + 1]
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            pass

    return None


def _normalize_script(script: list) -> list:
    """
    Chuẩn hóa script từ AI về đúng cấu trúc.

    AI hay trả về:
      - dialogues: ["text1", "text2"]  thay vì [{"id": 1, "text": "text1"}, ...]
      - field thừa: duration_seconds, v.v.

    Hàm này tự động sửa các lỗi phổ biến.
    """
    if not isinstance(script, list):
        return script

    normalized = []
    for scene in script:
        if not isinstance(scene, dict):
            continue

        # Xóa field thừa, chỉ giữ scene / style_hint / dialogues
        clean = {
            "scene": scene.get("scene", len(normalized) + 1),
            "style_hint": scene.get("style_hint", ""),
            "dialogues": [],
        }

        dialogues = scene.get("dialogues", [])
        if isinstance(dialogues, list):
            for i, d in enumerate(dialogues):
                if isinstance(d, str):
                    clean["dialogues"].append({"id": i + 1, "text": d})
                elif isinstance(d, dict):
                    d_clean = {
                        "id": d.get("id", i + 1),
                        "text": d.get("text", ""),
                    }
                    clean["dialogues"].append(d_clean)
                else:
                    continue

        normalized.append(clean)

    return normalized


# ═══════════════════════════════════════════════════════════════════
# Hàm main: B1a → B1b (thay thế batch cũ)
# ═══════════════════════════════════════════════════════════════════

def generate(
    topic: str = "Trí tuệ nhân tạo",
    num_scenes: int = 5,
    style: str = "tech tối màu, dramatic",
    duration_per_scene: str = "15-20 giây",
) -> Optional[list]:
    """
    Gọi Gemini để sinh kịch bản (2 bước) → ghi input/script.json

    B1a: Sinh kịch bản thô (1 lần gọi Gemini, temperature=0.8)
    B1b: Parse thô → JSON (Python thuần, không cần AI)

    Args:
        topic: Chủ đề video.
        num_scenes: Số cảnh.
        style: Phong cách thiết kế.
        duration_per_scene: Thời lượng mỗi cảnh (giữ param để tương thích).

    Returns:
        List script hoặc None nếu thất bại.
    """
    logger.info("Đang sinh kịch bản cho chủ đề: '%s' | %d cảnh | style: %s",
                topic, num_scenes, style)

    # ── Bước 1a: Sinh kịch bản thô ──────────────────────────────
    raw_script = generate_raw(topic=topic, num_scenes=num_scenes, style=style)
    if raw_script is None:
        logger.error("B1a thất bại → không thể sinh kịch bản")
        return None

    # ── Bước 1b: Parse thô → JSON ───────────────────────────────
    scenes = parse_raw_script(raw_script)

    if not scenes:
        logger.error("B1b: Parse raw script không ra scene nào → dừng")
        return None

    # Kiểm tra số scene
    if len(scenes) < num_scenes:
        logger.warning(
            "⚠️ Chỉ parse được %d/%d cảnh (raw script chỉ có %d scene). "
            "Pipeline sẽ tiếp tục với số cảnh hiện có.",
            len(scenes), num_scenes, len(scenes)
        )

    # Ghi file JSON
    output_path = INPUT_DIR / "script.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(scenes, f, ensure_ascii=False, indent=2)

    logger.info("✅ B1 hoàn tất: %d cảnh → %s", len(scenes), output_path)
    return scenes