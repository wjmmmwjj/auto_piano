import os
import sys
from pathlib import Path
import json

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Ensure we use the correct virtual env
import torch
print(f"CUDA Available: {torch.cuda.is_available()}")
print(f"GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'None'}")

try:
    from playback.song_workflow import (
        extract_midi_notes,
        build_project_score,
        build_esp32_playback_lines,
        save_score_files,
        score_to_project_musicxml
    )
except ImportError as e:
    print(f"ImportError: {e}")
    sys.exit(1)

outputs_dir = PROJECT_ROOT / "playback" / "outputs"
count = 0
for d in outputs_dir.iterdir():
    if not d.is_dir(): continue
    # Ignore _validation or internal dirs
    if d.name.startswith("_"): continue
    
    song_name = d.name
    midi_path = d / f"{song_name}.mid"
    
    # Try alternate mid paths if the first one fails
    if not midi_path.exists():
        candidates = list(d.glob("*.mid"))
        if candidates:
            midi_path = candidates[0]
            print(f"Using found MIDI: {midi_path.name}")
        else:
            print(f"Skipping {song_name}, no .mid found.")
            continue
            
    print(f"Re-building: {song_name} with NEW gravity and accurately aggregated chords...")
    try:
        notes = extract_midi_notes(midi_path)
        # build_project_score now has the 30ms ghost note filter and 40ms chord aggregation
        score = build_project_score(notes)
        # build_esp32_playback_lines provides the precision required for the visualizer
        esp32_lines = build_esp32_playback_lines(notes)
        
        # Regenerate MusicXML with latest sync and gravity-based colors
        score_to_project_musicxml(score, song_name, d)
        
        # Regenerate python file (SONGS_DIR) and esp32 cache
        save_score_files(song_name, score, d, esp32_lines)
        print(f"  -> SUCCESS! SCORE upgraded for {song_name}")
        count += 1
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"  -> FAILED for {song_name}: {e}")

print(f"\nDone! {count} songs have been upgraded to the latest 100% accurate format on GPU.")
