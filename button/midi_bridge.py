from __future__ import annotations

import argparse
import math
import os
import re
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
warnings.filterwarnings("ignore", message="pkg_resources is deprecated as an API.*")

import numpy as np
import pygame
import pygame.midi
import pygame.sndarray
import serial
import serial.tools.list_ports


SERIAL_BAUD = 115200
SERIAL_TIMEOUT_SEC = 0.2
PROBE_STARTUP_WAIT_SEC = 0.25
PROBE_TIMEOUT_SEC = 0.75
LISTEN_START_DELAY_SEC = 0.25
RECONNECT_DELAY_SEC = 1.0
VELOCITY = 100
MIXER_SAMPLE_RATE = 44100
MIXER_BUFFER_SIZE = 256
SOUND_CHANNEL_COUNT = 128
SOUND_MIN_DURATION_SEC = 1.1
SOUND_MAX_DURATION_SEC = 2.6
SOUND_RELEASE_FADE_MS = 90

NOTE_NAMES = ["Do", "Do#", "Re", "Re#", "Mi", "Fa", "Fa#", "Sol", "Sol#", "La", "La#", "Si"]
READY_PATTERN = re.compile(r"READY\s*-\s*Arduino Mega #(\d+)\s*-\s*MIDI\s*(\d+)-(\d+)", re.IGNORECASE)
MEGA_HINT_TOKENS = (
    "arduino",
    "mega",
    "usb serial",
    "usb-serial",
    "ch340",
    "cp210",
    "silicon labs",
    "uart",
)


@dataclass(frozen=True)
class PortAssignment:
    port: str
    label: str
    mega_index: int | None = None
    midi_start: int | None = None
    midi_end: int | None = None


def midi_to_frequency(note: int) -> float:
    return 440.0 * (2.0 ** ((note - 69) / 12.0))


class NoteOutput:
    backend_name = "unknown"

    def note_on(self, note: int, velocity: int = VELOCITY) -> None:
        raise NotImplementedError

    def note_off(self, note: int) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class SoftwareSynthOutput(NoteOutput):
    backend_name = "電腦喇叭（鋼琴風格備援）"

    def __init__(self) -> None:
        pygame.mixer.init(frequency=MIXER_SAMPLE_RATE, size=-16, channels=2, buffer=MIXER_BUFFER_SIZE)
        pygame.mixer.set_num_channels(SOUND_CHANNEL_COUNT)
        self._sounds: dict[int, pygame.mixer.Sound] = {}
        self._active_channels: dict[int, pygame.mixer.Channel] = {}
        self._lock = threading.Lock()

    def _lowpass(self, waveform: np.ndarray, cutoff_hz: float) -> np.ndarray:
        cutoff_hz = max(80.0, min(float(cutoff_hz), MIXER_SAMPLE_RATE * 0.45))
        alpha = math.exp(-2.0 * math.pi * cutoff_hz / MIXER_SAMPLE_RATE)
        filtered = np.empty_like(waveform)
        previous = float(waveform[0])
        filtered[0] = previous

        for index in range(1, waveform.shape[0]):
            previous = (1.0 - alpha) * float(waveform[index]) + alpha * previous
            filtered[index] = previous

        return filtered

    def _build_string_stack(self, note: int, timeline: np.ndarray, note_ratio: float) -> np.ndarray:
        frequency = midi_to_frequency(note)
        harmonic_weights = np.array([1.00, 0.58, 0.31, 0.18, 0.10, 0.06, 0.04], dtype=np.float32)
        harmonic_weights[2:] *= 1.18 - note_ratio * 0.28

        if note < 40:
            detune_cents = (0.0,)
        elif note < 64:
            detune_cents = (-2.8, 2.8)
        else:
            detune_cents = (-4.0, 0.0, 4.6)

        waveform = np.zeros_like(timeline)
        inharmonicity = 0.00006 + 0.00018 * note_ratio

        for string_index, cents in enumerate(detune_cents):
            detune_ratio = 2.0 ** (cents / 1200.0)
            phase_base = (string_index + 1) * 0.23

            for harmonic_index, weight in enumerate(harmonic_weights, start=1):
                partial_frequency = (
                    frequency
                    * detune_ratio
                    * harmonic_index
                    * (1.0 + inharmonicity * harmonic_index * harmonic_index)
                )
                if partial_frequency >= MIXER_SAMPLE_RATE * 0.45:
                    break

                waveform += np.sin(2.0 * np.pi * partial_frequency * timeline + phase_base * harmonic_index) * weight

        return waveform / float(len(detune_cents))

    def _build_sound(self, note: int) -> pygame.mixer.Sound:
        note_ratio = max(0.0, min(1.0, (note - 21) / 87.0))
        duration_sec = SOUND_MAX_DURATION_SEC - (SOUND_MAX_DURATION_SEC - SOUND_MIN_DURATION_SEC) * note_ratio
        sample_count = max(2048, int(MIXER_SAMPLE_RATE * duration_sec))
        timeline = np.arange(sample_count, dtype=np.float32) / MIXER_SAMPLE_RATE
        raw_strings = self._build_string_stack(note, timeline, note_ratio)

        warm_waveform = self._lowpass(raw_strings, 1800.0 + note * 24.0)
        bright_waveform = raw_strings - self._lowpass(raw_strings, 1200.0 + note * 18.0)
        bloom_waveform = self._lowpass(warm_waveform, 420.0 + note * 4.0)

        attack_samples = max(12, int(MIXER_SAMPLE_RATE * (0.0025 + note_ratio * 0.0008)))
        attack_curve = np.ones(sample_count, dtype=np.float32)
        attack_curve[:attack_samples] = np.linspace(0.0, 1.0, attack_samples, endpoint=False, dtype=np.float32)

        body_envelope = (
            0.74 * np.exp(-timeline * (1.8 + 1.4 * note_ratio))
            + 0.26 * np.exp(-timeline * (6.0 + 2.0 * note_ratio))
        ).astype(np.float32)
        body_envelope *= attack_curve

        brightness_envelope = np.exp(-timeline * (16.0 + 8.0 * note_ratio)).astype(np.float32)
        brightness_envelope *= attack_curve

        bloom_envelope = np.exp(-timeline * (3.6 + 1.8 * note_ratio)).astype(np.float32)
        bloom_envelope *= attack_curve

        rng = np.random.default_rng(note)
        hammer_noise = rng.standard_normal(sample_count).astype(np.float32)
        hammer_noise = hammer_noise - self._lowpass(hammer_noise, 2400.0 + note * 20.0)
        hammer_noise *= np.exp(-timeline * (52.0 + 10.0 * note_ratio)).astype(np.float32)
        hammer_noise *= attack_curve

        waveform = (
            warm_waveform * body_envelope
            + bright_waveform * brightness_envelope * (0.55 + 0.18 * note_ratio)
            + bloom_waveform * bloom_envelope * (0.16 - 0.05 * note_ratio)
            + hammer_noise * (0.020 + 0.020 * note_ratio)
        )

        waveform = np.tanh(waveform * 1.55).astype(np.float32)
        peak = float(np.max(np.abs(waveform))) or 1.0
        waveform = (waveform / peak) * 0.48

        pan = max(-0.8, min(0.8, note_ratio * 1.6 - 0.8))
        left_gain = math.cos((pan + 1.0) * math.pi / 4.0)
        right_gain = math.sin((pan + 1.0) * math.pi / 4.0)
        delay_samples = min(6, max(1, int(2 + note_ratio * 4)))
        right_waveform = np.empty_like(waveform)
        right_waveform[:delay_samples] = 0.0
        right_waveform[delay_samples:] = waveform[:-delay_samples]

        stereo_waveform = np.column_stack((waveform * left_gain, right_waveform * right_gain))
        pcm = np.asarray(stereo_waveform * 32767, dtype=np.int16)
        return pygame.sndarray.make_sound(pcm)

    def _get_sound(self, note: int) -> pygame.mixer.Sound:
        sound = self._sounds.get(note)
        if sound is None:
            sound = self._build_sound(note)
            self._sounds[note] = sound
        return sound

    def _cleanup_finished_channels(self) -> None:
        inactive_notes = [note for note, channel in self._active_channels.items() if not channel.get_busy()]
        for note in inactive_notes:
            self._active_channels.pop(note, None)

    def note_on(self, note: int, velocity: int = VELOCITY) -> None:
        with self._lock:
            self._cleanup_finished_channels()
            existing = self._active_channels.pop(note, None)
            if existing is not None:
                existing.stop()

            channel = pygame.mixer.find_channel(force=True)
            if channel is None:
                return

            volume = max(0.05, min(1.0, velocity / 127.0))
            channel.set_volume(volume)
            channel.play(self._get_sound(note), fade_ms=4)
            self._active_channels[note] = channel

    def note_off(self, note: int) -> None:
        with self._lock:
            channel = self._active_channels.pop(note, None)
            if channel is not None and channel.get_busy():
                channel.fadeout(SOUND_RELEASE_FADE_MS)

    def close(self) -> None:
        with self._lock:
            for channel in self._active_channels.values():
                try:
                    channel.stop()
                except Exception:
                    pass
            self._active_channels.clear()
        try:
            pygame.mixer.quit()
        except Exception:
            pass


class PygameMidiOutput(NoteOutput):
    backend_name = "Windows MIDI"

    def __init__(self) -> None:
        pygame.midi.init()
        output_id = pygame.midi.get_default_output_id()
        if output_id == -1:
            raise RuntimeError("沒有可用的 MIDI 輸出裝置。")

        self._output = pygame.midi.Output(output_id, 0)
        self._output.set_instrument(0, 0)
        self._output.write_short(0xB0, 7, 100)

    def note_on(self, note: int, velocity: int = VELOCITY) -> None:
        self._output.note_on(note, velocity, 0)

    def note_off(self, note: int) -> None:
        self._output.note_off(note, 0, 0)

    def close(self) -> None:
        try:
            self._output.close()
        finally:
            try:
                pygame.midi.quit()
            except Exception:
                pass


def create_note_output(backend: str) -> NoteOutput:
    normalized = backend.lower()
    errors: list[str] = []

    if normalized == "auto":
        backend_attempts = ("midi", "speaker")
    else:
        backend_attempts = (normalized,)

    for backend_name in backend_attempts:
        if backend_name == "midi":
            try:
                return PygameMidiOutput()
            except Exception as exc:
                errors.append(f"Windows MIDI 模式失敗：{exc}")
                if normalized == "midi":
                    raise RuntimeError("；".join(errors))
        elif backend_name == "speaker":
            try:
                return SoftwareSynthOutput()
            except Exception as exc:
                errors.append(f"電腦喇叭模式失敗：{exc}")
                if normalized == "speaker":
                    raise RuntimeError("；".join(errors))
        else:
            raise RuntimeError(f"不支援的輸出模式：{backend}")

    raise RuntimeError("；".join(errors) if errors else f"不支援的輸出模式：{backend}")


def configure_utf8_console() -> None:
    for stream in (getattr(__import__("sys"), "stdout"), getattr(__import__("sys"), "stderr")):
        try:
            stream.reconfigure(encoding="utf-8", line_buffering=True)
        except Exception:
            pass


def list_ports() -> list[serial.tools.list_ports_common.ListPortInfo]:
    return list(serial.tools.list_ports.comports())


def is_likely_mega_port(port: serial.tools.list_ports_common.ListPortInfo) -> bool:
    description = (port.description or "").lower()
    hwid = (port.hwid or "").lower()
    combined = f"{description} {hwid}"
    return any(token in combined for token in MEGA_HINT_TOKENS)


def parse_ready_banner(line: str) -> PortAssignment | None:
    match = READY_PATTERN.search(line)
    if not match:
        return None

    mega_index = int(match.group(1))
    midi_start = int(match.group(2))
    midi_end = int(match.group(3))
    label = f"Mega #{mega_index} ({midi_start}-{midi_end})"
    return PortAssignment(
        port="",
        label=label,
        mega_index=mega_index,
        midi_start=midi_start,
        midi_end=midi_end,
    )


def probe_port(port_name: str, timeout_sec: float = PROBE_TIMEOUT_SEC) -> PortAssignment | None:
    try:
        ser = serial.Serial(port_name, SERIAL_BAUD, timeout=SERIAL_TIMEOUT_SEC)
    except Exception as exc:
        print(f"略過 {port_name}：無法開啟 ({exc})")
        return None

    try:
        time.sleep(PROBE_STARTUP_WAIT_SEC)
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            raw = ser.readline()
            if not raw:
                time.sleep(0.02)
                continue

            line = raw.decode("utf-8", errors="ignore").strip()
            if not line:
                continue

            parsed = parse_ready_banner(line)
            if parsed is not None:
                return PortAssignment(
                    port=port_name,
                    label=parsed.label,
                    mega_index=parsed.mega_index,
                    midi_start=parsed.midi_start,
                    midi_end=parsed.midi_end,
                )
        return None
    finally:
        ser.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="自動偵測 Arduino Mega 2560 按鈕控制板，並把按鍵聲送到喇叭或 MIDI。")
    parser.add_argument(
        "ports",
        nargs="*",
        help="可選：只掃描指定 COM 埠，例如 COM3 COM4。不填就自動掃描全部序列埠。",
    )
    parser.add_argument(
        "--backend",
        choices=["auto", "speaker", "midi"],
        default="auto",
        help="聲音輸出模式：auto 預設優先用電腦喇叭，其次才是 Windows MIDI。",
    )
    return parser


def resolve_targets(raw_ports: list[str]) -> list[str]:
    ports = list_ports()
    if raw_ports:
        return [port.upper() for port in raw_ports if port.strip()]

    likely_ports = [port.device for port in ports if is_likely_mega_port(port)]
    if likely_ports:
        return likely_ports

    return [port.device for port in ports]


def auto_match_ports(target_ports: list[str]) -> list[PortAssignment]:
    matched: list[PortAssignment] = []
    unmatched: list[str] = []

    if not target_ports:
        return matched

    print("正在自動辨識 Arduino Mega 2560 按鈕板...")
    scanned_results: dict[str, PortAssignment | None] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(len(target_ports), 4))) as executor:
        future_map = {executor.submit(probe_port, port_name): port_name for port_name in target_ports}
        for future in as_completed(future_map):
            scanned_results[future_map[future]] = future.result()

    for port_name in target_ports:
        assignment = scanned_results.get(port_name)
        if assignment is None:
            unmatched.append(port_name)
            continue
        matched.append(assignment)
        print(f"  已匹配 {assignment.port} -> {assignment.label}")

    matched.sort(key=lambda item: (item.mega_index is None, item.mega_index or 999, item.port))

    if unmatched:
        print("以下埠沒有辨識到 Mega 開機訊息：")
        for port_name in unmatched:
            print(f"  - {port_name}")

    return matched


def midi_note_name(note: int) -> str:
    return f"{NOTE_NAMES[note % 12]}{note // 12 - 1}"


def handle_serial(assignment: PortAssignment, note_output: NoteOutput) -> None:
    while True:
        try:
            ser = serial.Serial(assignment.port, SERIAL_BAUD, timeout=SERIAL_TIMEOUT_SEC)
        except Exception as exc:
            print(f"[{assignment.label}] 無法連線到 {assignment.port}：{exc}")
            time.sleep(RECONNECT_DELAY_SEC)
            continue

        try:
            time.sleep(LISTEN_START_DELAY_SEC)
            print(f"[{assignment.label}] 已開始監聽 {assignment.port}")

            while True:
                raw = ser.readline()
                if not raw:
                    continue

                line = raw.decode("utf-8", errors="ignore").strip()
                if not line or not line.startswith("NOTE_"):
                    continue

                parts = line.split(":")
                if len(parts) < 2:
                    continue

                try:
                    note = int(parts[1])
                except ValueError:
                    continue

                pin = None
                if len(parts) >= 4 and parts[2].upper() == "PIN":
                    try:
                        pin = int(parts[3])
                    except ValueError:
                        pin = None

                status = 0x90 if parts[0] == "NOTE_ON" else 0x80
                if status == 0x90:
                    note_output.note_on(note, VELOCITY)
                else:
                    note_output.note_off(note)

                action = "ON" if status == 0x90 else "OFF"
                if pin is None:
                    print(f"[{assignment.label} | {assignment.port}] {midi_note_name(note)} ({action})")
                else:
                    print(f"[{assignment.label} | {assignment.port}] {midi_note_name(note)} ({action}) pin {pin}")
        except Exception as exc:
            print(f"[{assignment.label}] 連線中斷：{exc}")
            time.sleep(RECONNECT_DELAY_SEC)
        finally:
            try:
                ser.close()
            except Exception:
                pass


def main() -> None:
    configure_utf8_console()

    parser = build_parser()
    args = parser.parse_args()
    note_output = create_note_output(args.backend)
    print(f"聲音輸出：{note_output.backend_name}")

    target_ports = resolve_targets(args.ports)
    assignments = auto_match_ports(target_ports)

    if not assignments:
        print("找不到可用的 Arduino Mega 2560 按鈕板。")
        print("請確認：")
        print("  1. 板子已連接")
        print("  2. 已燒錄 mega_buttons_1.ino / mega_buttons_2.ino")
        print("  3. 沒有被其他程式占用")
        raise SystemExit(1)

    print("自動匹配完成：")
    for assignment in assignments:
        print(f"  - {assignment.port} -> {assignment.label}")

    for assignment in assignments:
        thread = threading.Thread(target=handle_serial, args=(assignment, note_output), daemon=True)
        thread.start()

    print("正在監聽按鍵的 NOTE_ON / NOTE_OFF 訊號...")
    try:
        while True:
            time.sleep(1)
    finally:
        note_output.close()


if __name__ == "__main__":
    main()
