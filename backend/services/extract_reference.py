"""
extract_reference.py — REAL MEDIAPIPE FACEMESH (legacy solutions API, bundled model)

Uses mediapipe.solutions.face_mesh, which ships its own model binaries inside
the pip wheel (no internet download required at runtime).

requirements.txt pins: mediapipe==0.10.13  (last version with bundled solutions API)

The pose formula here is IDENTICAL to the one used in the frontend's
usePoseTracker.js (computePoseFromLandmarks), guaranteeing both sides of the
comparison operate in the same coordinate system:

    yaw   = (nose.x - eye_mid_x) / eye_span
    pitch = (nose.y - eye_mid_y) / face_height
    roll  = atan2(right_eye.y - left_eye.y, right_eye.x - left_eye.x)

Landmark indices (standard 468-point MediaPipe FaceMesh):
    nose_tip = 1, left_eye_outer = 33, right_eye_outer = 263,
    chin = 152, forehead = 10

Usage:
    python services/extract_reference.py --video reference/teacher.mp4 --output reference/reference.json
"""

import cv2
import numpy as np
import json
import argparse
import os


def compute_pose(lm):
    """Same math as frontend computePoseFromLandmarks()."""
    nose, leftE, rightE, chin, forehead = lm[1], lm[33], lm[263], lm[152], lm[10]

    eye_mid_x = (leftE.x + rightE.x) / 2
    eye_span  = abs(rightE.x - leftE.x) or 0.001
    yaw = (nose.x - eye_mid_x) / eye_span

    eye_mid_y = (leftE.y + rightE.y) / 2
    face_h    = abs(chin.y - forehead.y) or 0.001
    pitch = (nose.y - eye_mid_y) / face_h

    dx, dy = rightE.x - leftE.x, rightE.y - leftE.y
    roll = float(np.arctan2(dy, dx))

    return {
        'yaw':   round(float(yaw), 6),
        'pitch': round(float(pitch), 6),
        'roll':  round(float(roll), 6),
    }


def extract_reference(video_path: str, output_path: str, sample_rate: int = 6) -> dict:
    import mediapipe as mp
    mp_face_mesh = mp.solutions.face_mesh

    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")

    cap = cv2.VideoCapture(video_path)
    fps   = cap.get(cv2.CAP_PROP_FPS)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    W     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = total / fps
    step  = max(1, int(fps / sample_rate))

    print(f"[extract_reference] Video: {W}x{H} @ {fps:.1f}fps | {total} frames | {duration:.2f}s")
    print(f"[extract_reference] Sampling every {step} frames (~{sample_rate}/sec)")

    sequence = []
    detected = 0
    sampled  = 0

    with mp_face_mesh.FaceMesh(
        static_image_mode=True,     # treat each sampled frame independently (best accuracy)
        max_num_faces=1,
        refine_landmarks=False,
        min_detection_confidence=0.4,
    ) as fm:
        for fi in range(0, total, step):
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
            ret, frame = cap.read()
            if not ret:
                continue
            sampled += 1

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = fm.process(rgb)
            if not results.multi_face_landmarks:
                continue
            detected += 1

            lm = results.multi_face_landmarks[0].landmark
            pose = compute_pose(lm)

            sequence.append({
                'frame': fi,
                'time':  round(fi / fps, 4),
                **pose,
            })

    cap.release()
    print(f"[extract_reference] Face detected in {detected}/{sampled} sampled frames")

    if len(sequence) == 0:
        raise RuntimeError("No face detected in any sampled frame. Check video quality/lighting.")

    return _finalize(sequence, fps, total, duration, sample_rate, output_path)


def _finalize(sequence, fps, total, duration, sample_rate, output_path):
    yaws    = [s['yaw']   for s in sequence]
    pitches = [s['pitch'] for s in sequence]
    rolls   = [s['roll']  for s in sequence]

    stats = {
        'yaw_mean':   round(float(np.mean(yaws)), 4),    'yaw_std':   round(float(np.std(yaws)), 4),
        'yaw_min':    round(float(np.min(yaws)), 4),      'yaw_max':   round(float(np.max(yaws)), 4),
        'pitch_mean': round(float(np.mean(pitches)), 4),  'pitch_std': round(float(np.std(pitches)), 4),
        'pitch_min':  round(float(np.min(pitches)), 4),   'pitch_max': round(float(np.max(pitches)), 4),
        'roll_mean':  round(float(np.mean(rolls)), 4),    'roll_std':  round(float(np.std(rolls)), 4),
        'roll_min':   round(float(np.min(rolls)), 4),     'roll_max':  round(float(np.max(rolls)), 4),
    }

    print(f"[extract_reference] Extracted {len(sequence)} frames")
    print(f"  Yaw  : {stats['yaw_min']:.4f} → {stats['yaw_max']:.4f}  std={stats['yaw_std']:.4f}")
    print(f"  Pitch: {stats['pitch_min']:.4f} → {stats['pitch_max']:.4f}  std={stats['pitch_std']:.4f}")
    print(f"  Roll : {stats['roll_min']:.4f} → {stats['roll_max']:.4f}  std={stats['roll_std']:.4f}")

    reference = {
        'fps': fps,
        'sample_rate': sample_rate,
        'total_frames': total,
        'duration': round(duration, 2),
        'movements': 3,
        'extraction_method': 'mediapipe_facemesh_solutions_api',
        'coordinate_system': 'mediapipe_normalized',
        'signal_stats': stats,
        'sequence': sequence,
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(reference, f, indent=2)
    print(f"[extract_reference] Saved → {output_path}")
    return reference


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--video',  default='reference/up-down.mp4')
    parser.add_argument('--output', default='reference/reference.json')
    parser.add_argument('--rate',   type=int, default=6)
    args = parser.parse_args()
    extract_reference(args.video, args.output, args.rate)
