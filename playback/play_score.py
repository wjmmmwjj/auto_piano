from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
import time

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import serial

try:
    from .project_score_tools import normalize_score, score_to_esp32_lines
    from .esp32_serial import Esp32PortProbe, find_best_esp32_port
except ImportError:
    from project_score_tools import normalize_score, score_to_esp32_lines
    from esp32_serial import Esp32PortProbe, find_best_esp32_port

SONGS_DIR = BASE_DIR / "songs"
SAFE_ZERO_DELAY_MS = 40
SAFE_ZERO_TIMEOUT_SEC = 30.0


def configure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def safe_filename(value: str) -> str:
    illegal = "\\/:*?\"<>|"
    cleaned = "".join("_" if ch in illegal else ch for ch in value).strip().strip(".")
    return cleaned or "untitled"


def list_available_score_entries() -> list[tuple[str, Path]]:
    entries: list[tuple[str, Path]] = []
    seen: set[Path] = set()

    if SONGS_DIR.exists():
        for path in sorted(SONGS_DIR.glob("*.py"), key=lambda item: item.stem.lower()):
            resolved = path.resolve()
            if resolved in seen:
                continue
            entries.append((path.stem, resolved))
            seen.add(resolved)

    return entries


def prompt_for_score_path() -> Path:
    entries = list_available_score_entries()
    print("可播放的樂譜：")
    for index, (label, path) in enumerate(entries, start=1):
        print(f"  {index}. {label}  [{path.name}]")

    if not entries:
        print("目前找不到已存樂譜，請直接輸入檔案路徑。")

    print("也可以直接輸入歌曲名稱或檔案路徑。")
    while True:
        raw = input("請選擇要播放的樂譜：").strip()
        if not raw:
            if len(entries) == 1:
                return entries[0][1]
            print("沒有預設樂譜，請輸入編號、歌曲名稱或檔案路徑。")
            continue

        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(entries):
                return entries[index - 1][1]
            print("編號不在範圍內，請重新輸入。")
            continue

        direct = Path(raw)
        if direct.suffix.lower() == ".py":
            candidate = direct if direct.is_absolute() else (BASE_DIR / direct)
            if candidate.exists():
                return candidate.resolve()

        candidate = SONGS_DIR / f"{safe_filename(raw)}.py"
        if candidate.exists():
            return candidate.resolve()

        if direct.exists():
            return direct.resolve()

        print("找不到對應的樂譜，請再試一次。")


def resolve_score_path(song_name: str | None, explicit_file: str | None) -> Path:
    if explicit_file:
        path = Path(explicit_file)
        if not path.is_absolute():
            path = (BASE_DIR / path).resolve()
        return path

    if song_name:
        direct = Path(song_name)
        if direct.suffix == ".py" and direct.exists():
            return direct.resolve()

        safe_name = safe_filename(song_name)
        candidate = SONGS_DIR / f"{safe_name}.py"
        if candidate.exists():
            return candidate

        raise FileNotFoundError(f"找不到對應的樂譜：{song_name}")

    raise FileNotFoundError("尚未指定要播放的樂譜。")


def load_song_data(score_path: Path) -> tuple[list[tuple] | None, list[str] | None]:
    if not score_path.exists():
        raise FileNotFoundError(f"找不到樂譜檔：{score_path}")

    module_name = f"score_{int(time.time() * 1000)}"
    spec = importlib.util.spec_from_file_location(module_name, score_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"無法載入樂譜檔：{score_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    score = getattr(module, "SCORE", None)
    if score is not None and not isinstance(score, list):
        raise RuntimeError(f"{score_path} 的 SCORE 格式無效。")

    embedded_lines = getattr(module, "ESP32_LINES", None)
    if embedded_lines is not None:
        if not isinstance(embedded_lines, list):
            raise RuntimeError(f"{score_path} 的 ESP32_LINES 格式無效。")
        normalized_lines = [str(line).strip() for line in embedded_lines if str(line).strip()]
        embedded_lines = normalized_lines or None

    if not isinstance(score, list) and embedded_lines is None:
        raise RuntimeError(f"{score_path} 沒有定義可播放的 SCORE 或 ESP32_LINES。")

    return (score if isinstance(score, list) else None), embedded_lines


def load_commands_file(command_path: Path) -> list[str]:
    if not command_path.exists():
        raise FileNotFoundError(f"找不到指令檔：{command_path}")

    commands: list[str] = []
    for raw_line in command_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        commands.append(line)

    return commands


def find_companion_commands_file(score_path: Path) -> Path | None:
    outputs_dir = BASE_DIR / "playback" / "outputs"
    if not outputs_dir.exists():
        return None

    safe_name = safe_filename(score_path.stem)
    candidate = outputs_dir / safe_name / f"{safe_name}.esp32.txt"
    if candidate.exists():
        return candidate.resolve()
    return None


def describe_probe_status(probe: Esp32PortProbe) -> str:
    if probe.mode == "main":
        return "ESP32 播放韌體"
    if probe.mode == "tuner":
        return "ESP32 調校韌體"
    if probe.mode == "mega":
        return "Arduino Mega 按鈕板"
    if probe.error:
        return f"無法開啟：{probe.error}"
    if probe.likely_esp32:
        return "可能是 ESP32"
    return "未辨識"


def selectable_probes(probes: list[Esp32PortProbe]) -> list[Esp32PortProbe]:
    return [probe for probe in probes if probe.error is None]


def selectable_likely_esp32_probes(probes: list[Esp32PortProbe]) -> list[Esp32PortProbe]:
    return [probe for probe in probes if probe.error is None and probe.likely_esp32]


def print_com_probe_choices(probes: list[Esp32PortProbe], default_port: str | None) -> None:
    if probes:
        print("偵測到的序列埠：")
        available = selectable_probes(probes)
        unavailable = [probe for probe in probes if probe.error is not None]

        for index, probe in enumerate(available, start=1):
            suffix = "（預設）" if probe.port == default_port else ""
            description = probe.description or "無描述"
            print(f"  {index}. {probe.port} - {description} [{describe_probe_status(probe)}]{suffix}")

        if unavailable:
            print("  不可用：")
            for probe in unavailable:
                description = probe.description or "無描述"
                print(f"  - {probe.port} - {description} [{describe_probe_status(probe)}]")
    else:
        print("目前沒有偵測到序列埠，將使用手動輸入。")


def prompt_for_com_port(probes: list[Esp32PortProbe], default: str | None = None) -> str:
    print_com_probe_choices(probes, default)
    available = selectable_probes(probes)

    while True:
        if default:
            raw = input(f"請輸入 ESP32 的 COM 埠（直接 Enter 使用 {default}）：").strip()
        else:
            raw = input("請輸入 ESP32 的 COM 埠（請輸入編號或 COM 埠，不會自動猜測）：").strip()
        if not raw:
            if default:
                return default
            print("目前沒有已確認的播放韌體埠，請手動選擇。")
            continue
        if raw.isdigit() and available:
            index = int(raw)
            if 1 <= index <= len(available):
                return available[index - 1].port
            print("編號不在範圍內，請重新輸入。")
            continue
        return raw.upper()


def resolve_playback_com_port(com_port: str | None, *, interactive: bool) -> str:
    if com_port:
        return com_port.strip().upper()

    selected_probe, probes = find_best_esp32_port(expected_mode="main")
    if selected_probe is not None:
        description = selected_probe.description or "無描述"
        print(f"已自動匹配 ESP32 播放控制器：{selected_probe.port} - {description}")
        return selected_probe.port

    tuner_probe = next((probe for probe in probes if probe.mode == "tuner"), None)
    likely_candidates = selectable_likely_esp32_probes(probes)
    unknown_esp32_probe = next((probe for probe in likely_candidates if probe.mode == "unknown"), None)

    if tuner_probe is not None:
        description = tuner_probe.description or "無描述"
        print(f"警告：有找到 ESP32，但目前燒錄的是調校韌體：{tuner_probe.port} - {description}")
        print("將自動嘗試連線此埠。如需正式播放，請改燒 esp32/motor_control/motor_control.ino。")
        return tuner_probe.port

    if len(likely_candidates) == 1:
        only_candidate = likely_candidates[0]
        description = only_candidate.description or "無描述"
        print(f"已直接連線唯一可用的疑似 ESP32：{only_candidate.port} - {description}")
        if only_candidate.mode == "unknown":
            print("警告：目前還沒有看到正式播放韌體的 READY 訊息，會先直接嘗試連線。")
        return only_candidate.port

    if len(likely_candidates) > 1:
        first_candidate = likely_candidates[0]
        description = first_candidate.description or "無描述"
        print(f"偵測到多個疑似 ESP32 的序列埠，自動選擇第一個：{first_candidate.port} - {description}")
        if first_candidate.mode == "unknown":
            print("警告：目前還沒有看到正式播放韌體的 READY 訊息，會先直接嘗試連線。")
        return first_candidate.port

    # 最後嘗試：從所有可用埠中找任何一個可開啟的
    all_available = selectable_probes(probes)
    if len(all_available) == 1:
        only_port = all_available[0]
        description = only_port.description or "無描述"
        print(f"只偵測到一個可用序列埠，自動嘗試連線：{only_port.port} - {description}")
        return only_port.port

    if interactive and all_available:
        print("無法自動判斷哪個是 ESP32，請手動選擇：")
        return prompt_for_com_port(probes)

    raise RuntimeError("找不到可確認為 ESP32 播放韌體的裝置；不會猜測 COM 埠。請確認板子已連線並回應 READY，或用 --com 指定。")


def wait_for_ready(ser: serial.Serial, timeout_sec: float = 30.0) -> None:
    start = time.time()
    while time.time() - start < timeout_sec:
        ser.write(b"PING,0\n")
        time.sleep(0.5)
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if line == "TUNER_READY":
            raise RuntimeError("目前選到的是調校韌體，請改燒 esp32/motor_control/motor_control.ino 再播放。")
        if line.startswith("READY - Arduino Mega"):
            raise RuntimeError("目前選到的是 Arduino Mega 按鈕板，不是 ESP32 播放控制器。")
        if "READY" in line:
            return
    raise TimeoutError("ESP32 沒有在時間內回應就緒訊號。")


def send_safe_zero(ser: serial.Serial, delay_ms: int = SAFE_ZERO_DELAY_MS, timeout_sec: float = SAFE_ZERO_TIMEOUT_SEC) -> None:
    print(f"播放前先讓全部琴鍵慢慢歸零（每鍵 {delay_ms} ms）...")
    try:
        ser.reset_input_buffer()
    except Exception:
        pass

    ser.write(f"SAFEZERO,{max(5, delay_ms)}\n".encode("utf-8"))
    start = time.time()
    while time.time() - start < timeout_sec:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if not line:
            time.sleep(0.1)
            continue
        if line.startswith("INFO:") or line.startswith("WARN:"):
            print(f"ESP32 {line}")
            continue
        if line == "OK":
            time.sleep(0.3)
            return
        if line.startswith("ERR:"):
            raise RuntimeError(f"ESP32 安全歸零失敗：{line}")
    raise TimeoutError("ESP32 沒有在時間內完成安全歸零。")


def send_commands(commands: list[str], com_port: str | None, overlap: int) -> None:
    if not commands:
        raise RuntimeError("沒有可傳送的 ESP32 指令。")

    resolved_port = resolve_playback_com_port(com_port, interactive=False)

    print(f"正在連線到 ESP32（{resolved_port}）...")
    ser = serial.Serial(resolved_port, 115200, timeout=0.1)
    try:
        wait_for_ready(ser)
        send_safe_zero(ser)
        print("ESP32 已就緒，開始傳送樂譜...")

        total = len(commands)
        sent = 0
        confirmed = 0

        while confirmed < total:
            while (sent - confirmed) < overlap and sent < total:
                ser.write(f"{commands[sent]}\n".encode("utf-8"))
                sent += 1

            resp = ser.readline().decode("utf-8", errors="ignore").strip()
            if resp.startswith("INFO:") or resp.startswith("WARN:"):
                print(f"\nESP32 {resp}")
                continue
            if resp.startswith("ERR:"):
                raise RuntimeError(f"ESP32 播放失敗：{resp}")
            if "OK" in resp:
                confirmed += 1
                progress = int((confirmed / total) * 20)
                bar = "#" * progress + "." * (20 - progress)
                print(f"\r[{bar}] {confirmed}/{total}", end="", flush=True)

        print("\n播放完成。")
    finally:
        ser.close()


def play_score(score: list[tuple], com_port: str | None, overlap: int, esp32_lines: list[str] | None = None) -> None:
    commands = esp32_lines if esp32_lines else score_to_esp32_lines(normalize_score(score))
    send_commands(commands, com_port=com_port, overlap=overlap)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="將樂譜傳送到 ESP32 控制器。")
    parser.add_argument("song_name", nargs="?", help="songs/<名稱>.py 的歌曲名稱")
    parser.add_argument("--file", help="含有樂譜清單的 .py 檔路徑。")
    parser.add_argument("--com", help="ESP32 COM 埠；未指定時會自動匹配。")
    parser.add_argument("--overlap", type=int, default=3, help="管線重疊數（預設：3）")
    parser.add_argument("--safezero", action="store_true", help="只執行全部按鍵歸零，不播放樂譜")
    return parser


def main() -> int:
    configure_utf8_console()
    parser = build_parser()
    args = parser.parse_args()

    try:
        selected_com = resolve_playback_com_port(args.com, interactive=True)
        if args.safezero:
            print("執行全部按鍵歸零...")
            ser = serial.Serial(selected_com, baudrate=115200, timeout=0.2)
            try:
                wait_for_ready(ser)
                send_safe_zero(ser, 40)
                print("歸零完成。")
            finally:
                ser.close()
            return 0

        if args.song_name or args.file:
            path = resolve_score_path(args.song_name, args.file)
        else:
            path = prompt_for_score_path()

        if path.suffix.lower() == ".txt":
            commands = load_commands_file(path)
            print(f"使用指令檔：{path}")
            send_commands(commands, com_port=selected_com, overlap=max(1, args.overlap))
        else:
            score, embedded_lines = load_song_data(path)
            print(f"使用樂譜：{path}")
            if embedded_lines:
                print("已載入內嵌的精準 ESP32 時間軸指令。")
                play_score(score or [], com_port=selected_com, overlap=max(1, args.overlap), esp32_lines=embedded_lines)
            else:
                companion_commands = find_companion_commands_file(path)
                if companion_commands:
                    print(f"已找到對應的 ESP32 控制檔：{companion_commands}")
                    send_commands(load_commands_file(companion_commands), com_port=selected_com, overlap=max(1, args.overlap))
                elif score is not None:
                    print("目前使用舊版 SCORE 轉換播放模式。")
                    play_score(score, com_port=selected_com, overlap=max(1, args.overlap))
                else:
                    raise RuntimeError("這份樂譜沒有可用的播放資料。")
        return 0
    except KeyboardInterrupt:
        print("\n已由使用者取消。")
        return 1
    except Exception as exc:
        print(f"\n錯誤：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
