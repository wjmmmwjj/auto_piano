from __future__ import annotations

import argparse
import base64
import contextlib
import csv
import hashlib
import importlib.util
import io
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import warnings
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, unquote
import urllib.request

import requests

try:
    from .project_score_tools import score_to_code
except ImportError:
    from project_score_tools import score_to_code

BASE_DIR = Path(__file__).resolve().parent.parent
PLAYBACK_DIR = BASE_DIR / "playback"
SONGS_DIR = BASE_DIR / "songs"
OUTPUTS_DIR = PLAYBACK_DIR / "outputs"
ALIAS_DICTIONARY_PATH = PLAYBACK_DIR / "song_aliases.json"
SOURCE_OVERRIDES_PATH = PLAYBACK_DIR / "song_source_overrides.json"
SOURCE_CACHE_PATH = PLAYBACK_DIR / "song_source_cache.json"
MODEL_RUNTIME_CONFIG_PATH = PLAYBACK_DIR / "model_runtime_config.json"

SONGSCRIPTION_BASE_URL = "https://www.songscription.ai"
SONGSCRIPTION_SUPABASE_URL = "https://idyyvscbgssdnwfqaufc.supabase.co"
SONGSCRIPTION_SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlkeXl2c2NiZ3NzZG53ZnFhdWZjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3MzM0Mzk0MjEsImV4cCI6MjA0OTAxNTQyMX0.WjI-nqJYvW6k69xy0lhg1Q9f8AoEPaLKaSrBjVPcWmc"
)
SONGSCRIPTION_AUTH_COOKIE_PREFIX = "sb-idyyvscbgssdnwfqaufc-auth-token"
SONGSCRIPTION_REQUEST_TIMEOUT_SECONDS = 60 * 60
SONGSCRIPTION_POLL_INTERVAL_SECONDS = 8

DEFAULT_SEARCH_SUFFIX = "piano solo"
YOUTUBE_SEARCH_LIMIT = 8
MAX_SUPPORTED_PYTHON = (3, 11)
MIN_NOTE_MS = 1
MAX_NOTE_MS = 30000
CHORD_THRESHOLD_SECONDS = 0.04     # raised from 0.015: groups near-simultaneous notes as one chord

PROJECT_REST_MS = 10
PROJECT_TIME_STEP_MS = 10
PROJECT_MIN_NOTE_MS = 100           # Forced minimum playable duration for newly generated project scores
PROJECT_ULTRA_SHORT_NOTE_MS = 100
PROJECT_ULTRA_SHORT_TARGET_MS = 100
PROJECT_MAX_NOTE_MS = 30000
PROJECT_MAX_CHORD_NOTES = 12
PROJECT_NOTE_MERGE_GAP_SECONDS = 0.02 # Lowered from 0.06 to preserve 'dots' (staccato)
PROJECT_ARP_MIN_SPREAD_MS = 5
PROJECT_ARP_MAX_SPREAD_MS = 120
PROJECT_ARP_RELEASE_MIN_MS = 5
PROJECT_ARP_RELEASE_MAX_MS = 80
PROJECT_HAND_SPLIT_MIDI = 60
PROJECT_NOISE_NOTE_MS = 20        # Lowered from 30: allow shorter clear strikes
PROJECT_REPEAT_RELEASE_MIN_MS = 15
PROJECT_REPEAT_RELEASE_MAX_MS = 60
PROJECT_REPEAT_RELEASE_RATIO = 0.18
PROJECT_REPEAT_TAIL_TOLERANCE_MS = 15
PROJECT_PDF_BPM = 120
PLAYBACK_TIME_STEP_MS = 5
DUPLICATE_NOTE_START_WINDOW_SECONDS = 0.005
DUPLICATE_NOTE_END_WINDOW_SECONDS = 0.02
VALIDATION_SEGMENT_SECONDS = 18
VALIDATION_MAX_SEGMENTS = 3
VALIDATION_BIN_SECONDS = 0.12
VALIDATION_LOW_CONFIDENCE_SCORE = 0.52
VALIDATION_MEDIUM_CONFIDENCE_SCORE = 0.68
FULL_MODE_PRIMARY_TIMEOUT_SECONDS = 8 * 60
FULL_MODE_FALLBACK_TIMEOUT_SECONDS = 6 * 60
FULL_MODE_PROGRESS_REMINDER_SECONDS = 60
DEFAULT_BYTEDANCE_CHECKPOINT = BASE_DIR / ".models" / "piano_transcription_inference-1.0.0-2020-09-16.pth"
BYTEDANCE_CHECKPOINT_SHA256 = "c3fa9730725bf4a762f1c14bc80cd5986eacda01b026f5a4a2525cd607876141"
BYTEDANCE_CHECKPOINT_MIN_BYTES = 160_000_000
BYTEDANCE_CHECKPOINT_URLS = (
    "https://zenodo.org/records/4034264/files/CRNN_note_F1%3D0.9677_pedal_F1%3D0.9186.pth?download=1",
    "https://zenodo.org/record/4034264/files/CRNN_note_F1%3D0.9677_pedal_F1%3D0.9186.pth?download=1",
    "https://huggingface.co/xavriley/midi-transcription-models/resolve/main/note_F1%3D0.9677_pedal_F1%3D0.9186.pth",
)
HF_PRIMARY_SPACE = "Genius-Society/piano_trans"
HF_FALLBACK_SPACE = "asigalov61/ByteDance-Solo-Piano-Audio-to-MIDI-Transcription"
TRANSCRIBE_MODE_QUICK = "quick"
TRANSCRIBE_MODE_FULL = "full"
TRANSCRIBE_MODE_AUTO = "auto"
FORMAL_SCORE_SUFFIX = ".formal.musicxml"
SEARCH_TOKEN_STOPWORDS = {
    "a",
    "an",
    "and",
    "cover",
    "for",
    "from",
    "in",
    "instrumental",
    "of",
    "on",
    "piano",
    "solo",
    "the",
    "to",
    "version",
    "with",
    "you",
}
CHINESE_MUSIC_SUFFIXES = (
    "練習曲",
    "奏鳴曲",
    "夜曲",
    "圓舞曲",
    "協奏曲",
    "前奏曲",
    "幻想曲",
    "即興曲",
    "變奏曲",
    "敘事曲",
)
SPECIAL_SEARCH_RULES = (
    {
        "triggers": ("黑鍵練習曲", "black key etude", "black keys etude", "op 10 no 5", "op.10 no.5"),
        "queries": (
            "黑鍵練習曲 肖邦 鋼琴獨奏",
            "Chopin Black Key Etude Op 10 No 5 piano solo",
            "Chopin Etude Op 10 No 5 piano",
        ),
        "preferred_terms": ("黑鍵練習曲", "black key etude", "肖邦", "蕭邦", "chopin", "etude", "op 10", "op.10", "no 5", "no.5"),
        "blocked_terms": ("jj lin", "林俊傑", "black keys"),
    },
)
PREFERRED_PIANO_TERMS = ("piano", "pianist", "keys", "keyboard")
BONUS_TITLE_TERMS = {
    "solo": 120,
    "cover": 70,
    "arrangement": 70,
    "arr.": 70,
    "instrumental": 50,
    "sheet": 20,
}
PENALTY_TITLE_TERMS = {
    "tutorial": -220,
    "synthesia": -200,
    "midi": -140,
    "karaoke": -220,
    "lyrics": -220,
    "hour": -160,
    "sleep": -120,
    "relax": -80,
    "lofi": -120,
    "easy": -70,
    "slow": -80,
    "violin": -160,
    "guitar": -160,
    "drum": -160,
    "orchestra": -160,
}
TITLE_DECORATION_TERMS = (
    "official",
    "lyrics",
    "lyric",
    "mv",
    "music video",
    "piano",
    "solo",
    "cover",
    "arrangement",
    "tutorial",
    "sheet",
    "midi",
    "live",
    "ver.",
    "version",
    "instrumental",
    "鋼琴",
    "演奏",
    "獨奏",
    "教學",
    "伴奏",
    "樂譜",
)
DEFAULT_ALIAS_DICTIONARY = {
    "黑鍵練習曲": {
        "aliases": [
            "蕭邦黑鍵練習曲",
            "肖邦黑鍵練習曲",
            "Chopin Black Key Etude",
            "Chopin Etude Op.10 No.5",
        ],
        "search_queries": [
            "黑鍵練習曲 肖邦 鋼琴獨奏",
            "Chopin Black Key Etude Op 10 No 5 piano solo",
            "Chopin Etude Op 10 No 5 piano",
        ],
        "preferred_terms": ["黑鍵練習曲", "肖邦", "蕭邦", "Chopin", "Etude", "Op 10", "No 5"],
        "blocked_terms": ["JJ Lin", "林俊傑", "Black Keys"],
    },
    "月光奏鳴曲": {
        "aliases": ["貝多芬月光奏鳴曲", "Moonlight Sonata", "Beethoven Sonata No.14"],
        "search_queries": [
            "月光奏鳴曲 貝多芬 鋼琴獨奏",
            "Beethoven Moonlight Sonata piano solo",
        ],
        "preferred_terms": ["月光奏鳴曲", "Moonlight Sonata", "貝多芬", "Beethoven"],
        "blocked_terms": ["relax", "sleep"],
    },
    "革命練習曲": {
        "aliases": ["蕭邦革命練習曲", "肖邦革命練習曲", "Revolutionary Etude", "Chopin Op.10 No.12"],
        "search_queries": [
            "革命練習曲 肖邦 鋼琴獨奏",
            "Chopin Revolutionary Etude Op 10 No 12 piano solo",
        ],
        "preferred_terms": ["革命練習曲", "Revolutionary Etude", "肖邦", "蕭邦", "Chopin", "Op 10", "No 12"],
        "blocked_terms": ["lesson", "tutorial"],
    },
    "給愛麗絲": {
        "aliases": ["貝多芬給愛麗絲", "Für Elise", "Fur Elise"],
        "search_queries": [
            "給愛麗絲 貝多芬 鋼琴獨奏",
            "Beethoven Fur Elise piano solo",
        ],
        "preferred_terms": ["給愛麗絲", "Für Elise", "Fur Elise", "貝多芬", "Beethoven"],
        "blocked_terms": ["easy", "tutorial"],
    },
    "夢中的婚禮": {
        "aliases": ["理查克萊德曼 夢中的婚禮", "Mariage d'amour", "Richard Clayderman Mariage d'amour"],
        "search_queries": [
            "夢中的婚禮 鋼琴獨奏",
            "Mariage d'amour piano solo",
        ],
        "preferred_terms": ["夢中的婚禮", "Mariage d'amour", "Richard Clayderman", "理查克萊德曼"],
        "blocked_terms": ["lesson", "tutorial"],
    },
    "聖誕快樂勞倫斯先生": {
        "aliases": ["Merry Christmas Mr Lawrence", "坂本龍一 Merry Christmas Mr Lawrence"],
        "search_queries": [
            "聖誕快樂勞倫斯先生 鋼琴獨奏",
            "Merry Christmas Mr Lawrence piano solo",
        ],
        "preferred_terms": ["聖誕快樂勞倫斯先生", "Merry Christmas Mr Lawrence", "坂本龍一", "Ryuichi Sakamoto"],
        "blocked_terms": ["tutorial", "karaoke"],
    },
}
DEFAULT_MODEL_RUNTIME_CONFIG = {
    "_說明": [
        "這個檔案用來設定本地模型與正式譜後處理工具。",
        "bytedance_checkpoint_path 改用相對路徑，整個專案搬到別台電腦也能直接用。",
        "transkun_command 可留空，程式會先嘗試用本機 transkun CLI 或 python -m transkun.transcribe。",
        "midi2scoretransformer_command 可填字串或陣列，支援這些佔位符：{midi_path} {output_musicxml_path} {output_dir} {song_name} {safe_name}",
    ],
    "prefer_device": "auto",
    "bytedance_checkpoint_path": ".models/piano_transcription_inference-1.0.0-2020-09-16.pth",
    "transkun_command": "",
    "midi2scoretransformer_command": "",
}


def banner() -> None:

    print("自動轉譜")



def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]+", "_", value).strip().strip(".")
    return cleaned or "untitled"


def normalize_lookup_key(value: str) -> str:
    tokens = re.findall(r"[\u4e00-\u9fff]+|[a-z0-9]+", value.casefold())
    return "".join(tokens)


def load_json_dict(path: Path, default: dict | None = None) -> dict:
    fallback = dict(default or {})
    if not path.exists():
        return fallback
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback
    if not isinstance(payload, dict):
        return fallback
    return payload


def write_json_dict(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def path_to_portable_string(path: Path | str | None) -> str:
    if path is None:
        return ""
    candidate = Path(path)
    try:
        resolved = candidate.resolve()
    except Exception:
        resolved = candidate
    try:
        relative = resolved.relative_to(BASE_DIR.resolve())
        return relative.as_posix()
    except Exception:
        return str(candidate)


def portable_string_to_path(value: Path | str | None) -> Path | None:
    if value in (None, ""):
        return None
    candidate = Path(str(value))
    if candidate.is_absolute():
        return candidate
    return BASE_DIR / candidate


def normalize_runtime_config_payload(raw_payload: dict[str, object] | None = None) -> dict[str, object]:
    payload = dict(DEFAULT_MODEL_RUNTIME_CONFIG)
    if isinstance(raw_payload, dict):
        payload.update(raw_payload)

    configured_checkpoint = str(payload.get("bytedance_checkpoint_path", "") or "").strip()
    if configured_checkpoint:
        checkpoint_path = Path(configured_checkpoint)
        try:
            if checkpoint_path.is_absolute():
                payload["bytedance_checkpoint_path"] = path_to_portable_string(checkpoint_path)
            else:
                payload["bytedance_checkpoint_path"] = checkpoint_path.as_posix()
        except Exception:
            payload["bytedance_checkpoint_path"] = DEFAULT_MODEL_RUNTIME_CONFIG["bytedance_checkpoint_path"]
    else:
        payload["bytedance_checkpoint_path"] = DEFAULT_MODEL_RUNTIME_CONFIG["bytedance_checkpoint_path"]

    payload["_說明"] = list(DEFAULT_MODEL_RUNTIME_CONFIG["_說明"])
    payload["prefer_device"] = str(payload.get("prefer_device", "auto") or "auto")
    payload["transkun_command"] = payload.get("transkun_command", "") or ""
    payload["midi2scoretransformer_command"] = payload.get("midi2scoretransformer_command", "") or ""
    return payload


def ensure_support_files() -> None:
    if not ALIAS_DICTIONARY_PATH.exists():
        write_json_dict(ALIAS_DICTIONARY_PATH, DEFAULT_ALIAS_DICTIONARY)
    if not SOURCE_OVERRIDES_PATH.exists():
        write_json_dict(
            SOURCE_OVERRIDES_PATH,
            {
                "_說明": "可把歌曲名稱直接指定到固定 YouTube 連結。格式可填字串或物件。",
                "範例歌曲": {
                    "youtube_url": "https://www.youtube.com/watch?v=example",
                    "aliases": ["範例別名", "Example Song"],
                },
            },
        )
    if not SOURCE_CACHE_PATH.exists():
        write_json_dict(SOURCE_CACHE_PATH, {})
    if not MODEL_RUNTIME_CONFIG_PATH.exists():
        write_json_dict(MODEL_RUNTIME_CONFIG_PATH, normalize_runtime_config_payload())


def load_model_runtime_config() -> dict[str, object]:
    ensure_support_files()
    raw_payload = load_json_dict(MODEL_RUNTIME_CONFIG_PATH)
    payload = normalize_runtime_config_payload(raw_payload)
    if raw_payload != payload:
        write_json_dict(MODEL_RUNTIME_CONFIG_PATH, payload)
    return payload


def build_artifact_stem(song_name: str, artifact_tag: str | None = None) -> str:
    extracted_url = extract_youtube_url(youtube_url)
    if not extracted_url:
        raise RuntimeError(f"無法從輸入內容解析出有效的 YouTube 連結：{youtube_url}")
    youtube_url = extracted_url

    extracted_url = extract_youtube_url(youtube_url)
    if not extracted_url:
        raise RuntimeError(f"無法從輸入內容解析出有效的 YouTube 連結：{youtube_url}")
    youtube_url = extracted_url

    safe_name = safe_filename(song_name)
    if artifact_tag:
        return f"{safe_name}.{safe_filename(artifact_tag)}"
    return safe_name


def build_artifact_stem(song_name: str, artifact_tag: str | None = None) -> str:
    safe_name = safe_filename(song_name)
    if artifact_tag:
        return f"{safe_name}.{safe_filename(artifact_tag)}"
    return safe_name


def ensure_dirs() -> None:
    SONGS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    ensure_support_files()


def clear_problematic_env() -> None:
    # Some environments set SSLKEYLOGFILE to an invalid path and break pip/requests.
    os.environ["SSLKEYLOGFILE"] = ""
    for key in list(os.environ):
        if key.lower().endswith("_proxy") or key.lower() == "no_proxy":
            os.environ.pop(key, None)


def build_clean_env(extra_env: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["SSLKEYLOGFILE"] = ""
    for key in list(env):
        if key.lower().endswith("_proxy") or key.lower() == "no_proxy":
            env.pop(key, None)
    if extra_env:
        env.update(extra_env)
    return env


def build_requests_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    return session


def configure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def require_supported_python() -> None:
    current = sys.version_info[:2]
    if current > MAX_SUPPORTED_PYTHON:
        supported = ".".join(map(str, MAX_SUPPORTED_PYTHON))
        now = ".".join(map(str, current))
        raise RuntimeError(
            f"This workflow is pinned for Python <= {supported}. You are running Python {now}. "
            "Please run run_score.bat (it creates a Python 3.11 venv automatically)."
        )


def require_python_module(module_name: str, package_name: str) -> None:
    if importlib.util.find_spec(module_name) is None:
        raise RuntimeError(f"缺少 Python 套件「{package_name}」，請先執行 run_score.bat。")


def run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    print("正在執行外部工具...")
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        env=build_clean_env(extra_env=extra_env),
        check=True,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )


def detect_inference_device(prefer_device: str = "auto") -> str:
    require_python_module("torch", "torch")
    import torch

    normalized = str(os.environ.get("AUTO_SCORE_FORCE_DEVICE") or prefer_device or "auto").strip().lower()
    if normalized == "cpu":
        return "cpu"
    if normalized == "cuda":
        return "cuda" if torch.cuda.is_available() else "cpu"
    return "cuda" if torch.cuda.is_available() else "cpu"


def expand_command_template(template: object, replacements: dict[str, str]) -> list[str]:
    if isinstance(template, str):
        if not template.strip():
            return []
        parts = shlex.split(template, posix=False)
    elif isinstance(template, list):
        parts = [str(item) for item in template if str(item).strip()]
    else:
        return []

    expanded: list[str] = []
    for part in parts:
        current = str(part)
        for key, value in replacements.items():
            current = current.replace("{" + key + "}", value)
        if current:
            expanded.append(current)
    return expanded


def find_transkun_command(runtime_config: dict[str, object]) -> list[str]:
    configured = expand_command_template(runtime_config.get("transkun_command"), {})
    if configured:
        return configured

    transkun_exe = shutil.which("transkun")
    if transkun_exe:
        return [transkun_exe]

    if importlib.util.find_spec("transkun.transcribe") is not None or importlib.util.find_spec("transkun") is not None:
        return [sys.executable, "-m", "transkun.transcribe"]

    raise RuntimeError("找不到 Transkun。請先執行 run_score.bat 安裝 transkun，或在 model_runtime_config.json 指定 transkun_command。")


def resolve_bytedance_checkpoint_path(runtime_config: dict[str, object]) -> Path:
    configured = str(runtime_config.get("bytedance_checkpoint_path", "") or "").strip()
    candidates: list[Path] = []
    if configured:
        configured_path = Path(configured)
        candidates.append(configured_path if configured_path.is_absolute() else (BASE_DIR / configured_path))
    candidates.append(DEFAULT_BYTEDANCE_CHECKPOINT)

    for candidate in candidates:
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate.resolve()

    if candidates:
        return candidates[0].resolve()

    raise RuntimeError("找不到 ByteDance 的模型檔目標位置，請在 model_runtime_config.json 指定 bytedance_checkpoint_path。")


def calculate_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        while True:
            chunk = file_obj.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def is_valid_bytedance_checkpoint(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < BYTEDANCE_CHECKPOINT_MIN_BYTES:
        return False
    return calculate_file_sha256(path).lower() == BYTEDANCE_CHECKPOINT_SHA256


def download_bytedance_checkpoint(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = destination.with_suffix(destination.suffix + ".download")

    def download_via_requests(url: str, temp_path: Path) -> None:
        session = build_requests_session()
        with session.get(url, stream=True, timeout=SONGSCRIPTION_REQUEST_TIMEOUT_SECONDS) as response:
            response.raise_for_status()
            downloaded = 0
            next_report = 32 * 1024 * 1024
            with temp_path.open("wb") as file_obj:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    file_obj.write(chunk)
                    downloaded += len(chunk)
                    if downloaded >= next_report:
                        print(f"    已下載 {downloaded // (1024 * 1024)} MB")
                        next_report += 32 * 1024 * 1024

    def download_via_urllib(url: str, temp_path: Path) -> None:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=SONGSCRIPTION_REQUEST_TIMEOUT_SECONDS) as response, temp_path.open("wb") as file_obj:
            shutil.copyfileobj(response, file_obj)

    def download_via_curl(url: str, temp_path: Path) -> None:
        curl_exe = shutil.which("curl.exe") or shutil.which("curl")
        if not curl_exe:
            raise RuntimeError("系統裡找不到 curl。")
        result = subprocess.run(
            [curl_exe, "-L", url, "-o", str(temp_path)],
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            details = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
            raise RuntimeError(details or "curl 下載失敗。")

    downloaders = (
        ("requests", download_via_requests),
        ("urllib", download_via_urllib),
        ("curl", download_via_curl),
    )
    last_error: Exception | None = None

    for index, url in enumerate(BYTEDANCE_CHECKPOINT_URLS, start=1):
        for downloader_name, downloader in downloaders:
            try:
                print(f"  進度：正在下載 ByteDance 模型檔（來源 {index}/{len(BYTEDANCE_CHECKPOINT_URLS)}，方式 {downloader_name}）...")
                downloader(url, tmp_path)
                if is_valid_bytedance_checkpoint(tmp_path):
                    tmp_path.replace(destination)
                    return destination
                raise RuntimeError("模型檔下載完成，但校驗失敗。")
            except Exception as exc:
                last_error = exc
                with contextlib.suppress(FileNotFoundError):
                    tmp_path.unlink()

    raise RuntimeError(f"無法下載有效的 ByteDance 模型檔：{last_error}")


def ensure_bytedance_checkpoint_ready(runtime_config: dict[str, object]) -> Path:
    checkpoint_path = resolve_bytedance_checkpoint_path(runtime_config)
    if is_valid_bytedance_checkpoint(checkpoint_path):
        return checkpoint_path

    print("  偵測到 ByteDance 模型檔損壞或不完整，正在重新下載官方版本...")
    return download_bytedance_checkpoint(checkpoint_path)


def run_optional_external_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    if not command:
        raise RuntimeError("外部命令設定是空的。")
    return run_command(command, cwd=cwd, extra_env=extra_env)


def find_musescore_executable() -> str | None:
    program_files = os.environ.get("ProgramFiles", "")
    local_app_data = os.environ.get("LocalAppData", "")
    candidates = [
        shutil.which("MuseScore4.exe"),
        shutil.which("MuseScore.exe"),
        shutil.which("musescore.exe"),
        str(BASE_DIR / "tools" / "musescore" / "MuseScore4.exe"),
        str(BASE_DIR / "tools" / "musescore" / "MuseScore.exe"),
        str(Path(program_files) / "MuseScore 4" / "bin" / "MuseScore4.exe") if program_files else None,
        str(Path(program_files) / "MuseScore 4" / "bin" / "MuseScore.exe") if program_files else None,
        str(Path(program_files) / "MuseScore 3" / "bin" / "MuseScore3.exe") if program_files else None,
        str(Path(program_files) / "MuseScore 3" / "bin" / "MuseScore.exe") if program_files else None,
        str(Path(local_app_data) / "Programs" / "MuseScore 4" / "bin" / "MuseScore4.exe") if local_app_data else None,
    ]

    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    return None


def is_youtube_url(value: str) -> bool:
    return extract_youtube_url(value) is not None


def clean_extracted_url(candidate: str) -> str:
    cleaned = str(candidate).strip().replace("&amp;", "&")
    while cleaned and cleaned[0] in "<([{'\"":
        cleaned = cleaned[1:].lstrip()
    while cleaned and cleaned[-1] in ">)]}',\".!?;:":
        cleaned = cleaned[:-1].rstrip()
    return cleaned


def extract_youtube_url(value: str) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None

    markdown_match = re.search(
        r"\((https?://(?:www\.|m\.)?(?:youtube\.com|youtu\.be)/[^)\s<>]+)\)",
        text,
        flags=re.I,
    )
    if markdown_match:
        candidate = clean_extracted_url(markdown_match.group(1))
        if "youtube.com/" in candidate or "youtu.be/" in candidate:
            return candidate

    generic_match = re.search(
        r"https?://(?:www\.|m\.)?(?:youtube\.com|youtu\.be)/[^\s<>]+",
        text,
        flags=re.I,
    )
    if generic_match:
        candidate = clean_extracted_url(generic_match.group(0))
        if "youtube.com/" in candidate or "youtu.be/" in candidate:
            return candidate

    return None


def fetch_youtube_metadata(youtube_url: str) -> dict[str, object]:
    require_python_module("yt_dlp", "yt-dlp")
    clear_problematic_env()

    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--ignore-config",
        "--no-playlist",
        "--dump-single-json",
        youtube_url,
    ]
    result = run_command(command, cwd=BASE_DIR)
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError("影片資訊回傳格式不正確。")
    return payload


def extract_youtube_title_from_metadata(payload: dict[str, object]) -> str:
    for key in ("title", "fulltitle", "alt_title"):
        candidate = normalize_resolved_song_name(str(payload.get(key, "") or ""))
        if candidate:
            return candidate
    return ""


def simplify_title_segment(segment: str) -> str:
    cleaned = str(segment).strip()
    if not cleaned:
        return ""

    cleaned = re.sub(
        r"\b(?:official|lyrics|lyric|music video|piano cover|piano solo|solo piano|piano version|cover|tutorial|sheet music|sheet|midi|live|arrangement|arr\.?)\b",
        " ",
        cleaned,
        flags=re.I,
    )
    cleaned = re.sub(r"(純鋼琴版|鋼琴版|鋼琴演奏版|鋼琴演奏|鋼琴獨奏|獨奏版|高音質|附譜|附谱|樂譜版|乐谱版|教學版|教学版)", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" -|_()[]【】")


def normalize_resolved_song_name(title: str) -> str:
    cleaned = " ".join(str(title).replace("\n", " ").split()).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(
        r"\s*[\(\[【][^\)\]】]{0,80}(official|lyrics|lyric|music video|piano|solo|cover|tutorial|sheet|midi|live|鋼琴|演奏|獨奏|教學|樂譜)[^\)\]】]{0,80}[\)\]】]\s*",
        " ",
        cleaned,
        flags=re.I,
    )
    segments = [
        simplify_title_segment(segment)
        for segment in re.split(r"\s*[-|｜–—:：]\s*", cleaned)
        if simplify_title_segment(segment)
    ]
    if not segments:
        return simplify_title_segment(cleaned) or cleaned.strip(" -|_")

    def score_segment(segment: str) -> tuple[int, int]:
        haystack = segment.casefold()
        score = 0
        if any(term in haystack for term in TITLE_DECORATION_TERMS):
            score -= 200
        if re.search(r"\b(by|cover by|performed by)\b", haystack):
            score -= 120
        if re.search(r"\b(op\.?\s*\d+|no\.?\s*\d+|in\s+[a-g](?:\s+(?:minor|major))?)\b", segment, flags=re.I):
            score += 180
        if re.search(r"[\u4e00-\u9fff]", segment):
            score += min(80, len(segment))
        if re.search(r"\d", segment):
            score += 80
        if "/" in segment:
            score += 40
        if re.fullmatch(r"[A-Za-z .&']{2,24}", segment) and len(segment.split()) <= 3 and not re.search(r"\d", segment):
            score -= 50
        return (score, len(segment))

    best_segment = max(segments, key=score_segment)
    return best_segment.strip(" -|_")


def derive_effective_song_name(user_input: str, source_info: dict[str, object]) -> str:
    if not is_youtube_url(user_input):
        return user_input.strip()

    for key in ("resolved_song_name", "title"):
        candidate = normalize_resolved_song_name(str(source_info.get(key, "")))
        if candidate:
            return candidate
    return user_input.strip()


def pick_latest_file(directory: Path, pattern: str) -> Path | None:
    matches = list(directory.glob(pattern))
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def build_lookup_candidates(song_name: str) -> list[str]:
    values = [song_name.strip(), safe_filename(song_name)]
    values.extend(extract_search_tokens(song_name))

    candidates: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = normalize_lookup_key(value)
        if not key or key in seen:
            continue
        seen.add(key)
        candidates.append(key)
    return candidates


def normalize_alias_entry(canonical_name: str, raw_entry: object) -> dict[str, object] | None:
    if isinstance(raw_entry, str):
        raw_entry = {"aliases": [raw_entry]}
    if not isinstance(raw_entry, dict):
        return None

    aliases = [str(alias).strip() for alias in raw_entry.get("aliases", []) if str(alias).strip()]
    search_queries = [str(query).strip() for query in raw_entry.get("search_queries", []) if str(query).strip()]
    preferred_terms = [str(term).strip() for term in raw_entry.get("preferred_terms", []) if str(term).strip()]
    blocked_terms = [str(term).strip() for term in raw_entry.get("blocked_terms", []) if str(term).strip()]

    return {
        "canonical_name": canonical_name,
        "canonical_key": normalize_lookup_key(canonical_name),
        "aliases": aliases,
        "alias_keys": [normalize_lookup_key(alias) for alias in aliases],
        "search_queries": search_queries,
        "preferred_terms": preferred_terms,
        "blocked_terms": blocked_terms,
    }


def load_alias_entries() -> list[dict[str, object]]:
    ensure_support_files()
    payload = dict(DEFAULT_ALIAS_DICTIONARY)
    payload.update(load_json_dict(ALIAS_DICTIONARY_PATH))

    entries: list[dict[str, object]] = []
    for canonical_name, raw_entry in payload.items():
        normalized = normalize_alias_entry(str(canonical_name), raw_entry)
        if normalized is not None:
            entries.append(normalized)
    return entries


def detect_alias_dictionary_rule(song_name: str) -> dict[str, tuple[str, ...]] | None:
    lookup_candidates = build_lookup_candidates(song_name)
    lookup_haystack = normalize_lookup_key(song_name)

    for entry in load_alias_entries():
        candidate_keys = [str(entry["canonical_key"])] + [str(key) for key in entry["alias_keys"]]
        if any(key and (key in lookup_haystack or key in lookup_candidates or lookup_haystack in key) for key in candidate_keys):
            return {
                "queries": tuple(str(query) for query in entry["search_queries"]),
                "preferred_terms": tuple(term.casefold() for term in entry["preferred_terms"]),
                "blocked_terms": tuple(term.casefold() for term in entry["blocked_terms"]),
            }
    return None


def lookup_source_mapping(path: Path, song_name: str) -> dict[str, object] | None:
    ensure_support_files()
    payload = load_json_dict(path)
    lookup_candidates = build_lookup_candidates(song_name)

    for raw_key, raw_value in payload.items():
        if isinstance(raw_value, str):
            raw_value = {"youtube_url": raw_value}
        if not isinstance(raw_value, dict):
            continue

        candidate_keys = [normalize_lookup_key(str(raw_key))]
        candidate_keys.extend(normalize_lookup_key(str(alias)) for alias in raw_value.get("aliases", []))
        if not any(current_key and current_key in lookup_candidates for current_key in candidate_keys):
            continue

        youtube_url = str(raw_value.get("youtube_url", "")).strip()
        if youtube_url:
            return {"youtube_url": youtube_url, "matched_key": str(raw_key), **raw_value}
    return None


def save_source_cache(song_name: str, source_info: dict[str, object]) -> None:
    ensure_support_files()
    payload = load_json_dict(SOURCE_CACHE_PATH)
    payload[song_name] = {
        "youtube_url": str(source_info.get("youtube_url", "")).strip(),
        "title": str(source_info.get("title", "")).strip(),
        "channel": str(source_info.get("channel", "")).strip(),
        "resolver": str(source_info.get("resolver", "search")).strip(),
        "cached_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    write_json_dict(SOURCE_CACHE_PATH, payload)


def extract_search_tokens(text: str) -> list[str]:
    tokens: list[str] = []

    for token in re.findall(r"[\u4e00-\u9fff]+|[a-z0-9]+", text.lower()):
        if re.search(r"[\u4e00-\u9fff]", token):
            if len(token) >= 2:
                tokens.append(token)
                for suffix in CHINESE_MUSIC_SUFFIXES:
                    if token.endswith(suffix) and len(token) > len(suffix):
                        tokens.append(token[: -len(suffix)])
                        tokens.append(suffix)
                        break
        elif len(token) >= 2 and token not in SEARCH_TOKEN_STOPWORDS:
            tokens.append(token)

    deduped: list[str] = []
    for token in tokens:
        if token not in deduped:
            deduped.append(token)
    return deduped


def detect_special_search_rule(song_name: str) -> dict[str, tuple[str, ...]] | None:
    merged_queries: list[str] = []
    merged_preferred_terms: list[str] = []
    merged_blocked_terms: list[str] = []

    def append_unique(target: list[str], values: Iterable[str]) -> None:
        for value in values:
            current = str(value).strip()
            if current and current not in target:
                target.append(current)

    normalized = song_name.casefold()
    for rule in SPECIAL_SEARCH_RULES:
        triggers = tuple(str(trigger).casefold() for trigger in rule["triggers"])
        if any(trigger in normalized for trigger in triggers):
            append_unique(merged_queries, [str(query) for query in rule["queries"]])
            append_unique(merged_preferred_terms, [str(term).casefold() for term in rule["preferred_terms"]])
            append_unique(merged_blocked_terms, [str(term).casefold() for term in rule["blocked_terms"]])

    alias_rule = detect_alias_dictionary_rule(song_name)
    if alias_rule is not None:
        append_unique(merged_queries, alias_rule["queries"])
        append_unique(merged_preferred_terms, alias_rule["preferred_terms"])
        append_unique(merged_blocked_terms, alias_rule["blocked_terms"])

    if not merged_queries and not merged_preferred_terms and not merged_blocked_terms:
        return None

    return {
        "queries": tuple(merged_queries),
        "preferred_terms": tuple(merged_preferred_terms),
        "blocked_terms": tuple(merged_blocked_terms),
    }


def build_search_queries(song_name: str, search_suffix: str) -> tuple[list[str], dict[str, tuple[str, ...]] | None]:
    queries: list[str] = []
    seen: set[str] = set()

    def add_query(value: str) -> None:
        query = " ".join(value.split()).strip()
        if not query:
            return
        key = query.casefold()
        if key in seen:
            return
        seen.add(key)
        queries.append(query)

    base_query = " ".join(part for part in (song_name.strip(), search_suffix.strip()) if part)
    add_query(base_query)

    special_rule = detect_special_search_rule(song_name)
    if special_rule is not None:
        for query in special_rule["queries"]:
            add_query(query)

    return queries, special_rule


def score_youtube_entry(
    entry: dict[str, object],
    song_name: str,
    special_rule: dict[str, tuple[str, ...]] | None = None,
) -> int:
    title = str(entry.get("title", "") or "")
    channel = str(entry.get("channel", "") or entry.get("uploader", "") or "")
    haystack = f"{title} {channel}".lower()
    score = 0
    song_tokens = extract_search_tokens(song_name)

    if any(term in haystack for term in PREFERRED_PIANO_TERMS):
        score += 320

    for term, bonus in BONUS_TITLE_TERMS.items():
        if term in haystack:
            score += bonus

    for term, penalty in PENALTY_TITLE_TERMS.items():
        if term in haystack:
            score += penalty

    duration = int(entry.get("duration") or 0)
    if 90 <= duration <= 600:
        score += 40
    elif duration and duration < 45:
        score -= 250
    elif duration > 900:
        score -= 40

    token_matches = sum(1 for token in song_tokens if token in haystack)
    if song_tokens:
        if token_matches == 0:
            score -= 450
        elif token_matches == 1 and len(song_tokens) >= 2:
            score -= 80
        score += token_matches * 35

    if special_rule is not None:
        preferred_matches = sum(1 for term in special_rule["preferred_terms"] if term in haystack)
        blocked_matches = sum(1 for term in special_rule["blocked_terms"] if term in haystack)
        if preferred_matches == 0:
            score -= 260
        score += preferred_matches * 80
        score -= blocked_matches * 700

    return score


def search_youtube_entries(search_queries: list[str], limit: int = YOUTUBE_SEARCH_LIMIT) -> list[dict[str, object]]:
    valid_entries: list[dict[str, object]] = []
    seen_urls: set[str] = set()

    for search_query in search_queries:
        command = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--ignore-config",
            "--no-playlist",
            "--dump-single-json",
            f"ytsearch{limit}:{search_query}",
        ]

        result = run_command(command, cwd=BASE_DIR)
        payload = json.loads(result.stdout)
        entries = payload.get("entries")
        if not isinstance(entries, list):
            continue

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            url = str(entry.get("webpage_url", "") or "")
            if not is_youtube_url(url):
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)
            valid_entries.append(entry)
    return valid_entries


def resolve_youtube_url(song_name: str, search_suffix: str) -> dict[str, object]:
    direct_youtube_url = extract_youtube_url(song_name)
    if direct_youtube_url:
        print("\n[1/7] 已使用你提供的影片連結。")
        if direct_youtube_url != song_name.strip():
            print(f"  已自動從輸入內容抽出 YouTube 連結：{direct_youtube_url}")
        try:
            payload = fetch_youtube_metadata(direct_youtube_url)
            title = extract_youtube_title_from_metadata(payload)
            channel = str(payload.get("channel", "") or payload.get("uploader", "") or "").strip()
            canonical_url = str(payload.get("webpage_url", "") or payload.get("original_url", "") or direct_youtube_url).strip()
            if title:
                print(f"  已辨識影片標題：{title}")
            if channel:
                print(f"  來源頻道：{channel}")
            return {
                "youtube_url": canonical_url,
                "title": title,
                "channel": channel,
                "resolver": "direct_url",
                "search_score": 0,
                "top_candidates": [],
                "resolved_song_name": title,
                "original_input": song_name.strip(),
            }
        except Exception as exc:
            print(f"  提醒：影片標題辨識失敗，先沿用你輸入的名稱。原因：{exc}")
            return {
                "youtube_url": direct_youtube_url,
                "title": "",
                "channel": "",
                "resolver": "direct_url",
                "search_score": 0,
                "top_candidates": [],
                "original_input": song_name.strip(),
            }

    require_python_module("yt_dlp", "yt-dlp")
    clear_problematic_env()

    override_info = lookup_source_mapping(SOURCE_OVERRIDES_PATH, song_name)
    if override_info is not None:
        print("\n[1/7] 已套用歌曲來源覆寫。")
        matched_key = str(override_info.get("matched_key", song_name))
        print(f"  覆寫鍵：{matched_key}")
        return {
            "youtube_url": str(override_info["youtube_url"]),
            "title": str(override_info.get("title", "")),
            "channel": str(override_info.get("channel", "")),
            "resolver": "override",
            "search_score": 0,
            "top_candidates": [],
        }

    cached_info = lookup_source_mapping(SOURCE_CACHE_PATH, song_name)
    if cached_info is not None:
        print("\n[1/7] 已使用上次成功的歌曲來源快取。")
        matched_key = str(cached_info.get("matched_key", song_name))
        print(f"  快取鍵：{matched_key}")
        return {
            "youtube_url": str(cached_info["youtube_url"]),
            "title": str(cached_info.get("title", "")),
            "channel": str(cached_info.get("channel", "")),
            "resolver": "cache",
            "search_score": 0,
            "top_candidates": [],
        }

    search_queries, special_rule = build_search_queries(song_name, search_suffix)

    print("\n[1/7] 正在查找影片搜尋結果...")
    if special_rule is not None:
        print("  已啟用強化搜尋規則，會同時比對中文別名與英文正式曲名。")
    try:
        entries = search_youtube_entries(search_queries)
    except subprocess.CalledProcessError as exc:
        error_text = (exc.stdout or "") + "\n" + (exc.stderr or "")
        raise RuntimeError("無法從歌曲名稱找到影片連結。\n" + error_text.strip()) from exc

    if not entries:
        raise RuntimeError("yt-dlp 沒有回傳可用的影片連結。")

    ranked_entries = sorted(
        entries,
        key=lambda entry: score_youtube_entry(entry, song_name, special_rule=special_rule),
        reverse=True,
    )
    top_candidates: list[dict[str, object]] = []
    for entry in ranked_entries[:5]:
        top_candidates.append(
            {
                "title": str(entry.get("title", "") or ""),
                "channel": str(entry.get("channel", "") or entry.get("uploader", "") or ""),
                "webpage_url": str(entry.get("webpage_url", "") or ""),
                "score": score_youtube_entry(entry, song_name, special_rule=special_rule),
            }
        )

    entries = ranked_entries
    selected = entries[0]
    youtube_url = str(selected.get("webpage_url", "") or "")
    if not is_youtube_url(youtube_url):
        raise RuntimeError(f"查到的結果不是影片連結：{youtube_url}")

    selected_title = str(selected.get("title", "") or "")
    selected_channel = str(selected.get("channel", "") or selected.get("uploader", "") or "")
    print(f"  已優先選擇鋼琴版：{selected_title}")
    if selected_channel:
        print(f"  來源頻道：{selected_channel}")
    source_info = {
        "youtube_url": youtube_url,
        "title": selected_title,
        "channel": selected_channel,
        "resolver": "search",
        "search_score": score_youtube_entry(selected, song_name, special_rule=special_rule),
        "top_candidates": top_candidates,
    }
    save_source_cache(song_name, source_info)
    return source_info


def find_ffmpeg_executable() -> str | None:
    program_files = os.environ.get("ProgramFiles", "")
    candidates = [
        shutil.which("ffmpeg"),
        shutil.which("ffmpeg.exe"),
        str(BASE_DIR / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"),
        str(Path(program_files) / "ffmpeg" / "bin" / "ffmpeg.exe") if program_files else None,
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)

    if importlib.util.find_spec("imageio_ffmpeg") is not None:
        import imageio_ffmpeg

        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        if ffmpeg_exe and Path(ffmpeg_exe).exists():
            return str(ffmpeg_exe)

    return None


def prepare_model_input_wav(
    audio_path: Path,
    output_path: Path,
    *,
    sample_rate_hz: int,
    channels: int,
    label: str,
) -> Path:
    ffmpeg_exe = find_ffmpeg_executable()
    if not ffmpeg_exe:
        raise RuntimeError(f"找不到 ffmpeg，無法準備{label}。")

    needs_refresh = (
        not output_path.exists()
        or output_path.stat().st_size <= 0
        or output_path.stat().st_mtime < audio_path.stat().st_mtime
    )
    if not needs_refresh:
        return output_path

    command = [
        ffmpeg_exe,
        "-y",
        "-i",
        str(audio_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        str(sample_rate_hz),
        "-ac",
        str(channels),
        str(output_path),
    ]
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0 or not output_path.exists() or output_path.stat().st_size <= 0:
        details = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
        raise RuntimeError(f"無法準備{label}。\n{details}")
    return output_path


def download_audio_from_youtube(youtube_url: str, output_dir: Path, song_name: str) -> Path:
    require_python_module("yt_dlp", "yt-dlp")
    ffmpeg_exe = find_ffmpeg_executable()
    if not ffmpeg_exe:
        raise RuntimeError("找不到 ffmpeg，請重新執行 run_score.bat 讓依賴補齊。")

    extracted_url = extract_youtube_url(youtube_url)
    if not extracted_url:
        raise RuntimeError(f"無法從輸入內容解析出有效的 YouTube 連結：{youtube_url}")
    youtube_url = extracted_url

    safe_name = safe_filename(song_name)
    output_template = output_dir / f"{safe_name}.%(ext)s"
    target_mp3 = output_dir / f"{safe_name}.mp3"

    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        youtube_url,
        "--ignore-config",
        "--no-playlist",
        "--extract-audio",
        "--audio-format",
        "mp3",
        "--audio-quality",
        "192K",
        "--write-info-json",
        "--ffmpeg-location",
        ffmpeg_exe,
        "--output",
        str(output_template),
    ]

    print("\n[2/7] 正在下載影片音訊...")
    try:
        run_command(command, cwd=BASE_DIR)
    except subprocess.CalledProcessError as exc:
        error_text = (exc.stdout or "") + "\n" + (exc.stderr or "")
        raise RuntimeError("下載 YouTube 音訊失敗。\n" + error_text.strip()) from exc

    if target_mp3.exists() and target_mp3.stat().st_size > 0:
        return target_mp3

    latest_audio = pick_latest_file(output_dir, f"{safe_name}*.mp3")
    if latest_audio and latest_audio.stat().st_size > 0:
        return latest_audio

    raise RuntimeError("音訊下載完成，但找不到可用的 mp3 檔案。")


def copy_provider_file(source: str | None, destination: Path) -> Path | None:
    if not source:
        return None

    src_path = Path(str(source))
    if not src_path.exists() or src_path.stat().st_size == 0:
        return None

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_path, destination)
    return destination


def configure_basic_pitch_runtime() -> None:
    os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
    logging.getLogger().setLevel(logging.ERROR)
    logging.getLogger("tensorflow").setLevel(logging.ERROR)
    warnings.filterwarnings("ignore", module="resampy")
    warnings.filterwarnings("ignore", module="pkg_resources")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def save_basic_pitch_note_events(note_events: list[tuple], destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["start_sec", "end_sec", "pitch", "amplitude", "pitch_bend"])
        for event in note_events:
            if len(event) < 4:
                continue
            writer.writerow(
                [
                    float(event[0]),
                    float(event[1]),
                    int(event[2]),
                    float(event[3]),
                    json.dumps([int(value) for value in event[4]]) if len(event) >= 5 and event[4] is not None else "",
                ]
            )
    return destination


def transcribe_with_basic_pitch(
    audio_path: Path,
    output_dir: Path,
    song_name: str,
    *,
    artifact_tag: str | None = None,
) -> tuple[str, Path, Path, Path | None]:
    require_python_module("basic_pitch", "basic-pitch")
    configure_basic_pitch_runtime()

    from basic_pitch import ICASSP_2022_MODEL_PATH
    from basic_pitch.inference import predict

    artifact_stem = build_artifact_stem(song_name, artifact_tag)
    midi_path = output_dir / f"{artifact_stem}.mid"
    note_events_csv_path = output_dir / f"{artifact_stem}.basic-pitch.csv"

    print("\n[3/7] 正在使用快速模式 Basic Pitch 轉成 MIDI...")
    print("  模式：快速模式（本機 Basic Pitch）")
    print("  進度：模型載入中...")

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        _model_output, midi_data, note_events = predict(str(audio_path), ICASSP_2022_MODEL_PATH)

    print("  進度：正在輸出 MIDI...")
    midi_data.write(str(midi_path))
    save_basic_pitch_note_events(note_events, note_events_csv_path)

    if not midi_path.exists() or midi_path.stat().st_size == 0:
        raise RuntimeError("Basic Pitch 沒有成功輸出 MIDI。")

    print("\n[4/7] 已取得快速轉譜結果。")
    print("  下載中：正在從 MIDI 轉成 MusicXML...")
    raw_musicxml_path = convert_midi_to_musicxml(midi_path, song_name, output_dir, artifact_tag=artifact_tag)
    return "Spotify Basic Pitch（快速模式）", midi_path, raw_musicxml_path, None


def transcribe_with_transkun(
    audio_path: Path,
    output_dir: Path,
    song_name: str,
    *,
    artifact_tag: str | None = None,
) -> tuple[str, Path, Path, Path | None]:
    runtime_config = load_model_runtime_config()
    artifact_stem = build_artifact_stem(song_name, artifact_tag)
    midi_path = output_dir / f"{artifact_stem}.mid"
    raw_musicxml_path = output_dir / f"{artifact_stem}.raw.musicxml"
    prepared_audio_path = output_dir / f"{artifact_stem}.transkun-input.wav"
    command_prefix = find_transkun_command(runtime_config)
    device_name = detect_inference_device(str(runtime_config.get("prefer_device", "auto")))
    print("\n[3/7] 正在使用 Transkun 本地轉譜...")
    print(f"  模式：Transkun（{device_name.upper()}）")
    print("  進度：正在整理音訊...")
    prepared_audio_path = prepare_model_input_wav(
        audio_path,
        prepared_audio_path,
        sample_rate_hz=44100,
        channels=2,
        label="Transkun 輸入音訊",
    )
    command = [*command_prefix, str(prepared_audio_path), str(midi_path), "--device", device_name]

    try:
        run_optional_external_command(command, cwd=BASE_DIR)
    except subprocess.CalledProcessError as exc:
        error_text = (exc.stdout or "") + "\n" + (exc.stderr or "")
        raise RuntimeError("Transkun 轉譜失敗。\n" + error_text.strip()) from exc

    if not midi_path.exists() or midi_path.stat().st_size == 0:
        raise RuntimeError("Transkun 沒有成功輸出 MIDI。")

    print("\n[4/7] 已取得 Transkun 轉譜結果。")
    raw_musicxml_path = convert_midi_to_musicxml(midi_path, song_name, output_dir, artifact_tag=artifact_tag)
    return f"Transkun（{device_name.upper()}）", midi_path, raw_musicxml_path, None


def transcribe_with_bytedance_local(
    audio_path: Path,
    output_dir: Path,
    song_name: str,
    *,
    artifact_tag: str | None = None,
) -> tuple[str, Path, Path, Path | None]:
    require_python_module("piano_transcription_inference", "piano_transcription_inference")
    require_python_module("librosa", "librosa")
    runtime_config = load_model_runtime_config()

    import librosa
    import torch
    from piano_transcription_inference import PianoTranscription, sample_rate

    artifact_stem = build_artifact_stem(song_name, artifact_tag)
    midi_path = output_dir / f"{artifact_stem}.mid"
    prepared_audio_path = output_dir / f"{artifact_stem}.bytedance-input.wav"
    device_name = detect_inference_device(str(runtime_config.get("prefer_device", "auto")))
    device = torch.device(device_name)
    checkpoint_path = ensure_bytedance_checkpoint_ready(runtime_config)

    print("\n[3/7] 正在使用 ByteDance 本地轉譜...")
    print(f"  模式：ByteDance Piano Transcription（{device_name.upper()}）")
    print(f"  模型檔：{checkpoint_path.name}")
    print("  進度：正在整理音訊...")
    prepared_audio_path = prepare_model_input_wav(
        audio_path,
        prepared_audio_path,
        sample_rate_hz=sample_rate,
        channels=1,
        label="ByteDance 輸入音訊",
    )

    print("  Progress: loading waveform into memory...")
    audio, _ = librosa.load(str(prepared_audio_path), sr=sample_rate, mono=True)

    print(f"  Progress: loading ByteDance model on {device_name.upper()}...")
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        transcriptor = PianoTranscription(checkpoint_path=str(checkpoint_path), device=device)

    transcribe_started_at = time.monotonic()
    _transcribe_bytedance_with_progress(
        transcriptor,
        audio,
        str(midi_path),
        sample_rate_hz=sample_rate,
    )
    print(f"  Progress: ByteDance finished in {format_elapsed_seconds(time.monotonic() - transcribe_started_at)}.")

    if not midi_path.exists() or midi_path.stat().st_size == 0:
        raise RuntimeError("ByteDance 沒有成功輸出 MIDI。")

    print("\n[4/7] 已取得 ByteDance 轉譜結果。")
    raw_musicxml_path = convert_midi_to_musicxml(midi_path, song_name, output_dir, artifact_tag=artifact_tag)
    return f"ByteDance Piano Transcription（{device_name.upper()}）", midi_path, raw_musicxml_path, None


def render_progress_bar(progress: float, width: int = 24) -> str:
    clamped = max(0.0, min(1.0, float(progress)))
    filled = max(0, min(width, int(round(clamped * width))))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def _print_bytedance_inference_progress(
    processed_segments: int,
    total_segments: int,
    *,
    processed_audio_seconds: float,
    total_audio_seconds: float,
    elapsed_seconds: float,
) -> None:
    progress = processed_segments / total_segments if total_segments else 1.0
    speed = processed_audio_seconds / elapsed_seconds if elapsed_seconds > 1e-9 else 0.0
    eta_seconds: float | None = None
    if speed > 1e-9 and total_audio_seconds > processed_audio_seconds:
        eta_seconds = max(0.0, (total_audio_seconds - processed_audio_seconds) / speed)

    eta_text = format_eta_seconds(eta_seconds) or "calculating"
    bar = render_progress_bar(progress)
    print(
        "  Progress: inference "
        f"{bar} {processed_segments}/{total_segments} "
        f"({int(round(progress * 100))}%) | audio {processed_audio_seconds:.1f}/{total_audio_seconds:.1f}s "
        f"| speed {speed:.2f}x | ETA {eta_text}",
        flush=True,
    )


def _transcribe_bytedance_with_progress(
    transcriptor,
    audio,
    midi_path: str,
    *,
    sample_rate_hz: int,
) -> dict[str, object]:
    import numpy as np
    import torch
    from piano_transcription_inference.pytorch_utils import move_data_to_device
    from piano_transcription_inference.utilities import RegressionPostProcessor, write_events_to_midi

    audio = audio[None, :]
    audio_len = audio.shape[1]
    segment_samples = int(transcriptor.segment_samples)
    pad_len = int(np.ceil(audio_len / segment_samples)) * segment_samples - audio_len

    if pad_len > 0:
        audio = np.concatenate((audio, np.zeros((1, pad_len), dtype=audio.dtype)), axis=1)

    print("  Progress: slicing waveform into overlapping segments...")
    segments = transcriptor.enframe(audio, segment_samples)
    total_segments = int(len(segments))
    total_audio_seconds = audio_len / float(sample_rate_hz) if sample_rate_hz > 0 else 0.0
    segment_seconds = segment_samples / float(sample_rate_hz) if sample_rate_hz > 0 else 0.0
    hop_seconds = segment_seconds / 2.0
    print(f"  Progress: {total_segments} segments queued from {total_audio_seconds:.1f}s audio.")

    output_chunks: dict[str, list] = {}
    model = transcriptor.model
    device = next(model.parameters()).device
    model.eval()
    started_at = time.monotonic()
    last_report_at = 0.0

    for segment_index in range(total_segments):
        batch_waveform = move_data_to_device(segments[segment_index : segment_index + 1], device)

        with torch.no_grad():
            batch_output_dict = model(batch_waveform)

        for key, value in batch_output_dict.items():
            output_chunks.setdefault(key, []).append(value.data.cpu().numpy())

        if segment_index == 0:
            processed_audio_seconds = min(total_audio_seconds, segment_seconds)
        else:
            processed_audio_seconds = min(total_audio_seconds, segment_seconds + segment_index * hop_seconds)

        now = time.monotonic()
        if segment_index + 1 == total_segments or now - last_report_at >= 1.0:
            _print_bytedance_inference_progress(
                segment_index + 1,
                total_segments,
                processed_audio_seconds=processed_audio_seconds,
                total_audio_seconds=total_audio_seconds,
                elapsed_seconds=now - started_at,
            )
            last_report_at = now

    print("  Progress: merging overlapping segment outputs...")
    output_dict = {key: np.concatenate(values, axis=0) for key, values in output_chunks.items()}
    for key in output_dict.keys():
        output_dict[key] = transcriptor.deframe(output_dict[key])[0:audio_len]

    print("  Progress: decoding note and pedal events...")
    post_processor = RegressionPostProcessor(
        transcriptor.frames_per_second,
        classes_num=transcriptor.classes_num,
        onset_threshold=transcriptor.onset_threshold,
        offset_threshold=transcriptor.offset_threshod,
        frame_threshold=transcriptor.frame_threshold,
        pedal_offset_threshold=transcriptor.pedal_offset_threshold,
    )
    est_note_events, est_pedal_events = post_processor.output_dict_to_midi_events(output_dict)

    print(f"  Progress: writing MIDI with {len(est_note_events)} notes...")
    if midi_path:
        write_events_to_midi(
            start_time=0,
            note_events=est_note_events,
            pedal_events=est_pedal_events,
            midi_path=midi_path,
        )

    return {
        "output_dict": output_dict,
        "est_note_events": est_note_events,
        "est_pedal_events": est_pedal_events,
    }


def format_eta_seconds(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return ""
    if seconds < 60:
        return f"約 {int(round(seconds))} 秒"
    minutes = int(seconds // 60)
    remaining = int(round(seconds % 60))
    return f"約 {minutes} 分 {remaining} 秒"


def format_elapsed_seconds(seconds: float) -> str:
    total_seconds = max(0, int(round(seconds)))
    minutes = total_seconds // 60
    remaining = total_seconds % 60
    return f"{minutes:02d}:{remaining:02d}"


def format_gradio_status_message(status_update, elapsed_seconds: float | None = None) -> str:
    code = getattr(getattr(status_update, "code", None), "value", str(getattr(status_update, "code", "")))
    code = str(code).upper()
    elapsed_suffix = f"（已等待 {format_elapsed_seconds(elapsed_seconds)}）" if elapsed_seconds is not None else ""

    if code in {"STARTING"}:
        return "連線中..." + elapsed_suffix
    if code in {"SENDING_DATA"}:
        return "上傳中..." + elapsed_suffix
    if code in {"JOINING_QUEUE", "IN_QUEUE"}:
        parts = ["排隊中"]
        rank = getattr(status_update, "rank", None)
        queue_size = getattr(status_update, "queue_size", None)
        eta = format_eta_seconds(getattr(status_update, "eta", None))
        if rank is not None and queue_size is not None:
            parts.append(f"目前順位 {rank + 1}/{queue_size}")
        elif rank is not None:
            parts.append(f"目前順位 {rank + 1}")
        if eta:
            parts.append(eta)
        message = "，".join(parts)
        return f"{message}{elapsed_suffix}"
    if code in {"PROCESSING", "ITERATING", "PROGRESS"}:
        progress_data = getattr(status_update, "progress_data", None) or []
        if progress_data:
            unit = progress_data[-1]
            desc = getattr(unit, "desc", None) or "轉譜中"
            progress = getattr(unit, "progress", None)
            index = getattr(unit, "index", None)
            length = getattr(unit, "length", None)
            bits = [str(desc)]
            if progress is not None:
                bits.append(f"{int(progress * 100)}%")
            elif index is not None and length:
                bits.append(f"{index}/{length}")
            return "轉譜中：" + " | ".join(bits) + elapsed_suffix
        eta = format_eta_seconds(getattr(status_update, "eta", None))
        return "轉譜中..." + (f" {eta}" if eta else "") + elapsed_suffix
    if code == "FINISHED":
        return "下載中：正在整理轉譯結果..."
    if code == "QUEUE_FULL":
        return "目前佇列已滿，正在等待空位..." + elapsed_suffix
    if code == "CANCELLED":
        return "已取消。"
    if code == "LOG":
        log = getattr(status_update, "log", None)
        if isinstance(log, tuple) and len(log) >= 2 and log[1]:
            return f"轉譜中：{log[1]}{elapsed_suffix}"
    return "轉譜中..." + elapsed_suffix


def wait_for_gradio_job(job, *, service_name: str, max_wait_seconds: int) -> tuple:
    last_message = ""
    last_emit_at = 0.0
    started_at = time.monotonic()
    last_reminder_bucket = -1

    while True:
        now = time.monotonic()
        elapsed_seconds = now - started_at
        status_update = job.status()
        message = format_gradio_status_message(status_update, elapsed_seconds=elapsed_seconds)

        if message and (message != last_message or now - last_emit_at >= 10.0):
            print(f"  {message}")
            last_message = message
            last_emit_at = now

        if job.done():
            break

        reminder_bucket = int(elapsed_seconds // FULL_MODE_PROGRESS_REMINDER_SECONDS)
        if reminder_bucket > 0 and reminder_bucket != last_reminder_bucket:
            print(f"  提醒：免費完整版可能需要數分鐘，目前 {service_name} 已等待 {format_elapsed_seconds(elapsed_seconds)}。")
            last_reminder_bucket = reminder_bucket

        if elapsed_seconds >= max_wait_seconds:
            raise TimeoutError(
                f"{service_name} 已等待 {format_elapsed_seconds(elapsed_seconds)}，超過上限，將改用備援服務。"
            )

        time.sleep(1.0)

    return job.result()


def transcribe_with_hf_space_primary(
    audio_path: Path,
    output_dir: Path,
    song_name: str,
    *,
    artifact_tag: str | None = None,
) -> tuple[str, Path, Path, Path | None]:
    require_python_module("gradio_client", "gradio_client")
    from gradio_client import Client, handle_file

    artifact_stem = build_artifact_stem(song_name, artifact_tag)
    midi_path = output_dir / f"{artifact_stem}.mid"
    raw_pdf_path = output_dir / f"{artifact_stem}.raw.pdf"
    raw_musicxml_path = output_dir / f"{artifact_stem}.raw.musicxml"
    raw_mxl_path = output_dir / f"{artifact_stem}.raw.mxl"
    raw_abc_path = output_dir / f"{artifact_stem}.raw.abc.txt"
    raw_staff_path = output_dir / f"{artifact_stem}.raw.jpg"

    client = Client(HF_PRIMARY_SPACE)
    job = client.submit(audio_path=handle_file(str(audio_path)), api_name="/upl_infer")
    result = wait_for_gradio_job(
        job,
        service_name=HF_PRIMARY_SPACE,
        max_wait_seconds=FULL_MODE_PRIMARY_TIMEOUT_SECONDS,
    )

    status = str(result[0]).strip() if result else ""
    if status.lower() != "success":
        raise RuntimeError(f"{HF_PRIMARY_SPACE} 回傳失敗：{status or '未知錯誤'}")

    print("  下載中：正在儲存 MIDI / PDF / MusicXML...")
    copied_midi = copy_provider_file(result[1], midi_path)
    copied_pdf = copy_provider_file(result[2], raw_pdf_path)
    copied_musicxml = copy_provider_file(result[3], raw_musicxml_path)
    copy_provider_file(result[4], raw_mxl_path)
    if len(result) > 5 and result[5]:
        raw_abc_path.write_text(str(result[5]), encoding="utf-8")
    if len(result) > 6 and isinstance(result[6], str):
        copy_provider_file(result[6], raw_staff_path)
    elif len(result) > 6 and isinstance(result[6], dict):
        copy_provider_file(result[6].get("path"), raw_staff_path)

    if copied_midi is None:
        raise RuntimeError(f"{HF_PRIMARY_SPACE} 沒有回傳 MIDI 檔。")

    if copied_musicxml is None:
        copied_musicxml = convert_midi_to_musicxml(copied_midi, song_name, output_dir, artifact_tag=artifact_tag)

    return HF_PRIMARY_SPACE, copied_midi, copied_musicxml, copied_pdf


def transcribe_with_hf_space_fallback(
    audio_path: Path,
    output_dir: Path,
    song_name: str,
    *,
    artifact_tag: str | None = None,
) -> tuple[str, Path, Path, Path | None]:
    require_python_module("gradio_client", "gradio_client")
    from gradio_client import Client, handle_file

    artifact_stem = build_artifact_stem(song_name, artifact_tag)
    midi_path = output_dir / f"{artifact_stem}.mid"
    rendered_audio_path = output_dir / f"{artifact_stem}.rendered.wav"
    score_plot_path = output_dir / f"{artifact_stem}.score-plot.json"

    client = Client(HF_FALLBACK_SPACE)
    job = client.submit(input_file=handle_file(str(audio_path)), api_name="/TranscribePianoAudio")
    result = wait_for_gradio_job(
        job,
        service_name=HF_FALLBACK_SPACE,
        max_wait_seconds=FULL_MODE_FALLBACK_TIMEOUT_SECONDS,
    )

    print("  下載中：正在儲存 MIDI...")
    copied_midi = copy_provider_file(result[2], midi_path)
    copy_provider_file(result[3], rendered_audio_path)
    if len(result) > 4 and result[4]:
        score_plot_path.write_text(json.dumps(result[4], ensure_ascii=False, indent=2), encoding="utf-8")

    if copied_midi is None:
        raise RuntimeError(f"{HF_FALLBACK_SPACE} 沒有回傳 MIDI 檔。")

    raw_musicxml_path = convert_midi_to_musicxml(copied_midi, song_name, output_dir, artifact_tag=artifact_tag)
    return HF_FALLBACK_SPACE, copied_midi, raw_musicxml_path, None


def transcribe_with_huggingface(
    audio_path: Path,
    output_dir: Path,
    song_name: str,
    *,
    artifact_tag: str | None = None,
) -> tuple[str, Path, Path, Path | None]:
    clear_problematic_env()
    print("\n[3/7] 正在送到免費線上轉譜服務...")

    primary_error: Exception | None = None
    try:
        provider_name, midi_path, raw_musicxml_path, raw_pdf_path = transcribe_with_hf_space_primary(
            audio_path, output_dir, song_name, artifact_tag=artifact_tag
        )
        print(f"  已使用：{provider_name}")
        print("\n[4/7] 已取得線上轉譜結果。")
        return provider_name, midi_path, raw_musicxml_path, raw_pdf_path
    except Exception as exc:
        primary_error = exc
        print(f"  第一個服務失敗，改用備援：{exc}")

    provider_name, midi_path, raw_musicxml_path, raw_pdf_path = transcribe_with_hf_space_fallback(
        audio_path, output_dir, song_name, artifact_tag=artifact_tag
    )
    print(f"  已使用備援：{provider_name}")
    print("\n[4/7] 已取得線上轉譜結果。")
    if primary_error:
        (output_dir / f"{build_artifact_stem(song_name, artifact_tag)}.primary-error.txt").write_text(
            str(primary_error),
            encoding="utf-8",
        )
    return provider_name, midi_path, raw_musicxml_path, raw_pdf_path


def transcribe_audio(
    audio_path: Path,
    output_dir: Path,
    song_name: str,
    *,
    mode: str,
    source_info: dict[str, object],
) -> dict[str, object]:
    if mode == TRANSCRIBE_MODE_AUTO:
        mode = TRANSCRIBE_MODE_FULL

    if mode == TRANSCRIBE_MODE_QUICK:
        provider_name, midi_path, raw_musicxml_path, raw_pdf_path = transcribe_with_transkun(audio_path, output_dir, song_name)
        quality_report = build_transcription_quality_report(
            song_name=song_name,
            audio_path=audio_path,
            midi_path=midi_path,
            output_dir=output_dir,
            source_info=source_info,
            provider_name=provider_name,
        )
        return {
            "provider_name": provider_name,
            "midi_path": midi_path,
            "raw_musicxml_path": raw_musicxml_path,
            "raw_pdf_path": raw_pdf_path,
            "quality_report": quality_report,
            "candidate_summary_path": None,
            "formal_musicxml_path": None,
        }

    if mode == TRANSCRIBE_MODE_FULL:
        provider_name, midi_path, raw_musicxml_path, raw_pdf_path = transcribe_with_bytedance_local(
            audio_path,
            output_dir,
            song_name,
        )
        quality_report = build_transcription_quality_report(
            song_name=song_name,
            audio_path=audio_path,
            midi_path=midi_path,
            output_dir=output_dir,
            source_info=source_info,
            provider_name=provider_name,
        )
        return {
            "provider_name": provider_name,
            "midi_path": midi_path,
            "raw_musicxml_path": raw_musicxml_path,
            "raw_pdf_path": raw_pdf_path,
            "quality_report": quality_report,
            "candidate_summary_path": None,
            "formal_musicxml_path": None,
        }

    print("\n[3/7] 正在啟用自動最佳化模式，會比較 Transkun 與 ByteDance 後自動選最佳結果...")
    candidate_records: list[dict[str, object]] = []
    successful_candidates: list[dict[str, object]] = []
    candidate_specs = [
        {
            "label": "Transkun",
            "mode": TRANSCRIBE_MODE_QUICK,
            "artifact_tag": "candidate_transkun",
            "runner": transcribe_with_transkun,
        },
        {
            "label": "ByteDance",
            "mode": TRANSCRIBE_MODE_FULL,
            "artifact_tag": "candidate_bytedance",
            "runner": transcribe_with_bytedance_local,
        },
    ]

    for index, spec in enumerate(candidate_specs, start=1):
        artifact_tag = str(spec["artifact_tag"])
        label = str(spec["label"])
        runner = spec["runner"]
        print(f"\n[3/7] 正在測試候選版本 {index}/{len(candidate_specs)}：{label}")
        try:
            provider_name, midi_path, raw_musicxml_path, raw_pdf_path = runner(
                audio_path,
                output_dir,
                song_name,
                artifact_tag=artifact_tag,
            )
            quality_report = build_transcription_quality_report(
                song_name=song_name,
                audio_path=audio_path,
                midi_path=midi_path,
                output_dir=output_dir,
                source_info=source_info,
                provider_name=provider_name,
                artifact_tag=artifact_tag,
            )
            candidate = {
                "label": label,
                "artifact_tag": artifact_tag,
                "mode": str(spec["mode"]),
                "provider_name": provider_name,
                "midi_path": midi_path,
                "raw_musicxml_path": raw_musicxml_path,
                "raw_pdf_path": raw_pdf_path,
                "quality_report": quality_report,
            }
            candidate_records.append(candidate)
            successful_candidates.append(candidate)
            print(
                "  候選評分："
                + f"{extract_quality_score(quality_report):.4f}"
                + f"（{extract_quality_confidence(quality_report)}）"
            )
        except Exception as exc:
            candidate_records.append(
                {
                    "label": label,
                    "artifact_tag": artifact_tag,
                    "mode": str(spec["mode"]),
                    "provider_name": label,
                    "error": str(exc),
                }
            )
            print(f"  候選失敗：{exc}")

    if not successful_candidates:
        error_lines = [f"- {record.get('label', '候選版本')}: {record.get('error', '未知錯誤')}" for record in candidate_records]
        raise RuntimeError("自動最佳化模式失敗，所有候選版本都沒有成功。\n" + "\n".join(error_lines))

    selected_candidate = max(successful_candidates, key=candidate_sort_key)
    candidate_summary_path = write_candidate_summary(song_name, output_dir, candidate_records, selected_candidate)
    midi_path, raw_musicxml_path, raw_pdf_path, quality_report = promote_selected_candidate(
        song_name,
        output_dir,
        selected_candidate,
    )

    print(
        "\n[4/7] 已自動選擇最佳版本："
        + f"{selected_candidate.get('provider_name', '')}"
        + f"（分數 {extract_quality_score(quality_report):.4f}）"
    )
    print(f"  候選比較報告：{candidate_summary_path.name}")

    return {
        "provider_name": str(selected_candidate.get("provider_name", "")),
        "midi_path": midi_path,
        "raw_musicxml_path": raw_musicxml_path,
        "raw_pdf_path": raw_pdf_path,
        "quality_report": quality_report,
        "candidate_summary_path": candidate_summary_path,
        "formal_musicxml_path": None,
    }


def parse_ffmpeg_duration_seconds(ffmpeg_output: str) -> float | None:
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", ffmpeg_output)
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = float(match.group(3))
    return hours * 3600 + minutes * 60 + seconds


def probe_audio_duration_seconds(audio_path: Path) -> float | None:
    ffmpeg_exe = find_ffmpeg_executable()
    if not ffmpeg_exe:
        return None

    result = subprocess.run(
        [ffmpeg_exe, "-i", str(audio_path)],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return parse_ffmpeg_duration_seconds((result.stderr or "") + "\n" + (result.stdout or ""))


def choose_validation_segments(duration_seconds: float | None) -> list[tuple[float, float]]:
    if duration_seconds is None or duration_seconds <= VALIDATION_SEGMENT_SECONDS + 2:
        return [(0.0, VALIDATION_SEGMENT_SECONDS)]

    starts = [0.0]
    if duration_seconds > VALIDATION_SEGMENT_SECONDS * 2:
        starts.append(max(0.0, duration_seconds / 2 - VALIDATION_SEGMENT_SECONDS / 2))
    if duration_seconds > VALIDATION_SEGMENT_SECONDS * 3:
        starts.append(max(0.0, duration_seconds - VALIDATION_SEGMENT_SECONDS - 5))

    cleaned: list[tuple[float, float]] = []
    seen: set[int] = set()
    for start in starts[:VALIDATION_MAX_SEGMENTS]:
        current_start = max(0.0, min(duration_seconds - VALIDATION_SEGMENT_SECONDS, start))
        key = int(round(current_start * 10))
        if key in seen:
            continue
        seen.add(key)
        cleaned.append((current_start, VALIDATION_SEGMENT_SECONDS))

    return cleaned or [(0.0, VALIDATION_SEGMENT_SECONDS)]


def extract_audio_segment(audio_path: Path, segment_path: Path, start_seconds: float, duration_seconds: float) -> Path:
    ffmpeg_exe = find_ffmpeg_executable()
    if not ffmpeg_exe:
        raise RuntimeError("找不到 ffmpeg，無法建立驗證片段。")

    command = [
        ffmpeg_exe,
        "-y",
        "-ss",
        f"{start_seconds:.3f}",
        "-t",
        f"{duration_seconds:.3f}",
        "-i",
        str(audio_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(segment_path),
    ]
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0 or not segment_path.exists():
        raise RuntimeError("無法建立轉譜驗證片段。")
    return segment_path


def transcribe_validation_clip_basic_pitch(segment_path: Path) -> list[tuple]:
    require_python_module("basic_pitch", "basic-pitch")
    configure_basic_pitch_runtime()

    from basic_pitch import ICASSP_2022_MODEL_PATH
    from basic_pitch.inference import predict

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        _model_output, _midi_data, note_events = predict(str(segment_path), ICASSP_2022_MODEL_PATH)
    return note_events


def extract_midi_notes_in_window(midi_path: Path, start_seconds: float, duration_seconds: float) -> list[dict[str, float | int]]:
    require_python_module("pretty_midi", "pretty_midi")
    import pretty_midi

    midi_data = pretty_midi.PrettyMIDI(str(midi_path))
    end_seconds = start_seconds + duration_seconds
    notes: list[dict[str, float | int]] = []

    for instrument in midi_data.instruments:
        if instrument.is_drum:
            continue
        for current_note in instrument.notes:
            if current_note.end < start_seconds or current_note.start > end_seconds:
                continue
            local_start = max(0.0, current_note.start - start_seconds)
            local_end = min(end_seconds, current_note.end) - start_seconds
            if local_end <= local_start:
                continue
            notes.append(
                {
                    "pitch": int(current_note.pitch),
                    "start": local_start,
                    "end": local_end,
                    "duration_ms": int(round((local_end - local_start) * 1000)),
                    "velocity": int(getattr(current_note, "velocity", 100)),
                }
            )
    return notes


def convert_note_events_to_dicts(note_events: Iterable[tuple]) -> list[dict[str, float | int]]:
    converted: list[dict[str, float | int]] = []
    for event in note_events:
        if len(event) < 4:
            continue
        start = float(event[0])
        end = float(event[1])
        if end <= start:
            continue
        converted.append(
            {
                "pitch": int(event[2]),
                "start": start,
                "end": end,
                "duration_ms": int(round((end - start) * 1000)),
                "velocity": int(round(float(event[3]) * 127)) if isinstance(event[3], (float, int)) else 100,
            }
        )
    return converted


def cosine_similarity(values_a: list[float], values_b: list[float]) -> float:
    if not values_a or not values_b or len(values_a) != len(values_b):
        return 0.0
    dot = sum(a * b for a, b in zip(values_a, values_b))
    norm_a = sum(a * a for a in values_a) ** 0.5
    norm_b = sum(b * b for b in values_b) ** 0.5
    if norm_a <= 1e-9 or norm_b <= 1e-9:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


def build_pitch_histogram(notes: Iterable[dict[str, float | int]]) -> list[float]:
    histogram = [0.0] * 12
    for note in notes:
        pitch = int(note["pitch"])
        weight = max(1.0, float(note["duration_ms"]))
        histogram[pitch % 12] += weight
    return histogram


def build_onset_histogram(notes: Iterable[dict[str, float | int]], duration_seconds: float) -> list[float]:
    bin_count = max(1, int(duration_seconds / VALIDATION_BIN_SECONDS) + 1)
    histogram = [0.0] * bin_count
    for note in notes:
        index = min(bin_count - 1, max(0, int(float(note["start"]) / VALIDATION_BIN_SECONDS)))
        histogram[index] += 1.0
    return histogram


def compare_note_sets(reference_notes: list[dict[str, float | int]], candidate_notes: list[dict[str, float | int]], duration_seconds: float) -> dict[str, float]:
    pitch_score = cosine_similarity(build_pitch_histogram(reference_notes), build_pitch_histogram(candidate_notes))
    onset_score = cosine_similarity(
        build_onset_histogram(reference_notes, duration_seconds),
        build_onset_histogram(candidate_notes, duration_seconds),
    )
    reference_count = len(reference_notes)
    candidate_count = len(candidate_notes)
    if reference_count == 0 and candidate_count == 0:
        density_score = 1.0
    elif reference_count == 0 or candidate_count == 0:
        density_score = 0.0
    else:
        density_score = min(reference_count, candidate_count) / max(reference_count, candidate_count)

    overall_score = 0.5 * pitch_score + 0.3 * onset_score + 0.2 * density_score
    return {
        "pitch_score": round(pitch_score, 4),
        "onset_score": round(onset_score, 4),
        "density_score": round(density_score, 4),
        "overall_score": round(overall_score, 4),
    }


def classify_quality_score(score: float) -> str:
    if score >= VALIDATION_MEDIUM_CONFIDENCE_SCORE:
        return "high"
    if score >= VALIDATION_LOW_CONFIDENCE_SCORE:
        return "medium"
    return "low"


def build_transcription_quality_report(
    *,
    song_name: str,
    audio_path: Path,
    midi_path: Path,
    output_dir: Path,
    source_info: dict[str, object],
    provider_name: str,
    artifact_tag: str | None = None,
) -> dict[str, object]:
    artifact_stem = build_artifact_stem(song_name, artifact_tag)
    report_path = output_dir / f"{artifact_stem}.quality-report.json"
    duration_seconds = probe_audio_duration_seconds(audio_path)
    validation_dir = output_dir / "_validation" / artifact_stem
    validation_dir.mkdir(parents=True, exist_ok=True)

    segment_reports: list[dict[str, object]] = []
    ffmpeg_exe = find_ffmpeg_executable()

    if ffmpeg_exe and importlib.util.find_spec("basic_pitch") is not None:
        for index, (start_seconds, clip_duration) in enumerate(choose_validation_segments(duration_seconds), start=1):
            clip_path = validation_dir / f"segment_{index}.wav"
            try:
                extract_audio_segment(audio_path, clip_path, start_seconds, clip_duration)
                reference_events = transcribe_validation_clip_basic_pitch(clip_path)
                reference_notes = convert_note_events_to_dicts(reference_events)
                candidate_notes = extract_midi_notes_in_window(midi_path, start_seconds, clip_duration)
                comparison = compare_note_sets(reference_notes, candidate_notes, clip_duration)
                segment_reports.append(
                    {
                        "segment_index": index,
                        "start_seconds": round(start_seconds, 3),
                        "duration_seconds": round(clip_duration, 3),
                        "reference_note_count": len(reference_notes),
                        "candidate_note_count": len(candidate_notes),
                        **comparison,
                    }
                )
            except Exception as exc:
                segment_reports.append(
                    {
                        "segment_index": index,
                        "start_seconds": round(start_seconds, 3),
                        "duration_seconds": round(clip_duration, 3),
                        "error": str(exc),
                    }
                )
    else:
        segment_reports.append({"error": "缺少 Basic Pitch 或 ffmpeg，略過自動驗證。"})

    valid_scores = [float(item["overall_score"]) for item in segment_reports if "overall_score" in item]
    overall_score = round(sum(valid_scores) / len(valid_scores), 4) if valid_scores else 0.0
    confidence = classify_quality_score(overall_score) if valid_scores else "unknown"

    source_score = float(source_info.get("search_score", 0) or 0)
    resolver_mode = str(source_info.get("resolver", ""))
    if resolver_mode in {"override", "cache", "direct_url"}:
        source_confidence = "high"
    else:
        source_confidence = "high" if source_score >= 300 else "medium" if source_score >= 120 else "low"

    report = {
        "song_name": song_name,
        "provider_name": provider_name,
        "source": {
            "resolver": resolver_mode,
            "youtube_url": str(source_info.get("youtube_url", "")),
            "title": str(source_info.get("title", "")),
            "channel": str(source_info.get("channel", "")),
            "search_score": source_score,
            "confidence": source_confidence,
            "top_candidates": source_info.get("top_candidates", []),
        },
        "transcription_validation": {
            "overall_score": overall_score,
            "confidence": confidence,
            "segments": segment_reports,
        },
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = path_to_portable_string(report_path)
    return report


def extract_quality_score(quality_report: dict[str, object] | None) -> float:
    if not isinstance(quality_report, dict):
        return 0.0
    validation = quality_report.get("transcription_validation", {})
    if not isinstance(validation, dict):
        return 0.0
    try:
        return float(validation.get("overall_score", 0) or 0)
    except Exception:
        return 0.0


def extract_quality_confidence(quality_report: dict[str, object] | None) -> str:
    if not isinstance(quality_report, dict):
        return "unknown"
    validation = quality_report.get("transcription_validation", {})
    if not isinstance(validation, dict):
        return "unknown"
    return str(validation.get("confidence", "unknown") or "unknown")


def candidate_sort_key(candidate: dict[str, object]) -> tuple[float, int, int]:
    score = extract_quality_score(candidate.get("quality_report") if isinstance(candidate, dict) else None)
    provider_name = str(candidate.get("provider_name", "")).lower()
    mode_bonus = 1 if "bytedance" in provider_name or str(candidate.get("mode", "")) == TRANSCRIBE_MODE_FULL else 0
    pdf_bonus = 1 if candidate.get("raw_pdf_path") else 0
    return (score, mode_bonus, pdf_bonus)


def copy_candidate_artifact(source_path: Path | None, destination_path: Path) -> Path | None:
    if source_path is None or not source_path.exists():
        return None

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        same_file = source_path.resolve() == destination_path.resolve()
    except Exception:
        same_file = source_path == destination_path
    if not same_file:
        shutil.copy2(source_path, destination_path)
    return destination_path


def promote_selected_candidate(
    song_name: str,
    output_dir: Path,
    selected_candidate: dict[str, object],
) -> tuple[Path, Path, Path | None, dict[str, object]]:
    final_stem = build_artifact_stem(song_name)
    final_midi_path = output_dir / f"{final_stem}.mid"
    final_raw_musicxml_path = output_dir / f"{final_stem}.raw.musicxml"
    final_raw_pdf_path = output_dir / f"{final_stem}.raw.pdf"
    final_report_path = output_dir / f"{final_stem}.quality-report.json"

    midi_path = copy_candidate_artifact(selected_candidate.get("midi_path"), final_midi_path)
    raw_musicxml_path = copy_candidate_artifact(selected_candidate.get("raw_musicxml_path"), final_raw_musicxml_path)
    raw_pdf_path = copy_candidate_artifact(selected_candidate.get("raw_pdf_path"), final_raw_pdf_path)
    if midi_path is None or raw_musicxml_path is None:
        raise RuntimeError("最佳候選版本缺少必要的 MIDI 或 MusicXML 檔案。")

    quality_report = dict(selected_candidate.get("quality_report", {}))
    source_report_path = quality_report.get("report_path")
    if source_report_path:
        copied_report = copy_candidate_artifact(portable_string_to_path(source_report_path), final_report_path)
        if copied_report is not None:
            quality_report["report_path"] = path_to_portable_string(copied_report)

    return midi_path, raw_musicxml_path, raw_pdf_path, quality_report


def write_candidate_summary(
    song_name: str,
    output_dir: Path,
    candidate_records: list[dict[str, object]],
    selected_candidate: dict[str, object],
) -> Path:
    summary_path = output_dir / f"{safe_filename(song_name)}.candidate-summary.json"
    payload = {
        "song_name": song_name,
        "selected_artifact_tag": str(selected_candidate.get("artifact_tag", "")),
        "selected_provider_name": str(selected_candidate.get("provider_name", "")),
        "selected_mode": str(selected_candidate.get("mode", "")),
        "selected_score": round(extract_quality_score(selected_candidate.get("quality_report")), 4),
        "selected_confidence": extract_quality_confidence(selected_candidate.get("quality_report")),
        "candidates": [],
    }

    for candidate in candidate_records:
        payload["candidates"].append(
            {
                "artifact_tag": str(candidate.get("artifact_tag", "")),
                "label": str(candidate.get("label", "")),
                "mode": str(candidate.get("mode", "")),
                "provider_name": str(candidate.get("provider_name", "")),
                "quality_score": round(extract_quality_score(candidate.get("quality_report")), 4),
                "quality_confidence": extract_quality_confidence(candidate.get("quality_report")),
                "midi_path": path_to_portable_string(candidate.get("midi_path")),
                "raw_musicxml_path": path_to_portable_string(candidate.get("raw_musicxml_path")),
                "raw_pdf_path": path_to_portable_string(candidate.get("raw_pdf_path")) if candidate.get("raw_pdf_path") else "",
                "error": str(candidate.get("error", "")),
            }
        )

    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary_path


def decode_songscription_auth_payload(cookie_value: str) -> dict[str, object]:
    text = re.sub(r'^"|"$', "", unquote(cookie_value.strip()))
    if text.startswith("base64-"):
        text = text[len("base64-") :]

    text = text.strip()
    padding = "=" * (-len(text) % 4)
    candidates = [text + padding, text.replace("-", "+").replace("_", "/") + padding]

    payload_text: str | None = None
    for candidate in candidates:
        for decoder in (base64.b64decode, base64.urlsafe_b64decode):
            try:
                payload_text = decoder(candidate).decode("utf-8")
                break
            except Exception:
                continue
        if payload_text is not None:
            break

    if payload_text is None:
        raise RuntimeError("無法解析 Songscription 的登入憑證。")

    payload = json.loads(payload_text)
    if not isinstance(payload, dict):
        raise RuntimeError("Songscription 登入憑證格式不正確。")
    return payload


def extract_songscription_access_token(context) -> str:
    for cookie in context.cookies():
        name = str(cookie.get("name", ""))
        if SONGSCRIPTION_AUTH_COOKIE_PREFIX not in name and not name.endswith("-auth-token"):
            continue

        value = str(cookie.get("value", ""))
        try:
            payload = decode_songscription_auth_payload(value)
        except Exception:
            continue

        access_token = payload.get("access_token")
        if access_token:
            return str(access_token)

    raise RuntimeError("送出請求後，找不到 Songscription 的登入 token。")


def fetch_songscription_request(request_id: str, auth_token: str) -> dict[str, object]:
    session = build_requests_session()
    response = session.post(
        f"{SONGSCRIPTION_SUPABASE_URL}/rest/v1/rpc/get_request_by_id_v2",
        headers={
            "apikey": SONGSCRIPTION_SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json={"id": request_id},
        timeout=60,
    )
    response.raise_for_status()

    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Songscription 查詢回傳格式不正確。")
    return payload


def format_songscription_state(state: str) -> str:
    state = state.upper()
    mapping = {
        "YOUTUBE_LINK_PROVIDED": "已提供連結",
        "RECEIVED": "已接收",
        "UPLOADED": "已上傳",
        "READY": "已就緒",
        "SUCCESS": "完成",
        "FAILED": "失敗",
        "ERROR": "錯誤",
        "CANCELLED": "已取消",
        "PREPROCESSING_STARTED": "前處理中",
        "PROCESSING": "轉譜中",
        "UPLOADING": "上傳中",
        "QUEUED": "排隊中",
    }
    return mapping.get(state, "處理中")


def wait_for_songscription_request(request_id: str, auth_token: str) -> dict[str, object]:
    print("\n[3/7] 正在等待線上轉譜服務完成...")
    deadline = time.monotonic() + SONGSCRIPTION_REQUEST_TIMEOUT_SECONDS
    last_state = ""
    last_message = ""

    while True:
        request_data = fetch_songscription_request(request_id, auth_token)
        state = str(request_data.get("state", "")).upper()
        message = str(request_data.get("message", "") or request_data.get("error_message", "") or "").strip()

        if state != last_state or message != last_message:
            status_bits = [format_songscription_state(state)]
            if message:
                status_bits.append(message)
            print("  狀態：" + " | ".join(status_bits))
            last_state = state
            last_message = message

        if state == "SUCCESS":
            return request_data

        if state in {"FAILED", "ERROR", "CANCELLED"}:
            raise RuntimeError(message or f"Songscription 以狀態 {state} 結束。")

        if time.monotonic() >= deadline:
            raise RuntimeError("等待 Songscription 完成時逾時。")

        time.sleep(SONGSCRIPTION_POLL_INTERVAL_SECONDS)


def download_songscription_artifact(storage_path: str, auth_token: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded_path = quote(storage_path, safe="/%")
    url = f"{SONGSCRIPTION_SUPABASE_URL}/storage/v1/object/audio-files/{encoded_path}"
    session = build_requests_session()
    response = session.get(
        url,
        headers={
            "apikey": SONGSCRIPTION_SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {auth_token}",
        },
        stream=True,
        timeout=120,
    )
    response.raise_for_status()

    with destination.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=1024 * 128):
            if chunk:
                handle.write(chunk)

    if not destination.exists() or destination.stat().st_size == 0:
        raise RuntimeError(f"下載的檔案是空的：{destination}")
    return destination


def collect_visible_button_texts(page, *, limit: int = 20) -> list[str]:
    texts: list[str] = []
    try:
        buttons = page.locator("button")
        count = buttons.count()
        for index in range(count):
            button = buttons.nth(index)
            try:
                if not button.is_visible():
                    continue
                text = button.inner_text(timeout=2_000)
            except Exception:
                continue

            text = re.sub(r"\s+", " ", text).strip()
            if text:
                texts.append(text)
            if len(texts) >= limit:
                break
    except Exception:
        pass
    return texts


def find_clickable_button(scope, patterns: list[str], *, timeout_ms: int = 60_000):
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        for pattern in patterns:
            locator = scope.get_by_role("button", name=re.compile(pattern, re.I))
            try:
                count = locator.count()
            except Exception:
                continue

            for index in range(count):
                button = locator.nth(index)
                try:
                    if button.is_visible() and button.is_enabled():
                        return button
                except Exception:
                    continue

        time.sleep(0.25)
    return None


def click_first_matching_button(scope, patterns: list[str], *, timeout_ms: int = 60_000) -> bool:
    button = find_clickable_button(scope, patterns, timeout_ms=timeout_ms)
    if button is None:
        return False
    button.scroll_into_view_if_needed(timeout=5_000)
    button.click(timeout=10_000)
    return True


def find_clickable_button_by_text(scope, patterns: list[str], *, timeout_ms: int = 60_000):
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        for pattern in patterns:
            locator = scope.locator("button").filter(has_text=re.compile(pattern, re.I))
            try:
                count = locator.count()
            except Exception:
                continue

            for index in range(count):
                button = locator.nth(index)
                try:
                    if button.is_visible() and button.is_enabled():
                        return button
                except Exception:
                    continue

        time.sleep(0.25)
    return None


def click_first_visible_button_by_text(scope, patterns: list[str], *, timeout_ms: int = 60_000) -> bool:
    button = find_clickable_button_by_text(scope, patterns, timeout_ms=timeout_ms)
    if button is None:
        return False
    button.scroll_into_view_if_needed(timeout=5_000)
    button.click(timeout=10_000)
    return True


def wait_for_processing_or_dialog(page, *, timeout_ms: int = 20_000):
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if re.search(r"/processing/[^/?#]+", page.url):
            return "processing"

        dialog = page.locator('[role="dialog"]')
        try:
            count = dialog.count()
        except Exception:
            count = 0

        for index in range(count - 1, -1, -1):
            candidate = dialog.nth(index)
            try:
                if candidate.is_visible():
                    return candidate
            except Exception:
                continue

        page.wait_for_timeout(250)

    return None


def transcribe_with_songscription(
    youtube_url: str, output_dir: Path, song_name: str
) -> tuple[str, Path | None, Path, Path]:
    require_python_module("playwright", "playwright")
    from playwright.sync_api import sync_playwright

    safe_name = safe_filename(song_name)
    processed_audio_path = output_dir / f"{safe_name}.processed.mp3"
    midi_path = output_dir / f"{safe_name}.mid"
    musicxml_path = output_dir / f"{safe_name}.raw.musicxml"
    request_json_path = output_dir / f"{safe_name}.songscription-request.json"

    print("\n[2/7] 正在把連結送到 Songscription...")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 1024}, locale="en-US")
            page = context.new_page()
            created_request: dict[str, object] | None = None

            def capture_request_response(response) -> None:
                nonlocal created_request
                try:
                    if response.request.method != "POST":
                        return
                    if "/rest/v1/requests" not in response.url:
                        return
                    if response.status not in {200, 201}:
                        return

                    payload = response.json()
                    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
                        if payload[0].get("request_id"):
                            created_request = payload[0]
                except Exception:
                    return

            page.on("response", capture_request_response)
            try:
                page.goto(SONGSCRIPTION_BASE_URL, wait_until="domcontentloaded", timeout=120_000)
                try:
                    page.locator("#youtube-link").wait_for(state="visible", timeout=20_000)
                except Exception:
                    click_first_visible_button_by_text(
                        page,
                        [
                            r"Upload your audio",
                            r"Upload my song",
                        ],
                        timeout_ms=10_000,
                    )
                    page.locator("#youtube-link").wait_for(state="visible", timeout=40_000)
                page.locator("#youtube-link").fill(youtube_url)
                page.locator("#youtube-link").press("Enter")
                request_id = ""
                for _ in range(120):
                    if created_request and created_request.get("request_id"):
                        request_id = str(created_request["request_id"])
                        break
                    page.wait_for_timeout(250)

                if not request_id:
                    visible_buttons = collect_visible_button_texts(page)
                    raise RuntimeError(
                        "線上轉譜服務沒有回傳請求編號。"
                        + (" 可見按鈕：" + ", ".join(visible_buttons) if visible_buttons else "")
                    )

                # The live site reveals the instrument picker after the YouTube link is accepted.
                # Clicking these visible buttons mirrors the browser flow instead of guessing a hidden route.
                if not click_first_visible_button_by_text(
                    page,
                    [
                        r"^Piano$",
                        r"Piano",
                    ],
                    timeout_ms=15_000,
                ):
                    visible_buttons = collect_visible_button_texts(page)
                    raise RuntimeError(
                        "找不到鋼琴選項。"
                        + (" 可見按鈕：" + ", ".join(visible_buttons) if visible_buttons else "")
                    )

                if not click_first_visible_button_by_text(
                    page,
                    [
                        r"Transcribe",
                        r"Let us predict",
                        r"Next Step",
                        r"Direct Transcription",
                    ],
                    timeout_ms=15_000,
                ):
                    visible_buttons = collect_visible_button_texts(page)
                    raise RuntimeError(
                        "找不到下一步或轉譜按鈕。"
                        + (" 可見按鈕：" + ", ".join(visible_buttons) if visible_buttons else "")
                    )

                page.wait_for_timeout(1500)

                auth_token = extract_songscription_access_token(context)
            finally:
                browser.close()
    except Exception as exc:
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError(f"線上轉譜服務的瀏覽器流程失敗：{exc}") from exc

    request_data = wait_for_songscription_request(request_id, auth_token)
    request_json_path.write_text(json.dumps(request_data, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n[4/7] 正在從線上轉譜服務下載中介檔...")
    midi_storage_path = str(request_data.get("midi_path", "")).strip()
    musicxml_storage_path = str(request_data.get("musicxml_path", "")).strip()
    processed_audio_storage_path = str(request_data.get("processed_audio_path", "")).strip()

    if not midi_storage_path:
        raise RuntimeError("線上轉譜服務沒有回傳 MIDI 檔路徑。")

    download_songscription_artifact(midi_storage_path, auth_token, midi_path)

    if musicxml_storage_path:
        download_songscription_artifact(musicxml_storage_path, auth_token, musicxml_path)
    else:
        print("  線上轉譜服務沒有回傳原始樂譜格式，改用本機備援產生。")
        musicxml_path = convert_midi_to_musicxml(midi_path, song_name, output_dir)

    processed_audio_file: Path | None = None
    if processed_audio_storage_path:
        processed_audio_file = download_songscription_artifact(processed_audio_storage_path, auth_token, processed_audio_path)

    return request_id, processed_audio_file, midi_path, musicxml_path


def convert_midi_to_musicxml(
    midi_path: Path,
    song_name: str,
    output_dir: Path,
    *,
    artifact_tag: str | None = None,
) -> Path:
    require_python_module("music21", "music21")
    from music21 import converter, metadata

    print("\n正在儲存備援用原始樂譜檔...")
    score = converter.parse(str(midi_path))
    if score.metadata is None:
        score.metadata = metadata.Metadata()
    score.metadata.title = song_name

    musicxml_path = output_dir / f"{build_artifact_stem(song_name, artifact_tag)}.raw.musicxml"
    with contextlib.redirect_stderr(io.StringIO()):
        score.write("musicxml", fp=str(musicxml_path))
    return musicxml_path


def polish_with_midi2scoretransformer(midi_path: Path, song_name: str, output_dir: Path) -> Path | None:
    runtime_config = load_model_runtime_config()
    template = runtime_config.get("midi2scoretransformer_command")
    safe_name = safe_filename(song_name)
    output_musicxml_path = output_dir / f"{safe_name}{FORMAL_SCORE_SUFFIX}"
    command = expand_command_template(
        template,
        {
            "midi_path": str(midi_path),
            "output_musicxml_path": str(output_musicxml_path),
            "output_dir": str(output_dir),
            "song_name": song_name,
            "safe_name": safe_name,
        },
    )
    if not command:
        return None

    print("\n[6/7] 正在用 MIDI2ScoreTransformer 整理正式樂譜...")
    try:
        run_optional_external_command(command, cwd=BASE_DIR)
    except subprocess.CalledProcessError as exc:
        error_text = (exc.stdout or "") + "\n" + (exc.stderr or "")
        raise RuntimeError("MIDI2ScoreTransformer 執行失敗。\n" + error_text.strip()) from exc

    if output_musicxml_path.exists() and output_musicxml_path.stat().st_size > 0:
        return output_musicxml_path

    fallback_candidates = sorted(
        output_dir.glob(f"{safe_name}*.musicxml"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for candidate in fallback_candidates:
        if candidate.name.endswith(FORMAL_SCORE_SUFFIX):
            return candidate

    raise RuntimeError("MIDI2ScoreTransformer 執行完成，但找不到 formal musicxml 輸出。")


def export_pdf(musicxml_path: Path, song_name: str, output_dir: Path) -> Path | None:
    musescore_exe = find_musescore_executable()
    if not musescore_exe:
        print("\n[7/7] 找不到免費排版軟體，略過列印檔匯出。")
        return None

    pdf_path = output_dir / f"{safe_filename(song_name)}.pdf"
    command = [musescore_exe, "-o", str(pdf_path), str(musicxml_path)]

    print("\n[7/7] 正在匯出列印檔...")
    try:
        run_command(command, cwd=BASE_DIR)
    except subprocess.CalledProcessError as exc:
        error_text = (exc.stdout or "") + "\n" + (exc.stderr or "")
        raise RuntimeError("免費排版軟體匯出列印檔失敗。\n" + error_text.strip()) from exc

    return pdf_path


def quantize_ms(value: int, *, step: int = 50, minimum: int | None = None, maximum: int | None = None) -> int:
    if step <= 0:
        result = value
    else:
        result = int(round(value / step) * step)
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def get_project_target_duration_ms(duration_ms: int) -> int:
    current = int(duration_ms)
    if current <= PROJECT_ULTRA_SHORT_NOTE_MS:
        return PROJECT_ULTRA_SHORT_TARGET_MS
    if current < PROJECT_MIN_NOTE_MS:
        return PROJECT_MIN_NOTE_MS
    return current


def extract_midi_notes(midi_path: Path) -> list[dict[str, float | int]]:
    require_python_module("pretty_midi", "pretty_midi")
    import pretty_midi

    midi_data = pretty_midi.PrettyMIDI(str(midi_path))
    notes: list[dict[str, float | int]] = []

    for instrument in midi_data.instruments:
        if instrument.is_drum:
            continue
        for note in instrument.notes:
            if not (21 <= note.pitch <= 108):
                continue

            duration_ms = int((note.end - note.start) * 1000)
            notes.append(
                {
                    "pitch": note.pitch,
                    "start": note.start,
                    "end": note.end,
                    "duration_ms": max(MIN_NOTE_MS, min(MAX_NOTE_MS, duration_ms)),
                    "velocity": getattr(note, "velocity", 100),
                }
            )

    if not notes:
        raise RuntimeError("No playable notes were found in the generated MIDI.")

    return notes


def merge_same_pitch_notes(notes: list[dict[str, float | int]]) -> list[dict[str, float | int]]:
    merged: list[dict[str, float | int]] = []
    by_pitch = sorted(notes, key=lambda item: (int(item["pitch"]), float(item["start"]), float(item["end"])))

    for note in by_pitch:
        if not merged:
            merged.append(dict(note))
            continue

        prev = merged[-1]
        same_pitch = int(prev["pitch"]) == int(note["pitch"])
        same_start = abs(float(note["start"]) - float(prev["start"])) <= DUPLICATE_NOTE_START_WINDOW_SECONDS
        same_end = abs(float(note["end"]) - float(prev["end"])) <= DUPLICATE_NOTE_END_WINDOW_SECONDS

        # Only collapse near-identical duplicate artifacts. Repeated notes with tiny gaps
        # are musically meaningful for piano and must stay separate.
        if same_pitch and same_start and same_end:
            prev["start"] = min(float(prev["start"]), float(note["start"]))
            prev["end"] = max(float(prev["end"]), float(note["end"]))
            prev["duration_ms"] = max(1, int(round((float(prev["end"]) - float(prev["start"])) * 1000)))
            prev["velocity"] = max(int(prev["velocity"]), int(note["velocity"]))
            continue

        merged.append(dict(note))

    return merged


def infer_natural_note_endings(notes: list[dict[str, float | int]]) -> list[dict[str, float | int]]:
    """Refine repeated-note tails from local timing instead of blunt hard clipping."""
    if not notes:
        return []

    refined = [dict(note) for note in notes]
    by_pitch: dict[int, list[int]] = {}
    for index, note in enumerate(refined):
        by_pitch.setdefault(int(note["pitch"]), []).append(index)

    for pitch_indexes in by_pitch.values():
        ordered = sorted(pitch_indexes, key=lambda idx: (float(refined[idx]["start"]), float(refined[idx]["end"])))
        for order, current_index in enumerate(ordered[:-1]):
            next_index = ordered[order + 1]
            current = refined[current_index]
            following = refined[next_index]

            current_start = float(current["start"])
            current_end = float(current["end"])
            next_start = float(following["start"])
            onset_gap_ms = int(round((next_start - current_start) * 1000))
            if onset_gap_ms <= PROJECT_MIN_NOTE_MS:
                continue

            previous_gap_ms = 0
            if order > 0:
                previous = refined[ordered[order - 1]]
                previous_gap_ms = int(round((current_start - float(previous["start"])) * 1000))

            local_gaps = [gap for gap in (previous_gap_ms, onset_gap_ms) if gap > 0]
            local_gap_ms = min(local_gaps) if local_gaps else onset_gap_ms
            current_duration_ms = int(current["duration_ms"])
            next_duration_ms = int(following["duration_ms"])

            adaptive_release_ms = quantize_ms(
                int(round(max(
                    PROJECT_REPEAT_RELEASE_MIN_MS,
                    min(
                        PROJECT_REPEAT_RELEASE_MAX_MS,
                        local_gap_ms * PROJECT_REPEAT_RELEASE_RATIO,
                        max(current_duration_ms, next_duration_ms) * 0.22,
                    ),
                ))),
                step=PLAYBACK_TIME_STEP_MS,
                minimum=PROJECT_REPEAT_RELEASE_MIN_MS,
                maximum=PROJECT_REPEAT_RELEASE_MAX_MS,
            )

            natural_cap_ms = max(PROJECT_MIN_NOTE_MS, onset_gap_ms - adaptive_release_ms)
            if current_duration_ms <= natural_cap_ms + PROJECT_REPEAT_TAIL_TOLERANCE_MS:
                continue

            required_release_start = next_start - adaptive_release_ms / 1000.0
            if current_end <= required_release_start + PROJECT_REPEAT_TAIL_TOLERANCE_MS / 1000.0:
                continue

            current["end"] = current_start + natural_cap_ms / 1000.0
            current["duration_ms"] = natural_cap_ms

    return refined


def prepare_notes_for_playback(notes: list[dict[str, float | int]]) -> list[dict[str, float | int]]:
    refined_notes = infer_natural_note_endings(merge_same_pitch_notes(notes))
    return [note for note in refined_notes if int(note["duration_ms"]) >= PROJECT_NOISE_NOTE_MS]


def append_wait_command(commands: list[str], wait_ms: int, *, step: int = PROJECT_TIME_STEP_MS) -> None:
    wait_ms = quantize_ms(wait_ms, step=step, minimum=0)
    if wait_ms <= 0:
        return

    if commands and commands[-1].startswith("WAIT,"):
        previous_wait = int(commands[-1].split(",", 1)[1])
        commands[-1] = f"WAIT,{previous_wait + wait_ms}"
    else:
        commands.append(f"WAIT,{wait_ms}")


def normalize_esp32_note_intervals(notes: list[dict[str, float | int]]) -> list[tuple[int, int, int]]:
    intervals_by_pitch: dict[int, list[list[int]]] = {}

    for note in notes:
        pitch = int(note["pitch"])
        start_ms = quantize_ms(int(round(float(note["start"]) * 1000)), step=PLAYBACK_TIME_STEP_MS, minimum=0)
        end_ms = quantize_ms(
            int(round(float(note["end"]) * 1000)),
            step=PLAYBACK_TIME_STEP_MS,
            minimum=start_ms + PROJECT_MIN_NOTE_MS,
        )
        intervals_by_pitch.setdefault(pitch, []).append([start_ms, end_ms])

    normalized: list[tuple[int, int, int]] = []
    for pitch, intervals in intervals_by_pitch.items():
        intervals.sort(key=lambda item: (item[0], item[1]))
        merged: list[list[int]] = []
        for start_ms, end_ms in intervals:
            if merged and start_ms <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end_ms)
            else:
                merged.append([start_ms, end_ms])
        for start_ms, end_ms in merged:
            normalized.append((pitch, start_ms, end_ms))

    normalized.sort(key=lambda item: (item[1], item[0], item[2]))
    return normalized


def build_esp32_playback_lines(notes: list[dict[str, float | int]]) -> list[str]:
    cleaned_notes = prepare_notes_for_playback(notes)
    if not cleaned_notes:
        raise RuntimeError("沒有可輸出的 ESP32 播放事件。")

    timeline: dict[int, dict[str, list[int]]] = {}

    for pitch, start_ms, end_ms in normalize_esp32_note_intervals(cleaned_notes):
        start_slot = timeline.setdefault(start_ms, {"on": [], "off": []})
        end_slot = timeline.setdefault(end_ms, {"on": [], "off": []})
        start_slot["on"].append(pitch)
        end_slot["off"].append(pitch)

    commands: list[str] = []
    cursor_ms = 0

    for time_ms in sorted(timeline):
        append_wait_command(commands, time_ms - cursor_ms, step=PLAYBACK_TIME_STEP_MS)

        change = timeline[time_ms]
        off_notes = sorted(set(int(pitch) for pitch in change["off"]))
        on_notes = sorted(set(int(pitch) for pitch in change["on"]))

        if off_notes:
            commands.append("OFF," + "+".join(str(pitch) for pitch in off_notes))
        if on_notes:
            commands.append("ON," + "+".join(str(pitch) for pitch in on_notes))

        cursor_ms = time_ms

    return commands


def choose_chord_pitches(chord_notes: list[dict[str, float | int]], max_notes: int = PROJECT_MAX_CHORD_NOTES) -> list[int]:
    best_per_pitch: dict[int, dict[str, float | int]] = {}
    for note in chord_notes:
        pitch = int(note["pitch"])
        existing = best_per_pitch.get(pitch)
        if existing is not None and int(note["velocity"]) <= int(existing["velocity"]):
            continue
        best_per_pitch[pitch] = note

    unique_pitches = sorted(best_per_pitch)
    if len(unique_pitches) <= max_notes:
        return unique_pitches

    selected = [unique_pitches[0], unique_pitches[-1]]
    remaining = unique_pitches[1:-1]

    while remaining and len(selected) < max_notes:
        best_pitch = max(remaining, key=lambda pitch: min(abs(pitch - chosen) for chosen in selected))
        selected.append(best_pitch)
        remaining.remove(best_pitch)

    return sorted(selected)


def choose_chord_notes(
    chord_notes: list[dict[str, float | int]],
    *,
    max_notes: int = PROJECT_MAX_CHORD_NOTES,
    preserve_order: bool = False,
) -> list[dict[str, float | int]]:
    best_per_pitch: dict[int, dict[str, float | int]] = {}
    for note in chord_notes:
        pitch = int(note["pitch"])
        existing = best_per_pitch.get(pitch)
        if existing is not None and int(note["velocity"]) <= int(existing["velocity"]):
            continue
        best_per_pitch[pitch] = dict(note)

    unique_pitches = sorted(best_per_pitch)
    if len(unique_pitches) > max_notes:
        selected = [unique_pitches[0], unique_pitches[-1]]
        remaining = unique_pitches[1:-1]
        while remaining and len(selected) < max_notes:
            best_pitch = max(remaining, key=lambda pitch: min(abs(pitch - chosen) for chosen in selected))
            selected.append(best_pitch)
            remaining.remove(best_pitch)
        chosen_pitches = set(selected)
    else:
        chosen_pitches = set(unique_pitches)

    selected_notes = [dict(best_per_pitch[pitch]) for pitch in chosen_pitches]
    if preserve_order:
        selected_notes.sort(key=lambda item: (float(item["start"]), int(item["pitch"])))
    else:
        selected_notes.sort(key=lambda item: int(item["pitch"]))
    return selected_notes


# ---- Context state for dynamic hand gravity tracking ----
_hand_gravity_left: float = 48.0   # running pitch centroid for left hand
_hand_gravity_right: float = 72.0  # running pitch centroid for right hand
_GRAVITY_ALPHA: float = 0.08       # exponential smoothing factor (lower = more stable)

def split_hands(chord_notes: list[dict[str, float | int]]) -> dict[str, list[dict[str, float | int]]]:
    """Dynamically assigns chord notes to L/R hand using a running pitch gravity model.
    This avoids the brittle fixed-MIDI-60 cut, especially for pieces with wide range shifts.
    """
    global _hand_gravity_left, _hand_gravity_right

    left: list[dict[str, float | int]] = []
    right: list[dict[str, float | int]] = []

    if not chord_notes:
        return {"L": left, "R": right}

    pitches = sorted(int(note["pitch"]) for note in chord_notes)
    avg_pitch = sum(pitches) / len(pitches)
    span = pitches[-1] - pitches[0]

    # Very compact chord (span <= 12 semitones = 1 octave): assign as a whole to closest hand
    if span <= 12:
        dist_left  = abs(avg_pitch - _hand_gravity_left)
        dist_right = abs(avg_pitch - _hand_gravity_right)
        if dist_left <= dist_right:
            _hand_gravity_left = (1 - _GRAVITY_ALPHA) * _hand_gravity_left + _GRAVITY_ALPHA * avg_pitch
            return {"L": [dict(n) for n in chord_notes], "R": []}
        else:
            _hand_gravity_right = (1 - _GRAVITY_ALPHA) * _hand_gravity_right + _GRAVITY_ALPHA * avg_pitch
            return {"L": [], "R": [dict(n) for n in chord_notes]}

    # Wide chord: find the largest gap between adjacent pitches to use as the split point
    sorted_notes = sorted(chord_notes, key=lambda n: int(n["pitch"]))
    max_gap = 0
    best_split = int((_hand_gravity_left + _hand_gravity_right) / 2)  # midpoint of running gravities
    for i in range(len(sorted_notes) - 1):
        gap = int(sorted_notes[i + 1]["pitch"]) - int(sorted_notes[i]["pitch"])
        mid  = (int(sorted_notes[i]["pitch"]) + int(sorted_notes[i + 1]["pitch"])) / 2
        # Prefer gaps that are near the midpoint between the two running gravities
        weighted_gap = gap - 0.3 * abs(mid - best_split)
        if weighted_gap > max_gap:
            max_gap = weighted_gap
            best_split = int(sorted_notes[i]["pitch"]) + gap // 2

    # Guard: never let the split drift more than 2 octaves from middle C
    best_split = max(36, min(84, best_split))

    left_pitches: list[float] = []
    right_pitches: list[float] = []
    for note in chord_notes:
        pitch = int(note["pitch"])
        if pitch <= best_split:
            left.append(dict(note))
            left_pitches.append(pitch)
        else:
            right.append(dict(note))
            right_pitches.append(pitch)

    # Update running gravity
    if left_pitches:
        _hand_gravity_left  = (1 - _GRAVITY_ALPHA) * _hand_gravity_left  + _GRAVITY_ALPHA * (sum(left_pitches)  / len(left_pitches))
    if right_pitches:
        _hand_gravity_right = (1 - _GRAVITY_ALPHA) * _hand_gravity_right + _GRAVITY_ALPHA * (sum(right_pitches) / len(right_pitches))

    return {"L": left, "R": right}


def build_arp_offsets(notes: list[dict[str, float | int]]) -> list[int]:
    if not notes:
        return []

    ordered_notes = sorted(notes, key=lambda item: (float(item["start"]), int(item["pitch"])))
    first_start = float(ordered_notes[0]["start"])
    offsets_ms: list[int] = []
    last_offset = 0

    for index, note in enumerate(ordered_notes):
        raw_offset = int(round((float(note["start"]) - first_start) * 1000))
        current_offset = quantize_ms(raw_offset, step=10, minimum=0, maximum=PROJECT_MAX_NOTE_MS)
        if index == 0:
            current_offset = 0
        else:
            current_offset = max(last_offset + PROJECT_ARP_RELEASE_MIN_MS, current_offset)
        offsets_ms.append(current_offset)
        last_offset = current_offset

    if offsets_ms[-1] == 0 and len(offsets_ms) >= 2:
        base_spread = max(
            PROJECT_ARP_MIN_SPREAD_MS,
            min(PROJECT_ARP_MAX_SPREAD_MS, 20 + len(offsets_ms) * 5),
        )
        offsets_ms = [index * base_spread for index in range(len(offsets_ms))]

    return offsets_ms


def make_hand_event(
    hand: str,
    hand_notes: list[dict[str, float | int]],
    duration_ms: int,
    onset_span_ms: int,
) -> tuple:
    if not hand_notes:
        raise RuntimeError("手部事件不能是空的。")

    if len(hand_notes) == 1:
        return (10, hand, int(hand_notes[0]["pitch"]), duration_ms)

    pitches = [int(note["pitch"]) for note in choose_chord_notes(hand_notes, preserve_order=False)]
    if onset_span_ms >= PROJECT_ARP_MIN_SPREAD_MS or len(pitches) >= 4:
        arp_notes = choose_chord_notes(hand_notes, preserve_order=True)
        offsets_ms = build_arp_offsets(arp_notes)
        if not offsets_ms:
            offsets_ms = [index * PROJECT_ARP_MIN_SPREAD_MS for index in range(len(arp_notes))]
        average_gap = offsets_ms[-1] // max(1, len(offsets_ms) - 1) if len(offsets_ms) >= 2 else PROJECT_ARP_MIN_SPREAD_MS
        release_ms = max(
            PROJECT_ARP_RELEASE_MIN_MS,
            min(PROJECT_ARP_RELEASE_MAX_MS, max(average_gap // 2, 10)),
        )
        return (12, hand, [int(note["pitch"]) for note in arp_notes], duration_ms, offsets_ms, release_ms)
    return (11, hand, pitches, duration_ms)


def build_project_score(notes: list[dict[str, float | int]]) -> list[tuple]:
    global _hand_gravity_left, _hand_gravity_right
    # Reset running gravity for each new song so previous piece doesn't contaminate
    _hand_gravity_left  = 48.0
    _hand_gravity_right = 72.0

    cleaned_notes = prepare_notes_for_playback(notes)
    cleaned_notes.sort(key=lambda item: (float(item["start"]), int(item["pitch"])))

    score: list[tuple] = []
    last_start_time = 0.0
    index = 0

    while index < len(cleaned_notes):
        current = cleaned_notes[index]
        chord_notes = [current]
        probe = index + 1

        while probe < len(cleaned_notes):
            next_note = cleaned_notes[probe]
            if abs(float(next_note["start"]) - float(current["start"])) <= CHORD_THRESHOLD_SECONDS:
                chord_notes.append(next_note)
                probe += 1
            else:
                break

        delta_ms = quantize_ms(
            int((float(current["start"]) - last_start_time) * 1000),
            step=PROJECT_TIME_STEP_MS,
            minimum=0
        )
        if delta_ms > 0:
            score.append((0, delta_ms))

        chord_duration_ms = get_project_target_duration_ms(
            quantize_ms(
                max(int(note["duration_ms"]) for note in chord_notes),
                step=PROJECT_TIME_STEP_MS,
                minimum=0,
                maximum=PROJECT_MAX_NOTE_MS,
            )
        )
        onset_span_ms = quantize_ms(
            int((max(float(note["start"]) for note in chord_notes) - min(float(note["start"]) for note in chord_notes)) * 1000),
            step=PROJECT_TIME_STEP_MS,
            minimum=0,
            maximum=PROJECT_MAX_NOTE_MS,
        )
        hands = split_hands(chord_notes)

        if hands["L"] and hands["R"]:
            score.append(make_hand_event("L", hands["L"], chord_duration_ms, onset_span_ms))
            score.append(make_hand_event("R", hands["R"], chord_duration_ms, onset_span_ms))
        elif hands["L"]:
            score.append(make_hand_event("L", hands["L"], chord_duration_ms, onset_span_ms))
        elif hands["R"]:
            score.append(make_hand_event("R", hands["R"], chord_duration_ms, onset_span_ms))
        else:
            # Fallback
            pitches = choose_chord_pitches(chord_notes)
            if pitches:
                if len(pitches) == 1:
                    score.append((1, pitches[0], chord_duration_ms))
                else:
                    score.append((3, pitches, chord_duration_ms))

        last_start_time = float(current["start"])
        index = probe

    return merge_score_rests(score)


def merge_score_rests(score: list[tuple]) -> list[tuple]:
    merged: list[tuple] = []
    for item in score:
        if item[0] == 0 and merged and merged[-1][0] == 0:
            merged[-1] = (0, int(merged[-1][1]) + int(item[1]))
        else:
            merged.append(item)
    return merged


def score_to_project_musicxml(score_data: list[tuple], song_name: str, output_dir: Path) -> Path:
    require_python_module("music21", "music21")
    from music21 import chord, metadata, meter, note, stream, tempo

    print("\n[6/7] 正在把中介檔轉成專案樂譜...")
    project_score = stream.Score()
    left_part = stream.Part()
    right_part = stream.Part()
    left_part.id = "LH"
    right_part.id = "RH"
    left_part.partName = "Left Hand"
    right_part.partName = "Right Hand"
    left_part.append(tempo.MetronomeMark(number=PROJECT_PDF_BPM))
    right_part.append(tempo.MetronomeMark(number=PROJECT_PDF_BPM))
    left_part.append(meter.TimeSignature("4/4"))
    right_part.append(meter.TimeSignature("4/4"))

    if project_score.metadata is None:
        project_score.metadata = metadata.Metadata()
    project_score.metadata.title = f"{song_name} (Project Arrangement)"

    quarter_ms = 60000 / PROJECT_PDF_BPM
    cursor_q = 0.0
    display_step_q = 0.0625
    min_display_quarter = display_step_q

    def quantize_display_q(value: float, *, minimum: float | None = None) -> float:
        current = value
        if minimum is not None:
            current = max(minimum, current)
        quantized = round(current / display_step_q) * display_step_q
        if minimum is not None:
            quantized = max(minimum, quantized)
        return quantized or display_step_q

    def arp_offsets_to_quarter_offsets(offset_data, note_count: int) -> list[float]:
        if isinstance(offset_data, (list, tuple)):
            offsets_q = [quantize_display_q(max(0.0, int(value) / quarter_ms), minimum=0.0) for value in offset_data[:note_count]]
            while len(offsets_q) < note_count:
                offsets_q.append(offsets_q[-1] if offsets_q else 0.0)
            return offsets_q

        spread_q = quantize_display_q(int(offset_data) / quarter_ms, minimum=display_step_q)
        return [index * spread_q for index in range(note_count)]

    def add_hand_event(hand: str, event: tuple) -> None:
        target_part = left_part if hand == "L" else right_part

        if event[0] == 10:
            element = note.Note(int(event[2]), quarterLength=quantize_display_q(int(event[3]) / quarter_ms, minimum=min_display_quarter))
            target_part.insert(cursor_q, element)
        elif event[0] == 11:
            element = chord.Chord([int(p) for p in event[2]], quarterLength=quantize_display_q(int(event[3]) / quarter_ms, minimum=min_display_quarter))
            target_part.insert(cursor_q, element)
        elif event[0] == 12:
            duration_q = quantize_display_q(int(event[3]) / quarter_ms, minimum=min_display_quarter)
            offsets_q = arp_offsets_to_quarter_offsets(event[4], len(event[2]))
            for idx, pitch in enumerate(event[2]):
                target_part.insert(quantize_display_q(cursor_q + offsets_q[idx], minimum=0.0), note.Note(int(pitch), quarterLength=duration_q))

    for item in score_data:
        if item[0] == 0:
            delta_quarter = quantize_display_q(int(item[1]) / quarter_ms, minimum=0.0)
            cursor_q = quantize_display_q(cursor_q + delta_quarter, minimum=0.0)
            continue
        elif item[0] == 1:
            duration_quarter_length = quantize_display_q(int(item[2]) / quarter_ms, minimum=min_display_quarter)
            right_part.insert(quantize_display_q(cursor_q, minimum=0.0), note.Note(int(item[1]), quarterLength=duration_quarter_length))
            continue
        elif item[0] == 4:
            duration_quarter_length = quantize_display_q(int(item[2]) / quarter_ms, minimum=min_display_quarter)
            offsets_quarter = arp_offsets_to_quarter_offsets(item[3], len(item[1]))
            for idx, pitch in enumerate(item[1]):
                right_part.insert(quantize_display_q(cursor_q + offsets_quarter[idx], minimum=0.0), note.Note(int(pitch), quarterLength=duration_quarter_length))
            continue
        elif item[0] in (10, 11, 12):
            hand = str(item[1]).upper()
            add_hand_event("L" if hand.startswith("L") else "R", item)
            continue
        else:
            duration_quarter_length = quantize_display_q(int(item[2]) / quarter_ms, minimum=min_display_quarter)
            right_part.insert(quantize_display_q(cursor_q, minimum=0.0), chord.Chord([int(p) for p in item[1]], quarterLength=duration_quarter_length))
            continue

    project_score.append(left_part)
    project_score.append(right_part)

    musicxml_path = output_dir / f"{safe_filename(song_name)}.musicxml"
    with contextlib.redirect_stderr(io.StringIO()):
        project_score.write("musicxml", fp=str(musicxml_path))
    return musicxml_path


def midi_to_score(midi_path: Path) -> list[tuple]:
    print("\n[5/7] 正在把原始 MIDI 轉成專案 SCORE...")
    notes = extract_midi_notes(midi_path)
    return build_project_score(notes)


def save_score_files(song_name: str, score: list[tuple], output_dir: Path, esp32_lines: list[str]) -> tuple[Path, Path]:
    code = score_to_code(score, song_name, esp32_lines=esp32_lines)
    safe_name = safe_filename(song_name)
    song_file = SONGS_DIR / f"{safe_name}.py"
    song_file.write_text(code, encoding="utf-8")

    esp32_txt = output_dir / f"{safe_name}.esp32.txt"
    esp32_txt.write_text("\n".join(esp32_lines) + "\n", encoding="utf-8")

    return song_file, esp32_txt


def build_process_result(
    *,
    song_name: str,
    output_dir: Path,
    source_info: dict[str, object],
    provider_name: str,
    score_path: Path,
    esp32_txt_path: Path,
) -> dict[str, object]:
    return {
        "song_name": song_name,
        "output_dir": str(output_dir.resolve()),
        "score_path": str(score_path.resolve()),
        "esp32_txt_path": str(esp32_txt_path.resolve()),
        "provider_name": provider_name,
        "youtube_url": str(source_info.get("youtube_url", "") or ""),
        "title": str(source_info.get("title", "") or ""),
        "channel": str(source_info.get("channel", "") or ""),
    }


def print_summary(
    *,
    song_name: str,
    output_dir: Path,
    source_info: dict[str, object],
    provider_name: str,
    audio_path: Path | None,
    midi_path: Path,
    raw_musicxml_path: Path,
    raw_pdf_path: Path | None,
    project_musicxml_path: Path,
    formal_musicxml_path: Path | None,
    pdf_path: Path | None,
    score_path: Path,
    esp32_txt_path: Path,
    quality_report: dict[str, object] | None,
    candidate_summary_path: Path | None = None,
) -> None:
    print("\n完成。")
    print(f"歌曲：      {song_name}")
    print(f"輸出資料夾：{output_dir}")
    print(f"來源網址：  {source_info.get('youtube_url', '')}")
    if source_info.get("title"):
        print(f"來源標題：  {source_info.get('title')}")
    if source_info.get("channel"):
        print(f"來源頻道：  {source_info.get('channel')}")
    if source_info.get("resolver"):
        print(f"來源模式：  {source_info.get('resolver')}")
    print(f"轉譜來源：  {provider_name}")
    print(f"音訊檔：    {audio_path.name if audio_path else '略過'}")
    print(f"中介轉譯檔：{midi_path.name}")
    print(f"原始樂譜：  {raw_musicxml_path.name}")
    print(f"原始 PDF：  {raw_pdf_path.name if raw_pdf_path else '略過'}")
    print(f"專案樂譜：  {project_musicxml_path.name}")
    print(f"正式樂譜：  {formal_musicxml_path.name if formal_musicxml_path else '略過（未啟用 MIDI2ScoreTransformer）'}")
    print(f"專案 PDF：  {pdf_path.name if pdf_path else '略過（找不到免費排版軟體）'}")
    print(f"樂譜程式：  {score_path}")
    print(f"ESP32 控制指令：{esp32_txt_path}")
    if quality_report is not None:
        validation = quality_report.get("transcription_validation", {})
        print(f"自動檢查：  {validation.get('confidence', 'unknown')} ({validation.get('overall_score', 0)})")
        print(f"檢查報告：  {quality_report.get('report_path', '')}")
    if candidate_summary_path is not None:
        print(f"候選比較：  {candidate_summary_path}")


def process_song(
    song_name: str,
    *,
    transcribe_mode: str,
    search_suffix: str,
    export_pdf_enabled: bool,
    play_after_export: bool,
    com_port: str | None,
    overlap: int,
) -> dict[str, object]:
    ensure_dirs()
    requested_song_name = song_name.strip()
    source_info = resolve_youtube_url(requested_song_name, search_suffix)
    effective_song_name = derive_effective_song_name(requested_song_name, source_info)
    if effective_song_name != requested_song_name:
        print(f"\n已自動改用辨識出的歌曲名稱：{effective_song_name}")

    song_name = effective_song_name
    safe_name = safe_filename(song_name)
    output_dir = OUTPUTS_DIR / safe_name
    output_dir.mkdir(parents=True, exist_ok=True)

    source_url = str(source_info.get("youtube_url", ""))
    (output_dir / f"{safe_name}.source-url.txt").write_text(source_url + "\n", encoding="utf-8")
    (output_dir / f"{safe_name}.source-info.json").write_text(
        json.dumps(source_info, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    audio_path = download_audio_from_youtube(source_url, output_dir, song_name)
    transcription_result = transcribe_audio(
        audio_path,
        output_dir,
        song_name,
        mode=transcribe_mode,
        source_info=source_info,
    )
    provider_name = str(transcription_result["provider_name"])
    midi_path = Path(transcription_result["midi_path"])
    raw_musicxml_path = Path(transcription_result["raw_musicxml_path"])
    raw_pdf_path = transcription_result.get("raw_pdf_path")
    if raw_pdf_path is not None:
        raw_pdf_path = Path(raw_pdf_path)
    quality_report = transcription_result.get("quality_report")
    candidate_summary_path = transcription_result.get("candidate_summary_path")
    if candidate_summary_path is not None:
        candidate_summary_path = Path(candidate_summary_path)
    formal_musicxml_path = transcription_result.get("formal_musicxml_path")
    if formal_musicxml_path is not None:
        formal_musicxml_path = Path(formal_musicxml_path)

    print("\n[5/7] 正在把原始 MIDI 轉成專案 SCORE...")
    notes = extract_midi_notes(midi_path)
    score = build_project_score(notes)
    print("[5/7] 正在建立精準 ESP32 時間軸控制檔...")
    esp32_lines = build_esp32_playback_lines(notes)
    project_musicxml_path = score_to_project_musicxml(score, song_name, output_dir)
    if formal_musicxml_path is None:
        formal_musicxml_path = polish_with_midi2scoretransformer(midi_path, song_name, output_dir)
    pdf_source_path = formal_musicxml_path or project_musicxml_path
    pdf_path = export_pdf(pdf_source_path, song_name, output_dir) if export_pdf_enabled else None
    score_path, esp32_txt_path = save_score_files(song_name, score, output_dir, esp32_lines)
    validation_confidence = str((quality_report or {}).get("transcription_validation", {}).get("confidence", "unknown"))
    if validation_confidence == "low":
        print("\n提醒：這次轉譜和原音的自動比對信心偏低，建議改用來源覆寫或重新指定影片。")
    elif validation_confidence == "medium":
        print("\n提醒：這次轉譜的自動比對信心中等，若是你很在意細節，建議檢查來源影片是否正確。")

    print_summary(
        song_name=song_name,
        output_dir=output_dir,
        source_info=source_info,
        provider_name=provider_name,
        audio_path=audio_path,
        midi_path=midi_path,
        raw_musicxml_path=raw_musicxml_path,
        raw_pdf_path=raw_pdf_path,
        project_musicxml_path=project_musicxml_path,
        formal_musicxml_path=formal_musicxml_path,
        pdf_path=pdf_path,
        score_path=score_path,
        esp32_txt_path=esp32_txt_path,
        quality_report=quality_report,
        candidate_summary_path=candidate_summary_path,
    )

    result = build_process_result(
        song_name=song_name,
        output_dir=output_dir,
        source_info=source_info,
        provider_name=provider_name,
        score_path=score_path,
        esp32_txt_path=esp32_txt_path,
    )

    if play_after_export:
        from play_score import play_score

        print("\n正在傳送樂譜到 ESP32...")
        play_score(score, com_port=com_port, overlap=max(1, overlap))

    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="輸入歌曲名稱後，先自動搜尋影片並下載音訊，再用本地鋼琴模型轉譜，最後輸出專案格式。"
    )
    parser.add_argument("song_name", nargs="*", help="歌曲名稱或影片連結")
    parser.add_argument(
        "--mode",
        choices=[TRANSCRIBE_MODE_QUICK, TRANSCRIBE_MODE_FULL, TRANSCRIBE_MODE_AUTO],
        default=TRANSCRIBE_MODE_FULL,
        help="auto = 自動比較 Transkun 與 ByteDance 後選最佳，quick = Transkun，full = ByteDance。",
    )
    parser.add_argument(
        "--search-suffix",
        default=DEFAULT_SEARCH_SUFFIX,
        help="當不是影片連結時，附加的搜尋關鍵字。",
    )
    parser.add_argument(
        "--no-pdf",
        action="store_true",
        help="即使有免費排版軟體也略過列印檔匯出。",
    )
    parser.add_argument("--play", action="store_true", help="匯出後立刻把 SCORE 傳給 ESP32。")
    parser.add_argument("--com", help="啟用 --play 時指定 ESP32 COM 埠；未提供時自動匹配。")
    parser.add_argument("--overlap", type=int, default=3, help="啟用 --play 時的管線重疊數。")
    parser.add_argument("--cpu", action="store_true", help="強制本地模型改用 CPU。")
    parser.add_argument("--summary-json", help="將本次轉譜結果摘要寫到指定 JSON 檔。")
    return parser


def main() -> int:
    clear_problematic_env()
    configure_utf8_console()

    parser = build_parser()
    args = parser.parse_args()
    banner()

    try:
        require_supported_python()
        require_python_module("yt_dlp", "yt-dlp")
        require_python_module("pretty_midi", "pretty_midi")
        require_python_module("music21", "music21")
        require_python_module("requests", "requests")
        require_python_module("imageio_ffmpeg", "imageio-ffmpeg")
        require_python_module("torch", "torch")
        runtime_config = load_model_runtime_config()
        if args.mode in {TRANSCRIBE_MODE_QUICK, TRANSCRIBE_MODE_AUTO}:
            find_transkun_command(runtime_config)
        if args.mode in {TRANSCRIBE_MODE_FULL, TRANSCRIBE_MODE_AUTO}:
            require_python_module("piano_transcription_inference", "piano_transcription_inference")
            resolve_bytedance_checkpoint_path(runtime_config)
        if args.mode in {TRANSCRIBE_MODE_QUICK, TRANSCRIBE_MODE_FULL, TRANSCRIBE_MODE_AUTO}:
            # Basic Pitch is still used for automatic validation of candidate outputs.
            require_python_module("basic_pitch", "basic-pitch")
    except RuntimeError as exc:
        print(f"\n錯誤：{exc}")
        return 1

    if args.song_name:
        song_name = " ".join(args.song_name).strip()
    else:
        song_name = input("請輸入歌曲名稱或影片連結：").strip()

    if not song_name:
        print("尚未輸入歌曲名稱。")
        return 1

    if args.cpu:
        os.environ["AUTO_SCORE_FORCE_DEVICE"] = "cpu"

    try:
        result = process_song(
            song_name=song_name,
            transcribe_mode=args.mode,
            search_suffix=args.search_suffix,
            export_pdf_enabled=not args.no_pdf,
            play_after_export=args.play,
            com_port=args.com,
            overlap=args.overlap,
        )
        if args.summary_json:
            summary_path = Path(args.summary_json)
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return 0
    except RuntimeError as exc:
        print(f"\n錯誤：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
