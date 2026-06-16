import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ─── Gemini API Keys (xoay vòng thông minh theo RPM/RPD) ──────────────────────
GEMINI_KEYS: list[str] = [
    key.strip()
    for key in os.getenv("GEMINI_API_KEYS", "").split(",")
    if key.strip()
]
if not GEMINI_KEYS:
    GEMINI_KEYS = [
        "AIzaSyA8lMEE5b5b5b5b5b5b5b5b5b5b5b5b5b5b5b5",
    ]

# Cấu hình model: mỗi model có rpm và rpd riêng
GEMINI_MODELS: list[dict] = [
   # {"name": "gemma-4-31b-it",       "rpm": 15, "rpd": 1500},
    {"name": "gemma-4-26b-a4b-it",   "rpm": 15, "rpd": 1500},
    # {"name": "gemini-3.5-flash",     "rpm": 5,  "rpd": 500},
    # {"name": "gemini-flash-lite-latest", "rpm": 15, "rpd": 1500},
]

# ─── TikTokTTS ────────────────────────────────────────────────────────────────
TIKTOKTTS_HOST: str = os.getenv("TIKTOKTTS_HOST", "http://localhost:8080")
TIKTOKTTS_VOICE: str = os.getenv("TIKTOKTTS_VOICE", "cutefemale")
TIKTOKTTS_SPEED: int = int(os.getenv("TIKTOKTTS_SPEED", "10"))
TIKTOKTTS_PITCH: int = int(os.getenv("TIKTOKTTS_PITCH", "0"))

# ─── Video ────────────────────────────────────────────────────────────────────
VIDEO_WIDTH: int = 1080
VIDEO_HEIGHT: int = 1920
FPS: int = 30
DISPLAY: str = ":99"

# ─── Audio ──────────────────────────────────────────────────────────────────────
SILENCE_BETWEEN_DIALOGUES: float = 0.3   # giây ngừng giữa các thoại
MAX_CONCURRENT_TTS: int = 2              # số request TTS song song
MAX_RETRIES: int = 5

# ─── Paths ────────────────────────────────────────────────────────────────────
PROJECT_ROOT: Path = Path(__file__).parent
INPUT_DIR: Path = PROJECT_ROOT / "input"
TEMP_DIR: Path = PROJECT_ROOT / "temp"
OUTPUT_DIR: Path = PROJECT_ROOT / "output"
PROMPT_DIR: Path = PROJECT_ROOT / "prompts"

# ─── Ensure directories exist ─────────────────────────────────────────────────
for d in [INPUT_DIR, TEMP_DIR / "audio", TEMP_DIR / "scenes", TEMP_DIR / "clips", OUTPUT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ─── Cleanup option ────────────────────────────────────────────────────────────
CLEANUP_TEMP: bool = os.getenv("CLEANUP_TEMP", "true").lower() == "true"
