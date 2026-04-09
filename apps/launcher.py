from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
APPS_DIR = BASE_DIR / "apps"
VENV_DIR = BASE_DIR / ".venv311"
VENV_PYTHON = VENV_DIR / "Scripts" / "python.exe"
PLAYBACK_DIR = BASE_DIR / "playback"
VISUALIZER_APP = APPS_DIR / "visualize_score.py"
INSTALL_BAT = BASE_DIR / "install.bat"
DEFAULT_TRANSCRIPTION_MODE = "full"


def zh(text: str) -> str:
    return text.encode("ascii").decode("unicode_escape")


def configure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", line_buffering=True)
        except Exception:
            pass


def install_hint() -> str:
    return zh("\\u5c1a\\u672a\\u5b89\\u88dd\\u5c08\\u6848\\u4f9d\\u8cf4\\uff0c\\u8acb\\u5148\\u57f7\\u884c ") + INSTALL_BAT.name


def require_installed_runtime() -> None:
    if not VENV_PYTHON.exists():
        raise RuntimeError(install_hint())


def require_modules(module_specs: dict[str, str]) -> None:
    missing_packages = [package for module_name, package in module_specs.items() if importlib.util.find_spec(module_name) is None]
    if missing_packages:
        raise RuntimeError(
            zh("\\u7f3a\\u5c11\\u57f7\\u884c\\u6240\\u9700\\u5957\\u4ef6\\uff1a")
            + ", ".join(missing_packages)
            + "。"
            + install_hint()
        )


def choose_mode() -> str:
    print(zh("\\u8acb\\u9078\\u64c7\\u8981\\u505a\\u7684\\u4e8b\\u60c5\\uff1a"))
    print(zh("  [1] \\u64ad\\u653e\\u5df2\\u6709\\u6b4c\\u66f2"))
    print(zh("  [2] \\u67e5\\u6b4c\\u4e26\\u81ea\\u52d5\\u8f49\\u8b5c"))
    print(zh("  [3] \\u96e2\\u958b"))
    while True:
        choice = input(zh("\\u8acb\\u8f38\\u5165 1 / 2 / 3\\uff1a")).strip()
        if choice in {"1", "2", "3"}:
            return choice
        print(zh("\\u8f38\\u5165\\u7121\\u6548\\uff0c\\u8acb\\u91cd\\u65b0\\u8f38\\u5165\\u3002"))


def prompt_song_name() -> str:
    while True:
        song_name = input(zh("\\u8acb\\u8f38\\u5165\\u6b4c\\u66f2\\u540d\\u7a31\\u6216\\u5f71\\u7247\\u9023\\u7d50\\uff1a")).strip()
        if song_name:
            return song_name
        print(zh("\\u6b4c\\u66f2\\u540d\\u7a31\\u4e0d\\u80fd\\u7a7a\\u767d\\uff0c\\u8acb\\u91cd\\u65b0\\u8f38\\u5165\\u3002"))


def wait_for_exit(message: str) -> None:
    try:
        input(message)
    except EOFError:
        pass


def create_temp_summary_path() -> Path:
    fd, raw_path = tempfile.mkstemp(prefix="auto-piano-summary-", suffix=".json")
    os.close(fd)
    return Path(raw_path)


def load_transcription_summary(summary_path: Path) -> dict[str, str]:
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(zh("\\u7121\\u6cd5\\u8b80\\u53d6\\u8f49\\u8b5c\\u7d50\\u679c\\u6458\\u8981\\uff1a") + str(exc)) from exc

    if not isinstance(payload, dict):
        raise RuntimeError(zh("\\u8f49\\u8b5c\\u7d50\\u679c\\u6458\\u8981\\u683c\\u5f0f\\u932f\\u8aa4\\u3002"))

    score_value = str(payload.get("score_path", "") or "").strip()
    if not score_value:
        raise RuntimeError(zh("\\u8f49\\u8b5c\\u5b8c\\u6210\\uff0c\\u4f46\\u7f3a\\u5c11\\u6a02\\u8b5c\\u8def\\u5f91\\u3002"))

    score_path = Path(score_value)
    if not score_path.is_file():
        raise RuntimeError(zh("\\u8f49\\u8b5c\\u5b8c\\u6210\\uff0c\\u4f46\\u627e\\u4e0d\\u5230\\u7522\\u751f\\u7684\\u6a02\\u8b5c\\u6a94\\u3002"))

    payload["score_path"] = str(score_path)
    return payload


def prompt_post_transcription_action(song_name: str) -> str:
    print(zh("\\u8f49\\u8b5c\\u5b8c\\u6210\\uff1a") + song_name)
    print(zh("\\u8acb\\u9078\\u64c7\\u63a5\\u4e0b\\u4f86\\u8981\\u505a\\u7684\\u4e8b\\u60c5\\uff1a"))
    print(zh("  [1] \\u76f4\\u63a5\\u6a21\\u64ec\\u64ad\\u653e"))
    print(zh("  [2] \\u76f4\\u63a5\\u771f\\u5be6\\u5f48\\u594f"))
    print(zh("  [3] \\u96e2\\u958b"))
    while True:
        choice = input(zh("\\u8acb\\u8f38\\u5165 1 / 2 / 3\\uff1a")).strip()
        if choice in {"1", "2", "3"}:
            return choice
        print(zh("\\u8f38\\u5165\\u7121\\u6548\\uff0c\\u8acb\\u91cd\\u65b0\\u8f38\\u5165\\u3002"))


def run_visualizer(score_path: Path) -> int:
    require_installed_runtime()
    require_modules({"pygame": "pygame"})
    print()
    return subprocess.call([str(VENV_PYTHON), str(VISUALIZER_APP), str(score_path)], cwd=BASE_DIR)


def run_hardware_playback(score_path: Path) -> int:
    require_installed_runtime()
    require_modules({"serial": "pyserial"})
    print()
    return subprocess.call(
        [str(VENV_PYTHON), str(PLAYBACK_DIR / "play_score.py"), "--file", str(score_path)],
        cwd=BASE_DIR,
    )


def run_play_mode() -> int:
    require_installed_runtime()
    require_modules({"serial": "pyserial"})
    print()
    return subprocess.call([str(VENV_PYTHON), str(PLAYBACK_DIR / "play_score.py")], cwd=BASE_DIR)


def run_search_mode() -> int:
    require_installed_runtime()
    require_modules(
        {
            "yt_dlp": "yt-dlp",
            "pretty_midi": "pretty_midi",
            "music21": "music21",
            "requests": "requests",
            "imageio_ffmpeg": "imageio-ffmpeg",
            "torch": "torch",
            "piano_transcription_inference": "piano_transcription_inference",
            "basic_pitch": "basic-pitch",
            "pydub": "pydub",
            "moduleconf": "moduleconf",
        }
    )
    song_name = prompt_song_name()
    provider_mode = DEFAULT_TRANSCRIPTION_MODE
    print(zh("\\u8f49\\u8b5c\\u6a21\\u5f0f\\uff1a\\u5df2\\u9810\\u8a2d\\u70ba\\u300cByteDance CUDA\\u300d\\u3002"))
    summary_path = create_temp_summary_path()
    print()
    try:
        exit_code = subprocess.call(
            [
                str(VENV_PYTHON),
                str(PLAYBACK_DIR / "song_workflow.py"),
                "--mode",
                provider_mode,
                "--summary-json",
                str(summary_path),
                song_name,
            ],
            cwd=BASE_DIR,
        )
        if exit_code != 0:
            return exit_code

        summary = load_transcription_summary(summary_path)
        score_path = Path(str(summary["score_path"]))
        print()
        action = prompt_post_transcription_action(str(summary.get("song_name", song_name) or song_name))
        if action == "1":
            exit_code = run_visualizer(score_path)
            if exit_code == 0:
                print()
                wait_for_exit(zh("\\u6a21\\u64ec\\u64ad\\u653e\\u5b8c\\u6210\\uff0c\\u8acb\\u6309 Enter \\u7d50\\u675f..."))
            return exit_code
        if action == "2":
            exit_code = run_hardware_playback(score_path)
            if exit_code == 0:
                print()
                wait_for_exit(zh("\\u771f\\u5be6\\u5f48\\u594f\\u5b8c\\u6210\\uff0c\\u8acb\\u6309 Enter \\u7d50\\u675f..."))
            return exit_code
        print(zh("\\u5df2\\u96e2\\u958b\\u3002"))
        return 0
    finally:
        try:
            summary_path.unlink(missing_ok=True)
        except Exception:
            pass


def main() -> int:
    configure_utf8_console()
    try:
        choice = choose_mode()
        if choice == "1":
            return run_play_mode()
        if choice == "2":
            return run_search_mode()
        print(zh("\\u5df2\\u96e2\\u958b\\u3002"))
        return 0
    except KeyboardInterrupt:
        print("\n" + zh("\\u5df2\\u53d6\\u6d88\\u3002"))
        return 1
    except Exception as exc:
        print("\n" + zh("\\u932f\\u8aa4\\uff1a") + str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
