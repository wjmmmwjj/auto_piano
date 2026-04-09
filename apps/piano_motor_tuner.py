from __future__ import annotations

import re
import shutil
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import serial
except ImportError:
    print("缺少套件 pyserial，請先執行 install.bat。")
    raise SystemExit(1)

from playback.esp32_serial import Esp32PortProbe, classify_banner_lines, find_best_esp32_port, ping_for_ready
MAIN_INO_PATH = PROJECT_ROOT / "esp32" / "motor_control" / "motor_control.ino"
TOOL_INO_PATH = PROJECT_ROOT / "esp32" / "motor_control_tool" / "motor_control_tool.ino"

MIN_MIDI = 21
MAX_MIDI = 108
MIN_ANGLE = 0
MAX_ANGLE = 180
SERIAL_BAUD = 115200
SERIAL_TIMEOUT_SEC = 0.2
READY_TIMEOUT_SEC = 4.0
COMMAND_TIMEOUT_SEC = 2.5
SUPPORTED_TOOL_BANNERS = ("TUNER_READY",)
MAIN_FIRMWARE_BANNERS = ("READY - 88 Keys", "READY")
TABLE_PATTERN = re.compile(r"((?:const\s+)?int\s+N\[\]\[7\]\s*=\s*\{)([\s\S]*?)(\n\};)")
ROW_PATTERN = re.compile(r"\{\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\}\s*,?")


def configure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", line_buffering=True)
        except Exception:
            pass
def describe_probe_status(probe: Esp32PortProbe) -> str:
    if probe.mode == "tuner":
        return "ESP32 調校韌體"
    if probe.mode == "main":
        return "ESP32 正式播放韌體"
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


def print_port_choices(default_port: str | None, probes: list[Esp32PortProbe]) -> None:
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
        print("目前沒有自動偵測到序列埠。")


def prompt_for_port(default_port: str | None, probes: list[Esp32PortProbe]) -> str | None:
    print_port_choices(default_port, probes)
    available = selectable_probes(probes)

    while True:
        if default_port:
            raw = input(f"ESP32 的 COM 埠 [直接 Enter 使用 {default_port}]：").strip()
        else:
            raw = input("ESP32 的 COM 埠 [請輸入編號或 COM 埠，不會自動猜測]：").strip()
        if not raw:
            if default_port:
                return default_port
            print("目前沒有已確認的調校韌體埠，請手動選擇。")
            continue

        if raw.isdigit() and available:
            index = int(raw)
            if 1 <= index <= len(available):
                return available[index - 1].port
            print("序號超出範圍。")
            continue

        return raw.upper()


def read_serial_lines(ser: serial.Serial, duration_sec: float) -> list[str]:
    deadline = time.time() + duration_sec
    lines: list[str] = []

    while time.time() < deadline:
        raw = ser.readline()
        if not raw:
            time.sleep(0.05)
            continue
        line = raw.decode("utf-8", errors="ignore").strip()
        if line:
            lines.append(line)

    return lines


def detect_firmware_mode(ser: serial.Serial) -> tuple[str, list[str]]:
    try:
        ser.reset_input_buffer()
    except Exception:
        pass

    banners = read_serial_lines(ser, READY_TIMEOUT_SEC)
    mode = classify_banner_lines(banners)
    if mode == "unknown":
        ping_lines = ping_for_ready(ser)
        if ping_lines:
            banners.extend(ping_lines)
            mode = classify_banner_lines(banners)
    return mode, banners


def send_command(ser: serial.Serial, command: str, timeout_sec: float = COMMAND_TIMEOUT_SEC) -> tuple[bool, list[str]]:
    try:
        ser.reset_input_buffer()
    except Exception:
        pass

    ser.write((command.strip() + "\n").encode("ascii"))
    ser.flush()

    deadline = time.time() + timeout_sec
    lines: list[str] = []
    while time.time() < deadline:
        raw = ser.readline()
        if not raw:
            time.sleep(0.05)
            continue
        line = raw.decode("utf-8", errors="ignore").strip()
        if not line:
            continue
        lines.append(line)
        if line == "OK":
            return True, lines
        if line.startswith("ERR"):
            return False, lines

    return False, lines


def validate_pitch(pitch: int) -> bool:
    return MIN_MIDI <= pitch <= MAX_MIDI


def validate_angle(angle: int) -> bool:
    return MIN_ANGLE <= angle <= MAX_ANGLE


def parse_motor_table(content: str) -> tuple[re.Match[str] | None, list[dict[str, int]]]:
    match = TABLE_PATTERN.search(content)
    if not match:
        return None, []

    entries: list[dict[str, int]] = []
    for row_match in ROW_PATTERN.finditer(match.group(2)):
        entries.append(
            {
                "midi": int(row_match.group(1)),
                "board": int(row_match.group(2)),
                "channel": int(row_match.group(3)),
                "p0": int(row_match.group(4)),
                "p180": int(row_match.group(5)),
                "press": int(row_match.group(6)),
                "release": int(row_match.group(7)),
            }
        )
    return match, entries


def load_reference_entry(midi_pitch: int) -> dict[str, int] | None:
    for candidate in (MAIN_INO_PATH.with_suffix(MAIN_INO_PATH.suffix + ".bak"), TOOL_INO_PATH):
        if not candidate.exists():
            continue

        _, entries = parse_motor_table(candidate.read_text(encoding="utf-8", errors="replace"))
        target = next((entry for entry in entries if entry["midi"] == midi_pitch), None)
        if target is not None:
            return dict(target)

    return None


def rebuild_motor_table(content: str, entries: list[dict[str, int]]) -> str:
    body_lines = [
        "  "
        + "{"
        + f"{entry['midi']}, {entry['board']}, {entry['channel']}, {entry['p0']}, {entry['p180']}, {entry['press']}, {entry['release']}"
        + "},"
        for entry in sorted(entries, key=lambda item: item["midi"])
    ]
    body = "\n" + "\n".join(body_lines) + "\n"
    return TABLE_PATTERN.sub(r"\1" + body + r"\3", content, count=1)


def update_ino_angles(midi_pitch: int, press_angle: int, release_angle: int) -> tuple[bool, str]:
    if not MAIN_INO_PATH.exists():
        return False, f"找不到正式韌體檔案：{MAIN_INO_PATH}"

    content = MAIN_INO_PATH.read_text(encoding="utf-8", errors="replace")
    match, entries = parse_motor_table(content)
    if match is None:
        return False, "在 motor_control.ino 中找不到 N[][7] 角度表。"

    target = next((entry for entry in entries if entry["midi"] == midi_pitch), None)
    recovered_missing_entry = False
    if target is None:
        reference_entry = load_reference_entry(midi_pitch)
        if reference_entry is None:
            return False, f"在 motor_control.ino 中找不到 MIDI {midi_pitch}，而且備份表裡也沒有。"
        entries.append(reference_entry)
        target = reference_entry
        recovered_missing_entry = True

    old_press = target["press"]
    old_release = target["release"]
    target["press"] = press_angle
    target["release"] = release_angle

    updated_content = rebuild_motor_table(content, entries)
    if updated_content == content and old_press == press_angle and old_release == release_angle:
        return True, f"MIDI {midi_pitch} 已經是回位角度={release_angle}，按下角度={press_angle}。"

    backup_path = MAIN_INO_PATH.with_suffix(MAIN_INO_PATH.suffix + ".bak")
    shutil.copy2(MAIN_INO_PATH, backup_path)
    MAIN_INO_PATH.write_text(updated_content, encoding="utf-8")

    if recovered_missing_entry:
        return (
            True,
            f"已補回缺少的 MIDI {midi_pitch}，並更新為回位角度={release_angle}，按下角度={press_angle}。備份檔：{backup_path.name}",
        )

    return (
        True,
        f"已更新 MIDI {midi_pitch}：回位角度={release_angle}，按下角度={press_angle}。備份檔：{backup_path.name}",
    )


def print_help() -> None:
    print("指令說明：")
    print("  <midi> <angle>")
    print("    範例：60 30")
    print("    直接送出單顆伺服的角度測試命令。")
    print("  <midi> <release_angle> <press_angle>")
    print("    範例：60 0 30")
    print("    執行擊鍵測試，並把角度寫回 motor_control.ino。")
    print("  help")
    print("    顯示這份說明。")
    print("  q")
    print("    離開工具。")


def main() -> int:
    configure_utf8_console()

    print("=== 鋼琴馬達調校工具 ===")
    print(f"請先燒錄這份韌體：{TOOL_INO_PATH.relative_to(PROJECT_ROOT).as_posix()}")
    print("這個工具支援兩種輸入模式：")
    print("  1. `<midi> <angle>`")
    print("     直接把單顆伺服轉到指定角度。")
    print("  2. `<midi> <release_angle> <press_angle>`")
    print("     執行擊鍵測試，並把角度寫回 motor_control.ino。")
    print("輸入 `help` 可看範例，輸入 `q` 可離開。")
    print()

    selected_probe, probes = find_best_esp32_port(expected_mode="tuner")
    if selected_probe is not None:
        default_port = selected_probe.port
        print_port_choices(default_port, probes)
        description = selected_probe.description or "無描述"
        print(f"已自動匹配調校用 ESP32：{selected_probe.port} - {description}")
        port = selected_probe.port
    else:
        main_probe = next((probe for probe in probes if probe.mode == "main"), None)
        likely_candidates = selectable_likely_esp32_probes(probes)
        unknown_esp32_probe = next((probe for probe in likely_candidates if probe.mode == "unknown"), None)
        if main_probe is not None:
            print("警告：有偵測到 ESP32，但它目前回應的是正式播放韌體，不是調校韌體。")
            print("因為沒有看到 TUNER_READY，所以這次不會自動替你選擇 COM 埠。")
        elif len(likely_candidates) == 1:
            only_candidate = likely_candidates[0]
            print_port_choices(None, probes)
            print(f"已直接連線唯一可用的疑似 ESP32：{only_candidate.port} - {only_candidate.description or '無描述'}")
            port = only_candidate.port
        elif unknown_esp32_probe is not None:
            print("警告：目前只有疑似 ESP32 的序列埠，但沒有看到 TUNER_READY。")
            print("因為沒有明確證據，所以這次不會自動替你選擇 COM 埠。")

        if 'port' not in locals():
            try:
                port = prompt_for_port(None, probes)
            except EOFError:
                print("\n尚未選擇 COM 埠就結束輸入。")
                return 1

            if not port:
                print("沒有選擇 COM 埠。")
                return 1

    print(f"正在連線到 {port}...")
    try:
        ser = serial.Serial(port, SERIAL_BAUD, timeout=SERIAL_TIMEOUT_SEC)
    except Exception as exc:
        print(f"無法開啟序列埠 {port}：{exc}")
        return 1

    try:
        time.sleep(2.0)
        mode, banners = detect_firmware_mode(ser)

        if banners:
            print("ESP32 回應：")
            for line in banners:
                print(f"  {line}")

        if mode == "main":
            print()
            print("警告：目前 ESP32 看起來跑的是正式播放韌體，不是調校韌體。")
            print(f"請先燒錄 {TOOL_INO_PATH.relative_to(PROJECT_ROOT).as_posix()}，再重新執行 tool.bat。")
            return 1

        if mode == "unknown":
            print()
            print("警告：沒有偵測到調校韌體的啟動訊息。若燒錯韌體，命令可能會失敗。")
            print(f"預期的啟動訊息：{SUPPORTED_TOOL_BANNERS[0]}")

        print()
        print_help()
        print()

        while True:
            try:
                raw = input("請輸入指令：").strip()
            except EOFError:
                print("\n輸入已結束，正在離開工具。")
                return 1

            if not raw:
                continue

            lowered = raw.lower()
            if lowered in {"q", "quit", "exit"}:
                break
            if lowered in {"help", "h", "?"}:
                print_help()
                continue

            parts = raw.split()

            if len(parts) == 2:
                try:
                    pitch, angle = map(int, parts)
                except ValueError:
                    print("格式錯誤，請使用：<midi> <angle>")
                    continue

                if not validate_pitch(pitch):
                    print(f"MIDI 音高必須介於 {MIN_MIDI} 到 {MAX_MIDI}。")
                    continue
                if not validate_angle(angle):
                    print(f"角度必須介於 {MIN_ANGLE} 到 {MAX_ANGLE}。")
                    continue

                ok, responses = send_command(ser, f"S,{pitch},{angle}")
                if responses:
                    print("ESP32 回覆：" + " | ".join(responses))
                else:
                    print("ESP32 沒有回覆。")
                if ok:
                    print(f"已把 MIDI {pitch} 移動到角度 {angle}。")
                else:
                    print("單顆角度測試沒有成功完成。")
                continue

            if len(parts) == 3:
                try:
                    pitch, release_angle, press_angle = map(int, parts)
                except ValueError:
                    print("格式錯誤，請使用：<midi> <release_angle> <press_angle>")
                    continue

                if not validate_pitch(pitch):
                    print(f"MIDI 音高必須介於 {MIN_MIDI} 到 {MAX_MIDI}。")
                    continue
                if not validate_angle(release_angle) or not validate_angle(press_angle):
                    print(f"角度必須介於 {MIN_ANGLE} 到 {MAX_ANGLE}。")
                    continue

                ok, responses = send_command(ser, f"H,{pitch},{release_angle},{press_angle}")
                if responses:
                    print("ESP32 回覆：" + " | ".join(responses))
                else:
                    print("ESP32 沒有回覆。")

                if not ok:
                    print("擊鍵測試沒有成功完成，所以不會修改 motor_control.ino。")
                    continue

                saved, message = update_ino_angles(pitch, press_angle, release_angle)
                print(message)
                if not saved:
                    print("馬達可能有動作，但角度表沒有更新。")
                continue

            print("不支援的指令格式。")
            print("請使用 `<midi> <angle>` 或 `<midi> <release_angle> <press_angle>`。")
    except KeyboardInterrupt:
        print("\n已由使用者取消。")
        return 1
    finally:
        ser.close()
        print("已關閉序列埠。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
