from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import serial
import serial.tools.list_ports


SERIAL_BAUD = 115200
SERIAL_TIMEOUT_SEC = 0.2
STARTUP_WAIT_SEC = 0.25
BANNER_READ_SEC = 0.45
PING_READ_SEC = 0.25

ESP32_HINT_TOKENS = (
    "silicon labs",
    "usb-serial",
    "usb serial",
    "cp210",
    "ch340",
    "ch910",
    "esp32",
    "uart bridge",
)
MAX_PROBE_WORKERS = 4

MAIN_FIRMWARE_BANNERS = ("READY - 88 Keys",)
TUNER_FIRMWARE_BANNERS = ("TUNER_READY",)
MEGA_READY_PATTERN = re.compile(r"READY\s*-\s*Arduino Mega #\d+\s*-\s*MIDI\s*\d+-\d+", re.IGNORECASE)


@dataclass(frozen=True)
class Esp32PortProbe:
    port: str
    description: str
    mode: str
    banners: tuple[str, ...]
    likely_esp32: bool
    error: str | None = None


def normalize_port_name(value: str) -> str:
    return value.strip().upper()


def list_serial_ports() -> list[serial.tools.list_ports_common.ListPortInfo]:
    return list(serial.tools.list_ports.comports())


def is_likely_esp32_description(description: str) -> bool:
    lowered = (description or "").lower()
    return any(token in lowered for token in ESP32_HINT_TOKENS)


def sort_serial_ports(
    ports: list[serial.tools.list_ports_common.ListPortInfo],
) -> list[serial.tools.list_ports_common.ListPortInfo]:
    return sorted(
        ports,
        key=lambda port: (
            0 if is_likely_esp32_description(port.description or "") else 1,
            normalize_port_name(port.device),
        ),
    )


def read_serial_lines(ser: serial.Serial, duration_sec: float) -> list[str]:
    deadline = time.time() + duration_sec
    lines: list[str] = []

    while time.time() < deadline:
        raw = ser.readline()
        if not raw:
            time.sleep(0.02)
            continue
        line = raw.decode("utf-8", errors="ignore").strip()
        if line:
            lines.append(line)

    return lines


def classify_banner_lines(lines: list[str] | tuple[str, ...]) -> str:
    banner_text = "\n".join(lines)

    if any(marker in banner_text for marker in TUNER_FIRMWARE_BANNERS):
        return "tuner"
    if any(MEGA_READY_PATTERN.search(line) for line in lines):
        return "mega"
    if any(marker in banner_text for marker in MAIN_FIRMWARE_BANNERS):
        return "main"
    if any(line.strip() == "READY" for line in lines):
        return "main"
    return "unknown"


def ping_for_ready(ser: serial.Serial) -> list[str]:
    try:
        ser.reset_input_buffer()
    except Exception:
        pass

    ser.write(b"PING,0\n")
    ser.flush()
    return read_serial_lines(ser, PING_READ_SEC)


def probe_serial_port(port_name: str, description: str = "") -> Esp32PortProbe:
    likely_esp32 = is_likely_esp32_description(description)

    try:
        ser = serial.Serial(port_name, SERIAL_BAUD, timeout=SERIAL_TIMEOUT_SEC)
    except Exception as exc:
        return Esp32PortProbe(
            port=port_name,
            description=description,
            mode="unavailable",
            banners=(),
            likely_esp32=likely_esp32,
            error=str(exc),
        )

    try:
        time.sleep(STARTUP_WAIT_SEC)
        lines = read_serial_lines(ser, BANNER_READ_SEC)
        mode = classify_banner_lines(lines)

        if mode == "unknown":
            ping_lines = ping_for_ready(ser)
            if ping_lines:
                lines.extend(ping_lines)
                mode = classify_banner_lines(lines)

        return Esp32PortProbe(
            port=port_name,
            description=description,
            mode=mode,
            banners=tuple(lines),
            likely_esp32=likely_esp32,
        )
    finally:
        ser.close()


def probe_serial_ports(port_names: list[str] | None = None) -> list[Esp32PortProbe]:
    available_ports = list_serial_ports()
    info_by_name = {normalize_port_name(port.device): port for port in available_ports}

    if port_names:
        ordered_names: list[str] = []
        seen: set[str] = set()
        for raw_name in port_names:
            port_name = normalize_port_name(raw_name)
            if not port_name or port_name in seen:
                continue
            seen.add(port_name)
            ordered_names.append(info_by_name.get(port_name, raw_name).device if port_name in info_by_name else port_name)
    else:
        sorted_ports = sort_serial_ports(available_ports)
        likely_ports = [port.device for port in sorted_ports if is_likely_esp32_description(port.description or "")]
        ordered_names = likely_ports or [port.device for port in sorted_ports]

    future_map = {}
    results_by_name: dict[str, Esp32PortProbe] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(len(ordered_names), MAX_PROBE_WORKERS))) as executor:
        for port_name in ordered_names:
            port_info = info_by_name.get(normalize_port_name(port_name))
            description = port_info.description if port_info is not None else ""
            future = executor.submit(probe_serial_port, port_name, description or "")
            future_map[future] = port_name
        for future in as_completed(future_map):
            results_by_name[future_map[future]] = future.result()

    results: list[Esp32PortProbe] = []
    for port_name in ordered_names:
        probe = results_by_name.get(port_name)
        if probe is not None:
            results.append(probe)

    return results


def select_best_esp32_probe(
    probes: list[Esp32PortProbe],
    *,
    expected_mode: str | None = None,
) -> Esp32PortProbe | None:
    if expected_mode:
        for probe in probes:
            if probe.mode == expected_mode:
                return probe
        return None

    for probe in probes:
        if probe.mode in {"main", "tuner"}:
            return probe

    return None


def find_best_esp32_port(
    *,
    expected_mode: str | None = None,
    port_names: list[str] | None = None,
) -> tuple[Esp32PortProbe | None, list[Esp32PortProbe]]:
    probes = probe_serial_ports(port_names=port_names)
    return select_best_esp32_probe(probes, expected_mode=expected_mode), probes
