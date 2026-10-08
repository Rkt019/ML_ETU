"""
extract_beats.py — MUSIC BEATS FROM A TEACHER VIDEO (librosa)

One-time offline step, like extract_reference.py. Decodes the video's audio
with ffmpeg, finds the tempo and beat times with librosa, and writes a small
JSON the backend loads at startup to score rhythm.

Output:
    {
      "tempo_bpm":   136.0,
      "beat_period": 0.441,           seconds between beats
      "beats":       [0.51, 0.93, ...] seconds from the start of the video
      "onsets":      [...]             every detected note / drum hit
    }

Needs (offline only, not on the server):
    sudo apt install ffmpeg
    venv/bin/pip install librosa==0.10.2.post1     (keeps numpy at 1.26.4)

Usage:
    python services/extract_beats.py                       # both head videos
    python services/extract_beats.py --video reference/up-down.mp4 --output reference/up-down_beats.json
"""

import argparse
import json
import os
import subprocess

import numpy as np

SAMPLE_RATE = 22050

DEFAULT_JOBS = [
    ('reference/up-down.mp4',    'reference/up-down_beats.json'),
    ('reference/right-left.mp4', 'reference/right-left_beats.json'),
]


def load_audio(video_path, sr=SAMPLE_RATE):
    """Mono float32 samples of the video's soundtrack, decoded by ffmpeg."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")
    cmd = ['ffmpeg', '-v', 'error', '-i', video_path, '-vn', '-ac', '1', '-ar', str(sr), '-f', 'f32le', '-']
    try:
        raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    except FileNotFoundError:
        raise RuntimeError("ffmpeg is not installed. Run: sudo apt install ffmpeg")
    samples = np.frombuffer(raw, dtype=np.float32)
    if samples.size == 0:
        raise RuntimeError(f"No audio track found in {video_path}")
    return samples, sr


def extract_beats(video_path, output_path):
    import librosa

    y, sr = load_audio(video_path)
    duration = len(y) / sr

    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    tempo, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
    beats = librosa.frames_to_time(beat_frames, sr=sr)
    onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, units='time')

    tempo = float(np.atleast_1d(tempo)[0])
    beat_period = float(np.median(np.diff(beats))) if len(beats) > 1 else 60.0 / tempo

    data = {
        'source_video':      video_path,
        'duration':          round(duration, 3),
        'tempo_bpm':         round(tempo, 1),
        'beat_period':       round(beat_period, 3),
        'beats':             [round(float(b), 3) for b in beats],
        'onsets':            [round(float(o), 3) for o in onsets],
        'extraction_method': 'librosa_beat_track',
        'librosa_version':   librosa.__version__,
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"[extract_beats] {video_path}: {duration:.1f}s | {tempo:.1f} BPM | "
          f"beat every {beat_period:.3f}s | {len(beats)} beats | {len(onsets)} onsets")
    print(f"[extract_beats] Saved → {output_path}")
    return data


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--video')
    parser.add_argument('--output')
    args = parser.parse_args()

    if args.video:
        out = args.output or os.path.splitext(args.video)[0] + '_beats.json'
        extract_beats(args.video, out)
    else:
        for video, out in DEFAULT_JOBS:
            extract_beats(video, out)
