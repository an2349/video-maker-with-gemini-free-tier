"""
Rotation Pool thông minh — xoay key + model theo RPM/RPD.
Copy từ proxy.py, bọc thêm call_gemini() cho pipeline dùng.

Hành vi xoay key:
- RPM đầy → chờ đến khi slot trống, dùng lại cặp đó (KHÔNG nhảy sang cặp khác)
- RPD cạn → đánh dấu hết ngày, bỏ hẳn cặp đó đến 00:00 UTC
- 429 từ server → parse retryDelay từ response → hard cooldown đúng thời gian
"""

import asyncio
import json
import logging
import time
from typing import Optional

import httpx

from config import GEMINI_KEYS, GEMINI_MODELS

logger = logging.getLogger(__name__)

GEMINI_BASE = "https://generativelanguage.googleapis.com"

SAFETY_CATEGORIES = [
    "HARM_CATEGORY_HARASSMENT",
    "HARM_CATEGORY_HATE_SPEECH",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT",
    "HARM_CATEGORY_DANGEROUS_CONTENT",
]


# ─── PairState ────────────────────────────────────────────────────────────────
class PairState:
    """Trạng thái của 1 cặp (key, model)."""

    def __init__(self, key: str, model_cfg: dict):
        self.key = key
        self.model_cfg = model_cfg
        self.model_name: str = model_cfg["name"]
        self.rpm: int = model_cfg["rpm"]
        self.rpd: int = model_cfg["rpd"]

        # Sliding window RPM: list[timestamp]
        self.rpm_window: list[float] = []
        self.rpd_used: int = 0
        self.rpd_date: str = ""  # YYYY-MM-DD

        self.cooldown_until: float = 0.0  # hard cooldown từ 429
        self.error_count: int = 0
        self.last_used: float = 0.0

    def reset_rpd_if_new_day(self):
        today = time.strftime("%Y-%m-%d")
        if self.rpd_date != today:
            self.rpd_used = 0
            self.rpd_date = today

    def can_use(self) -> bool:
        now = time.time()
        self.reset_rpd_if_new_day()

        # Hard cooldown
        if now < self.cooldown_until:
            return False

        # RPD
        if self.rpd_used >= self.rpd:
            return False

        # RPM: remove old entries (> 60s)
        self.rpm_window = [t for t in self.rpm_window if now - t < 60]
        if len(self.rpm_window) >= self.rpm:
            return False

        return True

    def mark_used(self):
        now = time.time()
        self.rpm_window.append(now)
        self.rpd_used += 1
        self.last_used = now

    def mark_limited(self, retry_after: int = 60):
        """Đánh dấu bị rate limit, cooldown trong retry_after giây."""
        self.cooldown_until = time.time() + retry_after
        logger.warning("  ⏳ Cooldown %s@%s trong %ds",
                       self.key[:8], self.model_name, retry_after)

    def mark_error(self):
        self.error_count += 1
        if self.error_count >= 5:
            self.cooldown_until = time.time() + 120  # nghỉ 2 phút nếu lỗi liên tiếp
            logger.warning("  ⛔ %s@%s lỗi %d lần, cooldown 120s",
                           self.key[:8], self.model_name, self.error_count)

    def mark_success(self):
        self.error_count = 0

    def time_until_available(self) -> float:
        """Thời gian chờ (giây) cho đến khi cặp này được."""
        now = time.time()

        if now < self.cooldown_until:
            return self.cooldown_until - now

        self.reset_rpd_if_new_day()
        if self.rpd_used >= self.rpd:
            # Hết RPD, chờ đến 00:00 UTC
            tomorrow = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 86400))
            tomorrow_ts = time.mktime(time.strptime(f"{tomorrow} 00:00:00", "%Y-%m-%d %H:%M:%S"))
            return tomorrow_ts - now

        # RPM
        if self.rpm_window:
            now_ts = now
            self.rpm_window = [t for t in self.rpm_window if now_ts - t < 60]
            if len(self.rpm_window) >= self.rpm:
                # Chờ đến khi entry cũ nhất hết hạn (> 60s)
                oldest = min(self.rpm_window)
                return max(0.0, 60 - (now_ts - oldest))

        return 0.0

    def __repr__(self):
        return (f"PairState(key={self.key[:8]}..., model={self.model_name}, "
                f"rpm={len(self.rpm_window)}/{self.rpm}, "
                f"rpd={self.rpd_used}/{self.rpd}, "
                f"cooldown={'yes' if time.time() < self.cooldown_until else 'no'})")


# ─── RotationPool ─────────────────────────────────────────────────────────────
class RotationPool:
    """Pool xoay vòng thông minh theo RPM/RPD."""

    def __init__(self, keys: list[str], model_configs: list[dict]):
        self.pairs: list[PairState] = [
            PairState(key, cfg)
            for key in keys
            for cfg in model_configs
        ]
        self._index = 0

    def _best_pair(self) -> Optional[PairState]:
        """Chọn cặp tốt nhất: available → thời gian chờ ngắn nhất."""
        available = [p for p in self.pairs if p.can_use()]
        if available:
            # Round-robin trong available
            available.sort(key=lambda p: p.last_used)
            return available[0]

        # Nếu không có available, chọn cặp có time_until_available ngắn nhất
        self.pairs.sort(key=lambda p: p.time_until_available())
        return self.pairs[0]

    async def get(self) -> tuple[str, dict]:
        """Lấy cặp (key, model_cfg) tốt nhất, chờ nếu cần."""
        while True:
            pair = self._best_pair()
            if pair.can_use():
                pair.mark_used()
                return pair.key, pair.model_cfg

            wait = pair.time_until_available()
            if wait > 0:
                logger.debug("Chờ %.1fs để dùng %s@%s",
                             wait, pair.key[:8], pair.model_name)
                await asyncio.sleep(min(wait, 1.0))
            else:
                await asyncio.sleep(0.1)

    async def mark_success(self, key: str, model_cfg: dict):
        for p in self.pairs:
            if p.key == key and p.model_name == model_cfg["name"]:
                p.mark_success()
                break

    async def mark_limited(self, key: str, model_cfg: dict, retry_after: int = 60):
        for p in self.pairs:
            if p.key == key and p.model_name == model_cfg["name"]:
                p.mark_limited(retry_after)
                break

    async def mark_error(self, key: str, model_cfg: dict):
        for p in self.pairs:
            if p.key == key and p.model_name == model_cfg["name"]:
                p.mark_error()
                break


# ─── Pool singleton dùng chung toàn pipeline ──────────────────────────────────
_pool = RotationPool(GEMINI_KEYS, GEMINI_MODELS)


def _parse_retry_after(body: bytes) -> int:
    """Parse retryDelay từ response body của Gemini 429."""
    try:
        data = json.loads(body)
        for detail in data.get("error", {}).get("details", []):
            if "retryDelay" in detail:
                return int(float(detail["retryDelay"].replace("s", ""))) + 5
    except (json.JSONDecodeError, KeyError, ValueError):
        pass
    return 60


async def _call_gemini_async(
    prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 8192,
    label: str = "API",
) -> Optional[str]:
    """
    Gọi Gemini API với RotationPool (async).

    Args:
        prompt: Prompt text.
        temperature: Nhiệt độ sinh.
        max_tokens: Token tối đa.
        label: Nhãn log.

    Returns:
        Response text (đã strip markdown fences) hoặc None.
    """
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
        "safetySettings": [
            {"category": c, "threshold": "BLOCK_NONE"}
            for c in SAFETY_CATEGORIES
        ],
    }

    async with httpx.AsyncClient(timeout=60) as client:
        for attempt in range(len(_pool.pairs) + 1):
            key, model_cfg = await _pool.get()
            model_name = model_cfg["name"]
            url = f"{GEMINI_BASE}/v1beta/models/{model_name}:generateContent"
            headers = {
                "Content-Type": "application/json",
                "x-goog-api-key": key,
            }

            try:
                resp = await client.post(url, json=payload, headers=headers)

                if resp.status_code == 200:
                    await _pool.mark_success(key, model_cfg)
                    data = resp.json()
                    text = (
                        data.get("candidates", [{}])[0]
                        .get("content", {})
                        .get("parts", [{}])[0]
                        .get("text", "")
                    )
                    if not text:
                        logger.warning("[%s] attempt=%d | empty response | %s@%s",
                                       label, attempt, key[:8], model_name)
                        continue
                    # Strip markdown fences
                    text = text.replace("```json", "").replace("```html", "").replace("```", "").strip()
                    logger.info("[%s] attempt=%d | OK | %s@%s | %d chars",
                                label, attempt, key[:8], model_name, len(text))
                    return text

                elif resp.status_code == 429:
                    retry_after = _parse_retry_after(resp.content)
                    await _pool.mark_limited(key, model_cfg, retry_after)
                    logger.warning("[%s] attempt=%d | 429 | %s@%s | retry_after=%ds",
                                   label, attempt, key[:8], model_name, retry_after)
                    continue

                elif resp.status_code in (500, 503):
                    await _pool.mark_error(key, model_cfg)
                    logger.warning("[%s] attempt=%d | %d | %s@%s | sleep 3s",
                                   label, attempt, resp.status_code, key[:8], model_name)
                    await asyncio.sleep(3)
                    continue

                else:
                    await _pool.mark_error(key, model_cfg)
                    logger.warning("[%s] attempt=%d | status=%d | %s@%s",
                                   label, attempt, resp.status_code, key[:8], model_name)
                    await asyncio.sleep(1)
                    continue

            except httpx.TimeoutException:
                await _pool.mark_error(key, model_cfg)
                logger.warning("[%s] attempt=%d | timeout | %s@%s | sleep 2s",
                               label, attempt, key[:8], model_name)
                await asyncio.sleep(2)
                continue

            except httpx.RequestError as e:
                await _pool.mark_error(key, model_cfg)
                logger.warning("[%s] attempt=%d | exception: %s | %s@%s | sleep 2s",
                               label, attempt, e, key[:8], model_name)
                await asyncio.sleep(2)
                continue

    logger.error("[%s] Hết attempts → return None", label)
    return None


def call_gemini(
    prompt: str,
    temperature: float = 0.7,
    max_tokens: int = 8192,
    label: str = "API",
) -> Optional[str]:
    """
    Wrapper đồng bộ cho _call_gemini_async.

    Dùng được trong code thường (script_generator, scene_generator).
    """
    return asyncio.run(_call_gemini_async(prompt, temperature, max_tokens, label))
