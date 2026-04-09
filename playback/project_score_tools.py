from __future__ import annotations

import re
from typing import Iterable

MIN_MIDI = 21
MAX_MIDI = 108
NOTE_NAMES_SHARP = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

REST_MS = 0       # Do not globally pad rests; preserve the original groove unless a note must be stretched
TIME_STEP_MS = 10
MIN_NOTE_MS = 60     # Forced minimum playable duration for score playback
ULTRA_SHORT_NOTE_MS = 40
ULTRA_SHORT_TARGET_MS = 60
MAX_UNBACKED_STRETCH_MS = 60
MAX_NOTE_MS = 30000
MAX_CHORD_NOTES = 12
MIN_ARP_SPREAD_MS = 5
MAX_ARP_SPREAD_MS = 120
MIN_ARP_RELEASE_MS = 5
MAX_ARP_RELEASE_MS = 80
ARP_OFFSET_STEP_MS = 5
HAND_LEFT = "L"
HAND_RIGHT = "R"
REPEAT_RELEASE_MIN_MS = 20
REPEAT_RELEASE_MAX_MS = 60
REPEAT_RELEASE_RATIO = 0.2
REPEAT_RELEASE_TOLERANCE_MS = 20


def quantize_ms(value: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    result = int(round(value / TIME_STEP_MS) * TIME_STEP_MS)
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def normalize_pitch(pitch: int) -> int:
    return max(MIN_MIDI, min(MAX_MIDI, int(pitch)))


def require_supported_pitch(pitch: int | str, midi: int) -> int:
    if MIN_MIDI <= midi <= MAX_MIDI:
        return midi
    raise ValueError(
        f"Pitch {pitch!r} is outside the supported 88-key range "
        f"(MIDI {MIN_MIDI}-{MAX_MIDI}, A0-C8)."
    )


def midi_to_note_name(pitch: int) -> str:
    midi = normalize_pitch(pitch)
    octave = (midi // 12) - 1
    note_name = NOTE_NAMES_SHARP[midi % 12]
    return f"{note_name}{octave}"


def parse_pitch_token(value: int | str) -> int:
    if isinstance(value, int):
        return require_supported_pitch(value, int(value))

    text = str(value).strip()
    if not text:
        raise ValueError("音高不能是空白。")
    if text.lstrip("-").isdigit():
        midi = int(text)
        return require_supported_pitch(value, midi)

    match = re.fullmatch(r"([A-Ga-g])([#b]?)(-?\d+)", text)
    if not match:
        raise ValueError(f"無法解析音高：{value}")

    base = match.group(1).upper()
    accidental = match.group(2)
    octave = int(match.group(3))
    semitone_map = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    semitone = semitone_map[base]
    if accidental == "#":
        semitone += 1
    elif accidental == "b":
        semitone -= 1

    midi = (octave + 1) * 12 + semitone
    return require_supported_pitch(value, midi)


def parse_pitch_collection(values: Iterable[int | str] | str | int) -> list[int]:
    if isinstance(values, (int, str)):
        if isinstance(values, str):
            text = values.replace(",", " ").replace("+", " ").replace("|", " ")
            tokens = [token for token in text.split() if token]
            if len(tokens) > 1:
                return [parse_pitch_token(token) for token in tokens]
        return [parse_pitch_token(values)]
    return [parse_pitch_token(value) for value in values]


def r(duration_ms: int) -> tuple[int, int]:
    return (0, int(duration_ms))


def n(pitch: int | str, duration_ms: int) -> tuple[int, int, int]:
    return (1, parse_pitch_token(pitch), int(duration_ms))


def c(pitches: Iterable[int | str] | str | int, duration_ms: int) -> tuple[int, list[int], int]:
    return (3, parse_pitch_collection(pitches), int(duration_ms))


def a(
    pitches: Iterable[int | str] | str | int,
    duration_ms: int,
    offsets_ms: Iterable[int] | int,
    release_ms: int = MIN_ARP_RELEASE_MS,
) -> tuple[int, list[int], int, Iterable[int] | int, int]:
    return (4, parse_pitch_collection(pitches), int(duration_ms), offsets_ms, int(release_ms))


def ln(pitch: int | str, duration_ms: int) -> tuple[int, str, int, int]:
    return (10, HAND_LEFT, parse_pitch_token(pitch), int(duration_ms))


def rn(pitch: int | str, duration_ms: int) -> tuple[int, str, int, int]:
    return (10, HAND_RIGHT, parse_pitch_token(pitch), int(duration_ms))


def lc(pitches: Iterable[int | str] | str | int, duration_ms: int) -> tuple[int, str, list[int], int]:
    return (11, HAND_LEFT, parse_pitch_collection(pitches), int(duration_ms))


def rc(pitches: Iterable[int | str] | str | int, duration_ms: int) -> tuple[int, str, list[int], int]:
    return (11, HAND_RIGHT, parse_pitch_collection(pitches), int(duration_ms))


def la(
    pitches: Iterable[int | str] | str | int,
    duration_ms: int,
    offsets_ms: Iterable[int] | int,
    release_ms: int = MIN_ARP_RELEASE_MS,
) -> tuple[int, str, list[int], int, Iterable[int] | int, int]:
    return (12, HAND_LEFT, parse_pitch_collection(pitches), int(duration_ms), offsets_ms, int(release_ms))


def ra(
    pitches: Iterable[int | str] | str | int,
    duration_ms: int,
    offsets_ms: Iterable[int] | int,
    release_ms: int = MIN_ARP_RELEASE_MS,
) -> tuple[int, str, list[int], int, Iterable[int] | int, int]:
    return (12, HAND_RIGHT, parse_pitch_collection(pitches), int(duration_ms), offsets_ms, int(release_ms))


def choose_chord_pitches(pitches: Iterable[int | str]) -> list[int]:
    unique = sorted({parse_pitch_token(pitch) for pitch in pitches})
    if len(unique) <= MAX_CHORD_NOTES:
        return unique

    selected = [unique[0], unique[-1]]
    remaining = unique[1:-1]
    while remaining and len(selected) < MAX_CHORD_NOTES:
        best = max(remaining, key=lambda pitch: min(abs(pitch - chosen) for chosen in selected))
        selected.append(best)
        remaining.remove(best)

    return sorted(selected)


def normalize_arp_offsets(offsets: Iterable[int], note_count: int) -> list[int]:
    cleaned = [max(0, int(offset)) for offset in offsets]
    if note_count <= 0:
        return []
    if not cleaned:
        return [0]

    normalized: list[int] = []
    last_offset = 0
    for index, offset in enumerate(cleaned[:note_count]):
        current = int(round(offset / ARP_OFFSET_STEP_MS) * ARP_OFFSET_STEP_MS)
        current = max(0, min(MAX_NOTE_MS, current))
        if index == 0:
            current = 0
        else:
            current = max(last_offset, current)
        normalized.append(current)
        last_offset = current

    while len(normalized) < note_count:
        normalized.append(last_offset)

    return normalized


def merge_score_rests(score: list[tuple]) -> list[tuple]:
    merged: list[tuple] = []
    for item in score:
        if item[0] == 0 and merged and merged[-1][0] == 0:
            merged[-1] = (0, int(merged[-1][1]) + int(item[1]))
            continue
        merged.append(item)
    return merged


def get_event_duration(item: list | tuple) -> int:
    kind = int(item[0])
    if kind == 0:
        return int(item[1])
    if kind in (1, 3, 4):
        return int(item[2])
    if kind in (10, 11, 12):
        return int(item[3])
    return 0


def set_event_duration(item: list, duration_ms: int) -> None:
    kind = int(item[0])
    if kind == 0:
        item[1] = int(duration_ms)
    elif kind in (1, 3, 4):
        item[2] = int(duration_ms)
    elif kind in (10, 11, 12):
        item[3] = int(duration_ms)


def get_target_short_note_duration(duration_ms: int) -> int:
    current = int(duration_ms)
    if current <= ULTRA_SHORT_NOTE_MS:
        return ULTRA_SHORT_TARGET_MS
    if current < MIN_NOTE_MS:
        return MIN_NOTE_MS
    return current


def stretch_short_notes(score: list[tuple]) -> list[tuple]:
    """
    Make ultra-short notes playable without globally slowing the song.
    Prefer borrowing time from the following rest. If the next event is another
    note, redistribute time locally from that following note before allowing the
    whole phrase to grow longer.
    """
    adjusted = [list(item) for item in score]

    for index in range(len(adjusted)):
        current = adjusted[index]

        if int(current[0]) == 0:
            continue

        current_duration_ms = get_event_duration(current)
        target_duration_ms = get_target_short_note_duration(current_duration_ms)
        if current_duration_ms >= target_duration_ms:
            continue

        needed_ms = target_duration_ms - current_duration_ms

        if index + 1 < len(adjusted) and needed_ms > 0:
            following = adjusted[index + 1]
            following_kind = int(following[0])

            if following_kind == 0:
                following_rest_ms = get_event_duration(following)
                borrowed_ms = min(needed_ms, following_rest_ms)
                if borrowed_ms > 0:
                    set_event_duration(following, following_rest_ms - borrowed_ms)
                    set_event_duration(current, get_event_duration(current) + borrowed_ms)
                    needed_ms -= borrowed_ms
            else:
                following_duration_ms = get_event_duration(following)
                following_target_ms = MIN_NOTE_MS
                transferable_ms = max(0, following_duration_ms - following_target_ms)
                borrowed_ms = min(needed_ms, transferable_ms)
                if borrowed_ms > 0:
                    set_event_duration(following, following_duration_ms - borrowed_ms)
                    set_event_duration(current, get_event_duration(current) + borrowed_ms)
                    needed_ms -= borrowed_ms

        if needed_ms > 0 and current_duration_ms <= ULTRA_SHORT_NOTE_MS:
            extra_ms = min(needed_ms, MAX_UNBACKED_STRETCH_MS)
            if extra_ms > 0:
                set_event_duration(current, get_event_duration(current) + extra_ms)

    cleaned: list[tuple] = []
    for item in adjusted:
        if int(item[0]) == 0 and get_event_duration(item) <= 0:
            continue
        cleaned.append(tuple(item))

    final_score: list[tuple] = []
    for item in cleaned:
        if int(item[0]) != 0 and get_event_duration(item) < MIN_NOTE_MS:
            current_duration_ms = get_event_duration(item)
            patched = list(item)
            set_event_duration(patched, get_target_short_note_duration(current_duration_ms))
            final_score.append(tuple(patched))
        else:
            final_score.append(item)

    return merge_score_rests(final_score)


MIN_MECHANICAL_GAP_MS = 60 # Minimum time for a motor to return and reset

def apply_mechanical_gaps(score: list[tuple]) -> list[tuple]:
    """
    Refine repeated-note tails from the next same-pitch onset instead of blunt cutting.
    """
    if not score:
        return []
        
    # First, calculate absolute start times for all events
    timeline: list[dict] = []
    current_time = 0
    for item in score:
        kind = item[0]
        duration = 0
        pitches = []
        
        if kind == 0:
            duration = int(item[1])
        elif kind == 1:
            duration = int(item[2])
            pitches = [int(item[1])]
        elif kind == 3:
            duration = int(item[2])
            pitches = [int(p) for p in item[1]]
        elif kind == 4:
            duration = int(item[2])
            pitches = [int(p) for p in item[1]]
        elif kind == 10:
            duration = int(item[3])
            pitches = [int(item[2])]
        elif kind in (11, 12):
            duration = int(item[3])
            pitches = [int(p) for p in item[2]]
            
        timeline.append({
            "item": item,
            "start": current_time,
            "duration": duration,
            "pitches": pitches,
            "end": current_time + duration
        })
        current_time += duration
        
    # For each pitch, infer a natural release point from the next same-pitch onset.
    by_pitch: dict[int, list[int]] = {}
    for index, event in enumerate(timeline):
        for pitch in event["pitches"]:
            by_pitch.setdefault(int(pitch), []).append(index)

    for pitch_indexes in by_pitch.values():
        ordered = sorted(pitch_indexes, key=lambda idx: (timeline[idx]["start"], timeline[idx]["end"]))
        for order, current_index in enumerate(ordered[:-1]):
            next_index = ordered[order + 1]
            current = timeline[current_index]
            following = timeline[next_index]

            onset_gap_ms = int(following["start"] - current["start"])
            if onset_gap_ms <= MIN_NOTE_MS:
                continue

            previous_gap_ms = 0
            if order > 0:
                previous = timeline[ordered[order - 1]]
                previous_gap_ms = int(current["start"] - previous["start"])

            local_gaps = [gap for gap in (previous_gap_ms, onset_gap_ms) if gap > 0]
            local_gap_ms = min(local_gaps) if local_gaps else onset_gap_ms
            current_duration_ms = int(current["duration"])
            next_duration_ms = int(following["duration"])

            adaptive_release_ms = quantize_ms(
                int(round(max(
                    REPEAT_RELEASE_MIN_MS,
                    min(
                        REPEAT_RELEASE_MAX_MS,
                        local_gap_ms * REPEAT_RELEASE_RATIO,
                        max(current_duration_ms, next_duration_ms) * 0.22,
                    ),
                ))),
                minimum=REPEAT_RELEASE_MIN_MS,
                maximum=REPEAT_RELEASE_MAX_MS,
            )

            natural_duration_ms = max(MIN_NOTE_MS, onset_gap_ms - adaptive_release_ms)
            required_release_start = following["start"] - adaptive_release_ms

            if current_duration_ms <= natural_duration_ms + REPEAT_RELEASE_TOLERANCE_MS:
                continue
            if current["end"] <= required_release_start + REPEAT_RELEASE_TOLERANCE_MS:
                continue

            current["duration"] = natural_duration_ms
            current["end"] = current["start"] + natural_duration_ms

    # Re-construct the quantized score with correct rests
    new_score = []
    last_time = 0
    for event in timeline:
        # If we truncated a note, we must add a rest before the next event
        # to maintain the original start time of the next event.
        gap_before = event["start"] - last_time
        if gap_before > 0:
            new_score.append((0, gap_before))
            
        item = list(event["item"])
        # Update the duration in the original item tuple
        if item[0] == 0:
            item[1] = event["duration"]
        elif item[0] in (1, 3):
            item[2] = event["duration"]
        elif item[0] == 4:
            item[2] = event["duration"]
        elif item[0] in (10, 11):
            item[3] = event["duration"]
        elif item[0] == 12:
            item[3] = event["duration"]
            
        new_score.append(tuple(item))
        last_time = event["end"]

    # Add final rest if needed (though usually not necessary)
    if last_time < current_time:
        new_score.append((0, current_time - last_time))
        
    return merge_score_rests(new_score)


def normalize_score(score: Iterable[tuple]) -> list[tuple]:
    normalized: list[tuple] = []

    for raw_item in score:
        if not isinstance(raw_item, (list, tuple)) or not raw_item:
            continue

        kind = int(raw_item[0])
        if kind == 0 and len(raw_item) >= 2:
            rest_ms = quantize_ms(int(raw_item[1]), minimum=REST_MS, maximum=MAX_NOTE_MS)
            normalized.append((0, rest_ms))
            continue

        if kind == 1 and len(raw_item) >= 3:
            pitch = parse_pitch_token(raw_item[1])
            duration_ms = quantize_ms(int(raw_item[2]), minimum=0, maximum=MAX_NOTE_MS)
            normalized.append((1, pitch, duration_ms))
            continue

        if kind == 3 and len(raw_item) >= 3:
            pitches = choose_chord_pitches(parse_pitch_collection(raw_item[1]))
            if not pitches:
                continue
            duration_ms = quantize_ms(int(raw_item[2]), minimum=0, maximum=MAX_NOTE_MS)
            normalized.append((3, pitches, duration_ms))
            continue

        if kind == 4 and len(raw_item) >= 4:
            original_pitches = parse_pitch_collection(raw_item[1])
            ordered_unique_pitches: list[int] = []
            for pitch in original_pitches:
                current_pitch = parse_pitch_token(pitch)
                if current_pitch not in ordered_unique_pitches:
                    ordered_unique_pitches.append(current_pitch)
            pitches = ordered_unique_pitches[:MAX_CHORD_NOTES]
            if not pitches:
                continue

            duration_ms = quantize_ms(int(raw_item[2]), minimum=0, maximum=MAX_NOTE_MS)
            
            if isinstance(raw_item[3], (list, tuple)):
                offsets_ms = normalize_arp_offsets(raw_item[3], len(pitches))
            else:
                spread_ms = quantize_ms(
                    int(raw_item[3]),
                    minimum=MIN_ARP_SPREAD_MS,
                    maximum=MAX_ARP_SPREAD_MS,
                )
                offsets_ms = [index * spread_ms for index in range(len(pitches))]
            
            release_ms = quantize_ms(
                int(raw_item[4]) if len(raw_item) >= 5 and not isinstance(raw_item[4], (list, tuple)) else max(
                    MIN_ARP_RELEASE_MS,
                    min(MAX_ARP_RELEASE_MS, (offsets_ms[-1] // max(1, len(pitches) - 1)) if len(pitches) >= 2 else MIN_ARP_RELEASE_MS),
                ),
                minimum=MIN_ARP_RELEASE_MS,
                maximum=MAX_ARP_RELEASE_MS,
            )

            normalized.append((4, pitches, duration_ms, offsets_ms, release_ms))
            continue

        if kind in (10, 11, 12) and len(raw_item) >= 4:
            hand = str(raw_item[1]).upper()
            hand = HAND_LEFT if hand.startswith("L") else HAND_RIGHT
            if kind == 10:
                pitches = [parse_pitch_token(raw_item[2])]
            elif kind == 12:
                ordered_unique_pitches: list[int] = []
                for pitch in parse_pitch_collection(raw_item[2]):
                    current_pitch = parse_pitch_token(pitch)
                    if current_pitch not in ordered_unique_pitches:
                        ordered_unique_pitches.append(current_pitch)
                pitches = ordered_unique_pitches[:MAX_CHORD_NOTES]
            else:
                pitches = choose_chord_pitches(parse_pitch_collection(raw_item[2]))
            if not pitches:
                continue

            duration_ms = quantize_ms(int(raw_item[3]), minimum=0, maximum=MAX_NOTE_MS)
            if kind == 10 and len(pitches) == 1:
                normalized.append((10, hand, pitches[0], duration_ms))
            elif kind == 11:
                normalized.append((11, hand, pitches, duration_ms))
            else:
                if len(raw_item) >= 5 and isinstance(raw_item[4], (list, tuple)):
                    offsets_ms = normalize_arp_offsets(raw_item[4], len(pitches))
                else:
                    spread_ms = quantize_ms(
                        int(raw_item[4]) if len(raw_item) >= 5 else MIN_ARP_SPREAD_MS,
                        minimum=MIN_ARP_SPREAD_MS,
                        maximum=MAX_ARP_SPREAD_MS,
                    )
                    offsets_ms = [index * spread_ms for index in range(len(pitches))]
                release_ms = quantize_ms(
                    int(raw_item[5]) if len(raw_item) >= 6 else max(
                        MIN_ARP_RELEASE_MS,
                        min(MAX_ARP_RELEASE_MS, (offsets_ms[-1] // max(1, len(pitches) - 1)) if len(pitches) >= 2 else MIN_ARP_RELEASE_MS),
                    ),
                    minimum=MIN_ARP_RELEASE_MS,
                    maximum=MAX_ARP_RELEASE_MS,
                )
                normalized.append((12, hand, pitches, duration_ms, offsets_ms, release_ms))

    return apply_mechanical_gaps(stretch_short_notes(normalized))


def pitches_to_code_text(pitches: Iterable[int]) -> str:
    return " ".join(midi_to_note_name(int(pitch)) for pitch in pitches)


def score_to_code(score: Iterable[tuple], song_name: str, esp32_lines: Iterable[str] | None = None) -> str:
    cached_lines = [str(line).strip() for line in esp32_lines] if esp32_lines is not None else None
    lines = [
        f"# song: {song_name}",
        "# shorthand: r=rest n=note c=chord a=arp ln/rn/lc/rc/la/ra=left-right-hand",
        "from playback.project_score_tools import r, n, c, a, ln, rn, lc, rc, la, ra",
        "",
        "SCORE = [",
    ]

    for item in score:
        if item[0] == 0:
            lines.append(f"    r({int(item[1])}),")
        elif item[0] == 1:
            lines.append(f"    n({midi_to_note_name(int(item[1]))!r}, {int(item[2])}),")
        elif item[0] == 4:
            lines.append(
                f"    a({pitches_to_code_text(item[1])!r}, {int(item[2])}, {[int(offset) for offset in item[3]]}, {int(item[4])}),"
            )
        elif item[0] == 10:
            helper = "ln" if str(item[1]).upper().startswith("L") else "rn"
            lines.append(f"    {helper}({midi_to_note_name(int(item[2]))!r}, {int(item[3])}),")
        elif item[0] == 11:
            helper = "lc" if str(item[1]).upper().startswith("L") else "rc"
            lines.append(f"    {helper}({pitches_to_code_text(item[2])!r}, {int(item[3])}),")
        elif item[0] == 12:
            helper = "la" if str(item[1]).upper().startswith("L") else "ra"
            lines.append(
                f"    {helper}({pitches_to_code_text(item[2])!r}, {int(item[3])}, {[int(offset) for offset in item[4]]}, {int(item[5])}),"
            )
        else:
            lines.append(f"    c({pitches_to_code_text(item[1])!r}, {int(item[2])}),")

    lines.append("]")
    if cached_lines is not None:
        lines.append("")
        lines.append("ESP32_LINES = [")
        for line in cached_lines:
            lines.append(f"    {line!r},")
        lines.append("]")
    lines.append("")
    return "\n".join(lines)


def score_to_esp32_lines(score: Iterable[tuple]) -> list[str]:
    lines: list[str] = []
    for item in score:
        if item[0] == 0:
            lines.append(f"0,{int(item[1])}")
        elif item[0] == 1:
            lines.append(f"{int(item[1])},{int(item[2])}")
        elif item[0] == 4:
            notes = "+".join(str(int(pitch)) for pitch in item[1])
            offsets = "+".join(str(int(offset)) for offset in item[3])
            lines.append(f"ARP,{notes},{int(item[2])},{offsets},{int(item[4])}")
        elif item[0] == 10:
            lines.append(f"{item[1]}:NOTE,{int(item[2])},{int(item[3])}")
        elif item[0] == 11:
            notes = "+".join(str(int(pitch)) for pitch in item[2])
            lines.append(f"{item[1]}:CHORD,{notes},{int(item[3])}")
        elif item[0] == 12:
            notes = "+".join(str(int(pitch)) for pitch in item[2])
            offsets = "+".join(str(int(offset)) for offset in item[4])
            lines.append(f"{item[1]}:ARP,{notes},{int(item[3])},{offsets},{int(item[5])}")
        else:
            notes = "+".join(str(int(pitch)) for pitch in item[1])
            lines.append(f"{notes},{int(item[2])}")
    return lines
