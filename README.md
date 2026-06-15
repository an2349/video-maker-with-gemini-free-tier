# 🎬 Video Pipeline

**HTML + localTTS + Gemini AI + FFmpeg → Tự động sinh video TikTok/Reels dạng dọc (9:16)**

## 🎯 Dùng để làm gì?
Bạn chỉ cần nhập một chủ đề, pipeline sẽ tự động tạo ra video dọc 9:16 hoàn chỉnh, sẵn sàng đăng TikTok / Reels / Shorts — không cần chỉnh tay. Phù hợp cho các kênh **faceless video** dạng giải thích, facts, lịch sử, quote. Toàn bộ **miễn phí** nhờ Gemini free tier + localTTS. 

Hệ thống pipeline 5 bước, nhận đầu vào là **chủ đề** hoặc **script JSON**, tự động sinh toàn bộ video hoàn chỉnh:

```
[Chủ đề] → B1: Sinh kịch bản (Gemini AI) — hỗ trợ batch cho số cảnh lớn
         → B2: Text → Audio (localTTS local server)
         → B3: JSON → HTML động (Gemini AI)
         → B4: HTML → Video clip (Playwright + FFmpeg x11grab)
         → B5: Ghép clip → Video cuối (FFmpeg concat)
```

---

## 📋 Yêu cầu hệ thống

### System packages
```bash
sudo apt install ffmpeg xvfb chromium-browser python3 python3-pip
```

### Python packages
```bash
pip install -r requirements.txt
playwright install chromium
```

### localTTS local server
Pipeline dùng localTTS local server để sinh audio. Cần chạy server riêng:
```bash
# Ví dụ: localTTS server tại http://localhost:8080

---

## 🚀 Quick Start

### 1. Clone & setup
```bash
cd video-pipeline
cp .env.example .env
```

### 2. Cấu hình `.env`
```env
# Gemini API Keys (comma-separated, xoay vòng tự động)
GEMINI_API_KEYS=AIzaSy...,AIzaSy...

# localTTS local server
localTTS_HOST=http://localhost:8080
localTTS_VOICE=cutefemale
localTTS_SPEED=10

# Dọn temp/ sau khi merge
CLEANUP_TEMP=true
```

### 3. Chạy full pipeline
```bash
python main.py --topic "Mật mã hậu lượng tử" --scenes 5 --style "tech tối màu dramatic"
```

### 4. Output
```
output/final_video.mp4  ← Video TikTok/Reels hoàn chỉnh
```

---

## 📖 CLI Usage

### Full pipeline từ chủ đề
```bash
# 5 cảnh
python main.py --topic "Trí tuệ nhân tạo năm 2025" --scenes 5 --style "tech tối màu dramatic"

# 30 cảnh — tự động chia batch (10 cảnh/lần) để tránh giới hạn output token
python main.py --topic "Giải thích về ML-KEM (CRYSTALS-KYBER)" --scenes 30 --style "tech tối màu"
```

### Dùng script có sẵn (bỏ qua bước 1)
```bash
python main.py --script input/script.json
```

### Chạy từ bước cụ thể
```bash
# Chạy từ bước render (đã có HTML + audio)
python main.py --script input/script.json --from-step 4

# Chạy từ bước 3 (gen HTML) — đã có script + audio
python main.py --script input/script.json --from-step 3
```

### Help
```bash
python main.py --help
```

---

## 🏗️ Cấu trúc dự án

```
video-pipeline/
├── main.py                       # CLI điều phối pipeline
├── config.py                     # Cấu hình toàn cục (API keys, models, paths)
├── requirements.txt              # Python dependencies
├── .env                          # API keys (không commit)
├── .env.example                  # Mẫu file env
├── README.md                     # Bạn đang đọc đây
│
├── pipeline/
│   ├── __init__.py
│   ├── gemini_pool.py            # RotationPool — xoay key/model theo RPM/RPD
│   ├── script_generator.py       # B1: Sinh kịch bản JSON (hỗ trợ batch)
│   ├── tts.py                    # B2: Text → Audio (localTTS async)
│   ├── scene_generator.py        # B3: JSON → HTML động (Gemini)
│   ├── renderer.py               # B4: HTML → Video clip (Playwright + FFmpeg)
│   └── merger.py                 # B5: Ghép clip → output video
│
├── prompts/
│   ├── gen_script.txt            # Prompt sinh kịch bản
│   └── gen_scene.txt             # Prompt sinh HTML/CSS slide
│
├── input/
│   └── script.json               # Script đầu vào/đầu ra
│
├── temp/
│   ├── audio/                    # File audio tạm (.mp3)
│   ├── scenes/                   # File HTML tạm (.html)
│   └── clips/                    # File video tạm (.mp4)
│
└── output/
    └── final_video.mp4           # Video thành phẩm
```

---

## 🔄 Pipeline 5 bước chi tiết

### Bước 1: Sinh kịch bản (`script_generator.py`)
- Đọc prompt từ `prompts/gen_script.txt`
- **Cơ chế batch (MỚI):** Chia nhỏ số cảnh thành các batch 10 cảnh/lần gọi Gemini
  - Ví dụ `--scenes 30`: batch 1 (scene 1-10) → batch 2 (scene 11-20) → batch 3 (scene 21-30)
  - Mỗi batch sau có context từ các batch trước để đảm bảo câu chuyện liền mạch
  - Giải quyết vấn đề Gemini Flash Lite bị giới hạn output token (~8K tokens)
- Gọi Gemini API với temperature schedule giảm dần (0.7 → 0.5 → 0.3) qua 10 lần retry
- Parse JSON bằng `extract_json()` — 3 cơ chế fallback
- Normalize dialogues (tự động sửa `["text"]` → `[{"id":1, "text":"..."}]`)
- Validate cấu trúc (scene, style_hint, dialogues)
- Output: `input/script.json`

### Bước 2: Text → Audio (`tts.py`)
- Gọi localTTS local server cho từng dialogue (async, song song)
- Kiểm soát concurrent bằng semaphore (`MAX_CONCURRENT_TTS=2`)
- Ghép audio: dialogue_1 + silence + dialogue_2 + silence + ... (không silence cuối)
- Đo duration bằng mutagen
- Output: `temp/audio/scene_X.mp3` + cập nhật `script.json` với `duration`

### Bước 3: Sinh HTML (`scene_generator.py`)
- Đọc prompt từ `prompts/gen_scene.txt`
- Tính `timing_hints` từ `dialogue_durations`
- Gọi Gemini API với rotation pool thông minh
- Validate HTML (DOCTYPE, 1080x1920, animation, @keyframes)
- Retry với các model/temperature khác nhau
- Output: `temp/scenes/scene_X.html`

### Bước 4: Render (`renderer.py`)
- Kiểm tra/kích hoạt Xvfb trên `DISPLAY=:99`
- Mở HTML bằng Playwright (headless=false, X11)
- Quay màn hình bằng FFmpeg x11grab
- Ghép audio vào video
- Output: `temp/clips/clip_X.mp4`

### Bước 5: Merge (`merger.py`)
- Tạo file list cho FFmpeg concat demuxer
- Ghép tất cả clip → `output/final_video.mp4`
- In thông tin video (thời lượng, kích thước)
- Dọn temp/ (nếu `CLEANUP_TEMP=true`)

---

## ⚙️ Config

### Gemini Models (trong `config.py`)
```python
GEMINI_MODELS = [
    {"name": "gemma-4-26b-a4b-it",       "rpm": 15, "rpd": 1500},
    {"name": "gemini-flash-lite-latest",  "rpm": 15, "rpd": 1500},
]
```

### RotationPool thông minh
- **RPM đầy** → chờ slot trống, dùng lại cặp đó (KHÔNG nhảy key)
- **RPD cạn** → bỏ cặp đến 00:00 UTC
- **429** → parse `retryDelay` từ response → hard cooldown
- Pool là **singleton global** — tracking chính xác qua các module
- **Model fallback:** nếu gemma-4 lỗi → tự động chuyển gemini-flash-lite

### localTTS
```python
localTTS_HOST  = "http://localhost:8080"
localTTS_VOICE = "cutefemale"
localTTS_SPEED = 10
MAX_CONCURRENT_TTS = 2   # request song song
MAX_RETRIES       = 5
```

---

## 🧪 Test từng bước

```bash
# Test bước 1: sinh kịch bản (5 cảnh)
python -c "from pipeline.script_generator import generate; generate('AI', 5, 'tech')"

# Test bước 2: TTS
python -c "from pipeline.tts import generate_all; import json; generate_all(json.load(open('input/script.json')))"

# Test bước 3: gen HTML
python -c "from pipeline.scene_generator import generate_all; import json; generate_all(json.load(open('input/script.json')))"

# Test bước 4: render 1 cảnh
python -c "from pipeline.renderer import render_scene; import json; s=json.load(open('input/script.json')); render_scene(s[0])"
```

---

## ⚠️ Lưu ý quan trọng

1. **Xvfb phải chạy trước renderer** — pipeline tự động kiểm tra/kích hoạt
2. **localTTS server phải chạy riêng** — pipeline không start server
3. **Duration phải được tính trước khi gen HTML** — `scene["duration"]` + `dialogue_durations`
4. **DISPLAY=:99** phải được set trước khi Playwright và FFmpeg x11grab chạy
5. **Playwright launch headless=false** trên X11 (không dùng `headless=True`)
6. **File list FFmpeg** dùng đường dẫn tuyệt đối hoặc `safe 0`
7. **Thứ tự ghép audio:** dialogue + silence + dialogue + silence + ... (không silence cuối)
8. **Số cảnh lớn (≥30):** Pipeline tự động chia batch 10 cảnh/lần. Mỗi batch gọi Gemini riêng, có context từ batch trước. Nếu AI không sinh đủ, pipeline vẫn tiếp tục với số cảnh hiện có.
