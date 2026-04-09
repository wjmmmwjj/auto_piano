from __future__ import annotations

import re
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
INO_PATH = PROJECT_ROOT / "esp32" / "motor_control" / "motor_control.ino"


def parse_ino(path: Path) -> tuple[str | None, list[dict[str, int]] | None]:
    if not path.exists():
        print(f"Error: file not found: {path}")
        return None, None

    content = path.read_text(encoding="utf-8")
    pattern = r"(?:const\s+)?int\s+N\[\]\[7\]\s*=\s*\{([\s\S]*?)\};"
    match = re.search(pattern, content)
    if not match:
        print("Error: could not find the N[][7] table in the ino file.")
        return None, None

    array_str = match.group(1)
    line_pattern = r"\{\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\}"
    entries: list[dict[str, int]] = []
    for line in array_str.splitlines():
        row_match = re.search(line_pattern, line)
        if not row_match:
            continue
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
    return content, entries


def save_ino(path: Path, original_content: str, entries: list[dict[str, int]]) -> None:
    backup_path = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup_path)
    print(f"Backup written to: {backup_path}")

    new_array_lines = [
        f"  {{{e['midi']}, {e['board']}, {e['channel']}, {e['p0']}, {e['p180']}, {e['press']}, {e['release']}}}"
        for e in entries
    ]
    new_array_str = "\n" + ",\n".join(new_array_lines) + "\n"
    pattern = r"((?:const\s+)?int\s+N\[\]\[7\]\s*=\s*\{)[\s\S]*?(\};)"
    new_content = re.sub(pattern, r"\1" + new_array_str + r"\2", original_content)
    path.write_text(new_content, encoding="utf-8")
    print(f"Updated: {path}")


def main() -> None:
    print("=== Ino Config Editor ===")
    content, entries = parse_ino(INO_PATH)
    if not content or not entries:
        return

    while True:
        print(f"\nLoaded {len(entries)} motor entries.")
        search = input("Enter MIDI note 21-108, or `q` to save and quit: ").strip().lower()
        if search == "q":
            save_ino(INO_PATH, content, entries)
            print("Done.")
            return
        if not search.isdigit():
            print("Please enter a valid number.")
            continue

        midi_val = int(search)
        target = next((entry for entry in entries if entry["midi"] == midi_val), None)
        if target is None:
            print(f"MIDI {midi_val} not found.")
            continue

        print(f"\nEditing MIDI {midi_val}")
        print(
            f"Current: board={target['board']}, channel={target['channel']}, "
            f"press={target['press']}, release={target['release']}"
        )
        try:
            target["board"] = int(input(f"Board [{target['board']}]: ") or target["board"])
            target["channel"] = int(input(f"Channel [{target['channel']}]: ") or target["channel"])
            target["press"] = int(input(f"Press angle [{target['press']}]: ") or target["press"])
            target["release"] = int(input(f"Release angle [{target['release']}]: ") or target["release"])
            print("Updated in memory.")
        except ValueError:
            print("Invalid numeric input. Changes for this entry were skipped.")


if __name__ == "__main__":
    main()
