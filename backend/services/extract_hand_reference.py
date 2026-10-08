"""
extract_hand_reference.py — MEDIAPIPE HANDS (legacy solutions API, bundled model)

One-time offline step. Reads a teacher video that shows several hand mudras,
plus a segments file that says which mudra is on screen between which
seconds, and writes:

  1. <output>            every sampled frame of every mudra (full detail,
                         usable later as training data for a sequence model)
  2. <templates output>  one averaged "answer key" per mudra (small file the
                         app can load to compare a student against)

Per sampled frame we store:
  - landmarks_image : 21 x [x, y, z]   MediaPipe image coords (x, y in 0..1)
  - landmarks_world : 21 x [x, y, z]   metres, origin near the hand centre
  - landmarks_norm  : 21 x [x, y, z]   world coords, wrist moved to 0 and
                                       divided by palm size (wrist -> middle
                                       knuckle), so hand size / distance from
                                       the camera does not matter
  - palm            : yaw, pitch, roll in degrees (which way the palm faces)
  - fingers         : bend of each finger, gaps between fingers, thumb pinch

The palm and finger formulas must stay identical to the browser code that
measures the student, otherwise the comparison is unfair.

Landmark indices (21-point MediaPipe hand):
    0 wrist
    1-4  thumb   (cmc, mcp, ip, tip)
    5-8  index   (mcp, pip, dip, tip)
    9-12 middle  13-16 ring  17-20 pinky

Usage:
    python services/extract_hand_reference.py \
        --video reference/Wrist.mp4 \
        --segments reference/asamyuta_hasta_segments.json \
        --output reference/asamyuta_hasta.json \
        --templates reference/asamyuta_hasta_templates.json
"""

import argparse
import json
import os
import re

import cv2
import numpy as np

LANDMARK_NAMES = [
    'wrist',
    'thumb_cmc', 'thumb_mcp', 'thumb_ip', 'thumb_tip',
    'index_mcp', 'index_pip', 'index_dip', 'index_tip',
    'middle_mcp', 'middle_pip', 'middle_dip', 'middle_tip',
    'ring_mcp', 'ring_pip', 'ring_dip', 'ring_tip',
    'pinky_mcp', 'pinky_pip', 'pinky_dip', 'pinky_tip',
]

FINGER_CHAINS = {
    'thumb':  [0, 1, 2, 3, 4],
    'index':  [0, 5, 6, 7, 8],
    'middle': [0, 9, 10, 11, 12],
    'ring':   [0, 13, 14, 15, 16],
    'pinky':  [0, 17, 18, 19, 20],
}

WRIST, INDEX_MCP, MIDDLE_MCP, PINKY_MCP = 0, 5, 9, 17
THUMB_TIP, INDEX_TIP, MIDDLE_TIP = 4, 8, 12

# A frame counts as "holding still" when the normalised hand moved less than
# this (mean landmark displacement, in palm-size units) since the last sample.
HOLD_MOTION_THRESHOLD = 0.06
MIN_HOLD_FRAMES = 3


def _unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v


def _angle_deg(a, b):
    cos = np.dot(_unit(a), _unit(b))
    return float(np.degrees(np.arccos(np.clip(cos, -1.0, 1.0))))


def normalize_landmarks(world):
    """Wrist at origin, scaled so wrist -> middle knuckle = 1."""
    centred = world - world[WRIST]
    palm_size = np.linalg.norm(centred[MIDDLE_MCP]) or 1e-6
    return centred / palm_size


def palm_angles(pts):
    """
    Which way the palm faces, in degrees.
        across = index knuckle - pinky knuckle   (side to side across the palm)
        up     = middle knuckle - wrist          (wrist towards the fingers)
        normal = across x up                     (out of the palm)
    """
    across = _unit(pts[INDEX_MCP] - pts[PINKY_MCP])
    up = _unit(pts[MIDDLE_MCP] - pts[WRIST])
    normal = _unit(np.cross(across, up))

    yaw = np.degrees(np.arctan2(normal[0], -normal[2]))
    pitch = np.degrees(np.arcsin(np.clip(normal[1], -1.0, 1.0)))
    roll = np.degrees(np.arctan2(up[0], -up[1]))
    return {'yaw': round(float(yaw), 1), 'pitch': round(float(pitch), 1), 'roll': round(float(roll), 1)}


def finger_features(pts):
    """
    curl   : total bend of a finger in degrees, summed over its 3 joints starting
             at the knuckle (bigger = folded; never exactly 0 because the
             wrist->knuckle bone fans out from the finger line)
    spread : angle between neighbouring fingers in degrees
    pinch  : fingertip distances in palm-size units (pts must be normalised)
    """
    curl = {}
    for name, chain in FINGER_CHAINS.items():
        bones = [pts[chain[k + 1]] - pts[chain[k]] for k in range(4)]
        curl[name] = round(sum(_angle_deg(bones[k], bones[k + 1]) for k in range(3)), 1)

    def direction(chain):
        return pts[chain[4]] - pts[chain[1]]

    spread = {
        'thumb_index':  round(_angle_deg(direction(FINGER_CHAINS['thumb']), direction(FINGER_CHAINS['index'])), 1),
        'index_middle': round(_angle_deg(direction(FINGER_CHAINS['index']), direction(FINGER_CHAINS['middle'])), 1),
        'middle_ring':  round(_angle_deg(direction(FINGER_CHAINS['middle']), direction(FINGER_CHAINS['ring'])), 1),
        'ring_pinky':   round(_angle_deg(direction(FINGER_CHAINS['ring']), direction(FINGER_CHAINS['pinky'])), 1),
    }

    pinch = {
        'thumb_index':  round(float(np.linalg.norm(pts[THUMB_TIP] - pts[INDEX_TIP])), 3),
        'thumb_middle': round(float(np.linalg.norm(pts[THUMB_TIP] - pts[MIDDLE_TIP])), 3),
    }
    return {'curl': curl, 'spread': spread, 'pinch': pinch}


def _round_points(arr, digits=4):
    return [[round(float(v), digits) for v in p] for p in arr]


def _find_hold(frames):
    """
    Longest run of visible frames where the hand barely moves.
    Returns (start_idx, end_idx) into `frames`, inclusive, or None.
    """
    best, run_start, prev = None, None, None
    for i, f in enumerate(frames):
        if not f['visible']:
            run_start, prev = None, None
            continue
        pts = np.array(f['landmarks_norm'])
        still = prev is not None and float(np.mean(np.linalg.norm(pts - prev, axis=1))) < HOLD_MOTION_THRESHOLD
        if still:
            if run_start is None:
                run_start = i - 1
            if best is None or (i - run_start) > (best[1] - best[0]):
                best = (run_start, i)
        else:
            run_start = None
        prev = pts
    if best and best[1] - best[0] + 1 >= MIN_HOLD_FRAMES:
        return best
    return None


def build_template(segment, frames):
    visible = [f for f in frames if f['visible']]
    if not visible:
        return None

    hold = _find_hold(frames)
    if hold:
        used = [f for f in frames[hold[0]:hold[1] + 1] if f['visible']]
        hold_info = {'start': used[0]['time'], 'end': used[-1]['time'], 'source': 'still_hand'}
    else:
        # No clear still period: fall back to the middle half of the visible frames.
        q = len(visible) // 4
        used = visible[q:len(visible) - q] or visible
        hold_info = {'start': used[0]['time'], 'end': used[-1]['time'], 'source': 'middle_of_segment'}

    norm = np.mean([np.array(f['landmarks_norm']) for f in used], axis=0)
    return {
        'id': segment['id'],
        'name': segment['name'],
        'display': segment['display'],
        'meaning': segment['meaning'],
        'hold': {**hold_info, 'frames_used': len(used)},
        'handedness': max({f['handedness'] for f in used}, key=[f['handedness'] for f in used].count),
        'landmarks_norm': _round_points(norm),
        'palm': palm_angles(norm),
        'fingers': finger_features(norm),
    }


def extract_hand_reference(video_path, segments_path, output_path, templates_path, sample_rate=6):
    import mediapipe as mp

    with open(segments_path) as f:
        segments = json.load(f)['segments']

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise FileNotFoundError(f"Video not found or unreadable: {video_path} (Linux filenames are case-sensitive)")

    fps = cap.get(cv2.CAP_PROP_FPS)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = total / fps
    step = max(1, round(fps / sample_rate))

    print(f"[extract_hand] Video: {W}x{H} @ {fps:.1f}fps | {total} frames | {duration:.1f}s")
    print(f"[extract_hand] Sampling every {step} frames (~{sample_rate}/sec) inside {len(segments)} segments")

    frames_by_segment = {s['id']: [] for s in segments}

    def segment_at(t):
        for s in segments:
            if s['start'] <= t <= s['end']:
                return s
        return None

    with mp.solutions.hands.Hands(
        static_image_mode=False,
        max_num_hands=1,
        model_complexity=1,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    ) as hands:
        fi = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t = fi / fps
            seg = segment_at(t) if fi % step == 0 else None
            fi += 1
            if seg is None:
                continue

            results = hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            record = {'time': round(t, 3), 'frame': fi - 1, 'visible': False}

            if results.multi_hand_landmarks:
                image = np.array([[p.x, p.y, p.z] for p in results.multi_hand_landmarks[0].landmark])
                world = np.array([[p.x, p.y, p.z] for p in results.multi_hand_world_landmarks[0].landmark])
                norm = normalize_landmarks(world)
                cls = results.multi_handedness[0].classification[0]
                record.update({
                    'visible': True,
                    'handedness': cls.label,
                    'confidence': round(float(cls.score), 3),
                    'landmarks_image': _round_points(image),
                    'landmarks_world': _round_points(world),
                    'landmarks_norm': _round_points(norm),
                    'palm': palm_angles(norm),
                    'fingers': finger_features(norm),
                })
            frames_by_segment[seg['id']].append(record)

    cap.release()

    mudras, templates = [], []
    print(f"\n[extract_hand] {'#':>2}  {'mudra':<16} {'frames':>6} {'hand':>5}  hold")
    for seg in segments:
        frames = frames_by_segment[seg['id']]
        template = build_template(seg, frames)
        visible = sum(f['visible'] for f in frames)
        hold = f"{template['hold']['start']:.1f}-{template['hold']['end']:.1f}s ({template['hold']['source']})" if template else 'NO HAND FOUND'
        print(f"[extract_hand] {seg['id']:>2}  {seg['name']:<16} {len(frames):>6} {visible:>5}  {hold}")
        mudras.append({**seg, 'frames_sampled': len(frames), 'frames_with_hand': visible, 'frames': frames})
        if template:
            templates.append(template)

    meta = {
        'source_video': video_path,
        'video': {'fps': fps, 'width': W, 'height': H, 'total_frames': total, 'duration': round(duration, 2)},
        'sample_rate': sample_rate,
        'extraction_method': 'mediapipe_hands_solutions_api',
        'mediapipe_version': mp.__version__,
        'landmark_names': LANDMARK_NAMES,
        'units': {
            'landmarks_image': 'x, y in 0..1 of frame width/height; z relative depth',
            'landmarks_world': 'metres, origin near hand centre',
            'landmarks_norm': 'world coords, wrist = 0, wrist->middle knuckle = 1',
            'palm': 'degrees',
            'fingers.curl': 'degrees, bigger = more folded (a straight finger reads ~25-60, a fist ~200-250)',
            'fingers.spread': 'degrees',
            'fingers.pinch': 'palm-size units',
        },
        'handedness_note': "MediaPipe labels handedness as if the image were mirrored (selfie). "
                           "For a normal, non-mirrored teacher video a right hand is reported as 'Left'.",
    }

    _write_json(output_path, {**meta, 'mudras': mudras})
    _write_json(templates_path, {**meta, 'templates': templates})

    total_frames = sum(m['frames_sampled'] for m in mudras)
    total_visible = sum(m['frames_with_hand'] for m in mudras)
    print(f"\n[extract_hand] Hand detected in {total_visible}/{total_frames} sampled frames")
    print(f"[extract_hand] Templates built for {len(templates)}/{len(segments)} mudras")
    print(f"[extract_hand] Saved → {output_path}")
    print(f"[extract_hand] Saved → {templates_path}")


def _write_json(path, data):
    """Indented JSON, but each [x, y, z] point kept on one line so the file stays readable."""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    text = json.dumps(data, indent=2)
    text = re.sub(r'\[\s+(-?[\d.e-]+),\s+(-?[\d.e-]+),\s+(-?[\d.e-]+)\s+\]', r'[\1, \2, \3]', text)
    with open(path, 'w') as f:
        f.write(text + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--video',     default='reference/Wrist.mp4')
    parser.add_argument('--segments',  default='reference/asamyuta_hasta_segments.json')
    parser.add_argument('--output',    default='reference/asamyuta_hasta.json')
    parser.add_argument('--templates', default='reference/asamyuta_hasta_templates.json')
    parser.add_argument('--rate',      type=int, default=6)
    args = parser.parse_args()
    extract_hand_reference(args.video, args.segments, args.output, args.templates, args.rate)
