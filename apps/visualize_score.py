from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    import pygame
    import pygame.midi
except ImportError:
    print("缺少 pygame，請先安裝：pip install pygame")
    input("請按 Enter 結束...")
    raise SystemExit(1)

FPS = 60
WIN_WIDTH = 1200
WIN_HEIGHT = 800
KEYBOARD_HEIGHT = 150
FALL_SPEED = 0.6
KEY_WHITE_WIDTH = WIN_WIDTH / 52
PLAYBACK_DELAY_MS = 2000

COLOR_BG = (20, 20, 25)
COLOR_WHITE_KEY = (240, 240, 240)
COLOR_BLACK_KEY = (30, 30, 30)
COLOR_LEFT_HAND = (100, 200, 255)
COLOR_RIGHT_HAND = (255, 200, 50)
COLOR_BOTH_HAND = (100, 255, 100)
COLOR_PROGRESS_TRACK = (48, 52, 68)
COLOR_PROGRESS_FILL = (112, 211, 255)
COLOR_PROGRESS_BORDER = (180, 188, 208)
COLOR_PROGRESS_TEXT = (240, 244, 255)

MIN_PITCH = 21
MAX_PITCH = 108


def build_keyboard_layout() -> tuple[dict[int, dict[str, object]], list[int], list[int]]:
    white_keys: list[int] = []
    black_keys: list[int] = []
    current_white_idx = 0
    keys: dict[int, dict[str, object]] = {}

    for pitch in range(MIN_PITCH, MAX_PITCH + 1):
        note_idx = pitch % 12
        is_white = note_idx in {0, 2, 4, 5, 7, 9, 11}

        if is_white:
            x = current_white_idx * KEY_WHITE_WIDTH
            rect = pygame.Rect(round(x), WIN_HEIGHT - KEYBOARD_HEIGHT, round(KEY_WHITE_WIDTH), KEYBOARD_HEIGHT)
            keys[pitch] = {"type": "W", "rect": rect, "x": x}
            white_keys.append(pitch)
            current_white_idx += 1
            continue

        prev_white_x = (current_white_idx - 1) * KEY_WHITE_WIDTH
        width = KEY_WHITE_WIDTH * 0.6
        height = KEYBOARD_HEIGHT * 0.65
        x = prev_white_x + KEY_WHITE_WIDTH - (width / 2)
        rect = pygame.Rect(round(x), WIN_HEIGHT - KEYBOARD_HEIGHT, round(width), round(height))
        keys[pitch] = {"type": "B", "rect": rect, "x": x}
        black_keys.append(pitch)

    return keys, white_keys, black_keys


def load_score_from_py(file_path: Path) -> tuple[list[tuple], list[str]]:
    spec = importlib.util.spec_from_file_location("song_module", str(file_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"無法載入樂譜檔：{file_path}")
    song_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(song_module)
    score = getattr(song_module, "SCORE", [])
    esp32 = getattr(song_module, "ESP32_LINES", [])
    return score, esp32


def extract_hand_map_from_score(score_data: list[tuple]) -> dict[int, str]:
    hand_map: dict[int, str] = {}
    for item in score_data:
        kind = item[0]
        if kind == 10:
            hand_map[int(item[2])] = str(item[1]).upper()[0]
        elif kind in (11, 12):
            for pitch in item[2]:
                hand_map[int(pitch)] = str(item[1]).upper()[0]
    return hand_map


def parse_esp32_timeline(lines: list[str], hand_map: dict[int, str] | None = None) -> list[dict[str, float | int | str]]:
    notes: list[dict[str, float | int | str]] = []
    current_time = 0.0
    active_ons: dict[int, float] = {}

    for raw_line in lines:
        parts = str(raw_line).strip().split(",")
        if not parts or not parts[0]:
            continue

        cmd = parts[0].upper()
        if cmd == "WAIT" and len(parts) > 1:
            current_time += float(parts[1])
            continue

        if cmd == "ON" and len(parts) > 1 and parts[1]:
            for pitch in [int(value) for value in parts[1].split("+") if value]:
                active_ons[pitch] = current_time
            continue

        if cmd == "OFF" and len(parts) > 1 and parts[1]:
            for pitch in [int(value) for value in parts[1].split("+") if value]:
                if pitch not in active_ons:
                    continue
                start_time = active_ons.pop(pitch)
                duration = max(1.0, current_time - start_time)
                hand = hand_map.get(pitch, "L" if pitch < 60 else "R") if hand_map else ("L" if pitch < 60 else "R")
                notes.append({"pitch": pitch, "start": start_time, "dur": duration, "hand": hand})

    notes.sort(key=lambda item: (float(item["start"]), int(item["pitch"])))
    return notes


def parse_timeline(score_data: list[tuple]) -> list[dict[str, float | int | str]]:
    notes: list[dict[str, float | int | str]] = []
    current_time = 0.0

    for item in score_data:
        kind = item[0]
        if kind == 0:
            current_time += float(item[1])
        elif kind == 1:
            pitch, duration = int(item[1]), float(item[2])
            notes.append({"pitch": pitch, "start": current_time, "dur": duration, "hand": "B"})
            current_time += duration
        elif kind == 3:
            pitches, duration = item[1], float(item[2])
            for pitch in pitches:
                notes.append({"pitch": int(pitch), "start": current_time, "dur": duration, "hand": "B"})
            current_time += duration
        elif kind == 4:
            pitches, duration, offsets = item[1], float(item[2]), item[3]
            for pitch, offset in zip(pitches, offsets):
                notes.append({"pitch": int(pitch), "start": current_time + float(offset), "dur": duration, "hand": "B"})
            current_time += duration
        elif kind == 10:
            hand, pitch, duration = str(item[1]), int(item[2]), float(item[3])
            notes.append({"pitch": pitch, "start": current_time, "dur": duration, "hand": hand})
            current_time += duration
        elif kind == 11:
            hand, pitches, duration = str(item[1]), item[2], float(item[3])
            for pitch in pitches:
                notes.append({"pitch": int(pitch), "start": current_time, "dur": duration, "hand": hand})
            current_time += duration
        elif kind == 12:
            hand, pitches, duration, offsets = str(item[1]), item[2], float(item[3]), item[4]
            for pitch, offset in zip(pitches, offsets):
                notes.append({"pitch": int(pitch), "start": current_time + float(offset), "dur": duration, "hand": hand})
            current_time += duration

    notes.sort(key=lambda item: (float(item["start"]), int(item["pitch"])))
    return notes


def calculate_total_duration_ms(notes: list[dict[str, float | int | str]]) -> float:
    if not notes:
        return 0.0
    return max(float(note["start"]) + float(note["dur"]) for note in notes)


def format_time_ms(value_ms: float) -> str:
    total_seconds = max(0, int(value_ms // 1000))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:d}:{seconds:02d}"


def draw_progress_bar(screen: pygame.Surface, font: pygame.font.Font, current_ms: float, total_ms: float) -> None:
    bar_margin_x = 24
    bar_top = 18
    bar_height = 18
    bar_rect = pygame.Rect(bar_margin_x, bar_top, WIN_WIDTH - (bar_margin_x * 2), bar_height)

    playable_total_ms = max(1.0, total_ms)
    clamped_current_ms = min(max(current_ms, 0.0), playable_total_ms)
    progress_ratio = clamped_current_ms / playable_total_ms

    pygame.draw.rect(screen, COLOR_PROGRESS_TRACK, bar_rect, border_radius=9)
    pygame.draw.rect(screen, COLOR_PROGRESS_BORDER, bar_rect, width=1, border_radius=9)

    inner_rect = bar_rect.inflate(-4, -4)
    fill_width = round(inner_rect.width * progress_ratio)
    if fill_width > 0:
        fill_rect = pygame.Rect(inner_rect.left, inner_rect.top, fill_width, inner_rect.height)
        pygame.draw.rect(screen, COLOR_PROGRESS_FILL, fill_rect, border_radius=7)

    time_text = f"{format_time_ms(clamped_current_ms)} / {format_time_ms(playable_total_ms)}"
    text_surface = font.render(time_text, True, COLOR_PROGRESS_TEXT)
    screen.blit(text_surface, (bar_rect.left, bar_rect.bottom + 8))


def choose_score_file(initial_dir: Path) -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        print("無法開啟檔案選擇視窗，請直接在命令列後面指定 songs/*.py")
        return ""

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    selected_file = filedialog.askopenfilename(
        title="選擇要播放的樂譜",
        initialdir=str(initial_dir),
        filetypes=[("Python Score Files", "*.py"), ("All Files", "*.*")],
    )
    root.destroy()
    return selected_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Synthesia 風格的鋼琴樂譜模擬播放。")
    parser.add_argument("score_file", nargs="?", default="", help="要播放的 songs/*.py 樂譜檔")
    args = parser.parse_args()

    selected_file = args.score_file or choose_score_file(PROJECT_ROOT / "songs")
    if not selected_file:
        print("沒有選擇任何樂譜。")
        return 0

    score_path = Path(selected_file)
    if not score_path.is_file():
        raise RuntimeError(f"找不到指定的樂譜檔：{score_path}")

    print(f"載入樂譜: {score_path.name}")
    score_data, esp32_data = load_score_from_py(score_path)

    if esp32_data:
        print("  - 已找到 ESP32_LINES，模擬播放會使用精準時間軸。")
        hand_map = extract_hand_map_from_score(score_data)
        notes = parse_esp32_timeline(esp32_data, hand_map)
    else:
        print("  - 沒有 ESP32_LINES，改用 SCORE 時間軸。")
        notes = parse_timeline(score_data)

    if not notes:
        raise RuntimeError("這份樂譜沒有任何可播放的音符。")

    total_duration_ms = calculate_total_duration_ms(notes)

    pygame.init()
    pygame.midi.init()
    screen = pygame.display.set_mode((WIN_WIDTH, WIN_HEIGHT))
    pygame.display.set_caption(f"Synthesia 效果播放器 - {score_path.name}")
    clock = pygame.time.Clock()
    progress_font = pygame.font.Font(None, 28)

    midi_out: pygame.midi.Output | None = None
    port = pygame.midi.get_default_output_id()
    if port != -1:
        midi_out = pygame.midi.Output(port, 0)
        midi_out.set_instrument(0)
    else:
        print("警告: 沒有偵測到可用的 MIDI 輸出裝置，將只顯示畫面。")

    keys_layout, white_keys, black_keys = build_keyboard_layout()
    start_ticks = pygame.time.get_ticks()
    active_notes: list[dict[str, float | int | str | bool]] = []
    played_index = 0
    running = True

    try:
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

            now_ms = pygame.time.get_ticks() - start_ticks - PLAYBACK_DELAY_MS
            pre_render_ms = (WIN_HEIGHT - KEYBOARD_HEIGHT) / FALL_SPEED

            while played_index < len(notes) and float(notes[played_index]["start"]) <= now_ms + pre_render_ms:
                note = notes[played_index].copy()
                note["played"] = False
                note["released"] = False
                active_notes.append(note)
                played_index += 1

            screen.fill(COLOR_BG)
            active_keys: dict[int, tuple[int, int, int]] = {}
            remaining_notes: list[dict[str, float | int | str | bool]] = []

            for note in active_notes:
                pitch = int(note["pitch"])
                if pitch < MIN_PITCH or pitch > MAX_PITCH:
                    note["released"] = True
                    continue

                start_y = WIN_HEIGHT - KEYBOARD_HEIGHT - (float(note["start"]) - now_ms) * FALL_SPEED
                end_y = WIN_HEIGHT - KEYBOARD_HEIGHT - (float(note["start"]) + float(note["dur"]) - now_ms) * FALL_SPEED
                height = max(5, round(start_y - end_y))

                key_meta = keys_layout[pitch]
                width = KEY_WHITE_WIDTH if key_meta["type"] == "W" else KEY_WHITE_WIDTH * 0.6
                x = float(key_meta["x"])

                hand = str(note["hand"]).upper()
                if hand.startswith("L"):
                    color = COLOR_LEFT_HAND
                elif hand.startswith("R"):
                    color = COLOR_RIGHT_HAND
                else:
                    color = COLOR_BOTH_HAND

                if not bool(note["played"]) and now_ms >= float(note["start"]):
                    note["played"] = True
                    if midi_out is not None:
                        midi_out.note_on(pitch, 100)

                if bool(note["played"]) and not bool(note["released"]) and now_ms >= float(note["start"]) + float(note["dur"]):
                    note["released"] = True
                    if midi_out is not None:
                        midi_out.note_off(pitch, 100)

                if bool(note["played"]) and not bool(note["released"]):
                    active_keys[pitch] = color

                if end_y < WIN_HEIGHT and start_y > 0:
                    rect = pygame.Rect(round(x + 1), round(end_y), round(width - 2), height)
                    pygame.draw.rect(screen, color, rect, border_radius=4)
                    highlight = pygame.Rect(round(x + (width / 3)), round(end_y), round(width / 3), height)
                    pygame.draw.rect(screen, (255, 255, 255), highlight, border_radius=4)

                if not bool(note["released"]) or start_y < WIN_HEIGHT:
                    remaining_notes.append(note)

            active_notes = remaining_notes

            for pitch in white_keys:
                rect = keys_layout[pitch]["rect"]
                pygame.draw.rect(screen, active_keys.get(pitch, COLOR_WHITE_KEY), rect)
                pygame.draw.rect(screen, (0, 0, 0), rect, width=1)

            for pitch in black_keys:
                rect = keys_layout[pitch]["rect"]
                pygame.draw.rect(screen, active_keys.get(pitch, COLOR_BLACK_KEY), rect)
                pygame.draw.rect(screen, (0, 0, 0), rect, width=1)

            draw_progress_bar(screen, progress_font, now_ms, total_duration_ms)
            pygame.display.flip()
            clock.tick(FPS)
    finally:
        if midi_out is not None:
            for note in active_notes:
                if bool(note.get("played")) and not bool(note.get("released")):
                    midi_out.note_off(int(note["pitch"]), 100)
            midi_out.close()
        pygame.midi.quit()
        pygame.quit()

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print("\n[發生錯誤]")
        traceback.print_exc()
        input("\n糟糕！程式發生了錯誤，請按 Enter 鍵結束...")
