"""
hand_compare.py — score a student's hand against the Asamyuta Hasta templates

The browser sends raw MediaPipe world landmarks (21 x [x, y, z]) for each
sampled webcam frame. Every feature (finger curl, pinch, spread, palm
direction) is computed here with the exact functions used to build the
templates in extract_hand_reference.py, so teacher and student are measured
the same way.

Score for one frame vs one mudra (0-100):
    40%  hand shape     every finger joint's position, measured in the palm's
                        own frame (so turning the whole hand does not change it)
    30%  finger curl    each finger's bend close to the teacher's
    10%  pinch          thumb-tip distances (matters for touching mudras)
    20%  palm direction which way the palm faces and points

Comparing against all 29 templates and taking the highest score doubles as a
simple nearest-template recogniser ("your hand looks like Pataka").
"""

import json

import numpy as np

from services.extract_hand_reference import (
    FINGER_CHAINS,
    INDEX_MCP,
    MIDDLE_MCP,
    PINKY_MCP,
    WRIST,
    finger_features,
    normalize_landmarks,
    palm_angles,
)

FINGERS = list(FINGER_CHAINS.keys())

WEIGHTS = {'shape': 0.40, 'fingers': 0.30, 'pinch': 0.10, 'orientation': 0.20}

# (tolerance, falloff): differences up to `tolerance` score full marks, then
# the score drops linearly and reaches 0 at tolerance + falloff.
SHAPE_TOL = (0.08, 0.25)        # mean joint distance, palm-size units
CURL_TOL = (15.0, 50.0)         # degrees
PINCH_TOL = (0.10, 0.40)        # palm-size units
ORIENTATION_TOL = (30.0, 60.0)  # degrees between palm axes

# Finger joints and tips; the wrist and knuckles barely move between mudras.
SHAPE_POINTS = [2, 3, 4, 6, 7, 8, 10, 11, 12, 14, 15, 16, 18, 19, 20]

PASS_SCORE = 70.0           # a frame at or above this counts as "holding the mudra"
BEST_WINDOW_SECONDS = 1.0

FINGER_LABELS = {
    'thumb': 'thumb', 'index': 'index finger', 'middle': 'middle finger',
    'ring': 'ring finger', 'pinky': 'little finger',
}


def _unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-9 else v


def _angle_between(a, b):
    return float(np.degrees(np.arccos(np.clip(np.dot(_unit(a), _unit(b)), -1.0, 1.0))))


def _closeness(diff, tol):
    tolerance, falloff = tol
    return float(np.clip(1.0 - max(0.0, diff - tolerance) / falloff, 0.0, 1.0))


def _with_worst(mean_score, finger_scores):
    """Half average, half worst finger: one finger in the wrong place is a different mudra."""
    return 0.5 * mean_score + 0.5 * min(finger_scores)


def _palm_axes(norm):
    across = _unit(norm[INDEX_MCP] - norm[PINKY_MCP])
    up = _unit(norm[MIDDLE_MCP] - norm[WRIST])
    return _unit(np.cross(across, up)), up


def _palm_local(norm):
    """Landmarks re-expressed along the palm's own across / up / normal axes."""
    across = _unit(norm[INDEX_MCP] - norm[PINKY_MCP])
    up = norm[MIDDLE_MCP] - norm[WRIST]
    up = _unit(up - np.dot(up, across) * across)
    normal = np.cross(across, up)
    return norm @ np.stack([across, up, normal]).T


def features_from_norm(norm):
    normal, up = _palm_axes(norm)
    return {
        'norm': norm,
        'local': _palm_local(norm),
        'fingers': finger_features(norm),
        'palm': palm_angles(norm),
        'normal': normal,
        'up': up,
    }


def student_variants(landmarks_world):
    """
    The hand as seen, and its mirror image (x flipped). A left hand is the
    mirror image of a right hand, so scoring both and keeping the better one
    lets the student use either hand. MediaPipe's handedness label is not used:
    the browser and Python versions label the same hand oppositely.
    """
    pts = np.asarray(landmarks_world, dtype=float)
    flipped = pts * np.array([-1.0, 1.0, 1.0])
    return [
        (features_from_norm(normalize_landmarks(pts)), False),
        (features_from_norm(normalize_landmarks(flipped)), True),
    ]


def best_variant(variants, template):
    """(feat, mirrored, score_result) for whichever variant matches the template better."""
    return max(((feat, mirrored, score_against(feat, template)) for feat, mirrored in variants),
               key=lambda v: v[2]['score'])


def score_against(feat, template):
    s, t = feat['fingers'], template['fingers']
    joint_dist = np.linalg.norm(feat['local'] - template['local'], axis=1)
    per_finger_shape = [_closeness(float(np.mean(joint_dist[chain[2:]])), SHAPE_TOL)
                        for chain in FINGER_CHAINS.values()]
    shape = _with_worst(_closeness(float(np.mean(joint_dist[SHAPE_POINTS])), SHAPE_TOL), per_finger_shape)
    fingers = {f: _closeness(abs(s['curl'][f] - t['curl'][f]), CURL_TOL) for f in FINGERS}
    pinch = float(np.mean([_closeness(abs(s['pinch'][k] - t['pinch'][k]), PINCH_TOL) for k in t['pinch']]))
    orientation = (
        _closeness(_angle_between(feat['normal'], template['normal']), ORIENTATION_TOL)
        + _closeness(_angle_between(feat['up'], template['up']), ORIENTATION_TOL)
    ) / 2

    parts = {'shape': shape, 'fingers': _with_worst(float(np.mean(list(fingers.values()))), fingers.values()),
             'pinch': pinch, 'orientation': orientation}
    total = sum(WEIGHTS[k] * parts[k] for k in WEIGHTS)
    return {
        'score': round(100 * total, 1),
        'parts': {k: round(100 * v, 1) for k, v in parts.items()},
        'finger_scores': {f: round(100 * v, 1) for f, v in fingers.items()},
    }


def rank_templates(variants, templates, top=3):
    ranked = sorted(
        ({'name': t['name'], 'display': t['display'], 'score': best_variant(variants, t)[2]['score']}
         for t in templates.values()),
        key=lambda r: r['score'], reverse=True,
    )
    return ranked[:top]


def load_templates(path):
    """Returns {name: template} with palm axes precomputed, or {} if the file is missing."""
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}

    templates = {}
    for t in data['templates']:
        norm = np.asarray(t['landmarks_norm'], dtype=float)
        normal, up = _palm_axes(norm)
        templates[t['name']] = {**t, 'norm': norm, 'local': _palm_local(norm), 'normal': normal, 'up': up}
    return templates


def public_template(t):
    return {k: t[k] for k in ('id', 'name', 'display', 'meaning', 'hold', 'handedness', 'palm', 'fingers')}


def score_frame(frame, template, templates):
    """
    Live score for one webcam frame. `frame` has visible and landmarks_world.
    Also returns the normalised landmarks (mirrored if that matched better)
    so the session can average them later.
    """
    if not frame.get('visible') or not frame.get('landmarks_world'):
        return {'visible': False, 'score': 0.0}, None

    variants = student_variants(frame['landmarks_world'])
    feat, mirrored, result = best_variant(variants, template)
    return {
        'visible': True,
        'mirrored': mirrored,
        **result,
        'palm': feat['palm'],
        'curl': feat['fingers']['curl'],
        'best_matches': rank_templates(variants, templates),
    }, feat['norm']


def summarize_attempt(template, frames, templates, sample_interval):
    """
    frames: [{'time', 'visible', 'score', 'norm' (np.ndarray or None)}]

    The overall score is the best 1 second of the attempt: a student needs a
    moment to form the mudra, so early frames should not drag the score down.
    """
    n = len(frames)
    visible_count = sum(1 for f in frames if f['visible'])
    hand_visible_pct = round(visible_count / n * 100, 1)

    if visible_count == 0:
        return None

    # Windows are measured in seconds, not frames, because a slow device may
    # deliver fewer than 6 samples per second.
    scores = np.array([f['score'] for f in frames], dtype=float)
    times = [f['time'] for f in frames]
    last_start = times[-1] - BEST_WINDOW_SECONDS + sample_interval
    best = None
    for i in range(n):
        if i > 0 and times[i] > last_start:
            break
        j = i
        while j < n and times[j] - times[i] < BEST_WINDOW_SECONDS:
            j += 1
        mean = float(scores[i:j].mean())
        if best is None or mean > best[0]:
            best = (mean, i, j)
    overall = round(best[0], 1)

    window_norms = [f['norm'] for f in frames[best[1]:best[2]] if f['visible']]
    if not window_norms:
        window_norms = [f['norm'] for f in frames if f['visible']]
    feat = features_from_norm(np.mean(window_norms, axis=0))
    breakdown = score_against(feat, template)

    longest, run_start = 0.0, None
    for f in frames:
        if f['visible'] and f['score'] >= PASS_SCORE:
            run_start = f['time'] if run_start is None else run_start
            longest = max(longest, f['time'] - run_start + sample_interval)
        else:
            run_start = None

    grade = _grade(overall)
    best_matches = rank_templates([(feat, False)], templates)
    return {
        'mudra': template['name'],
        'display': template['display'],
        'meaning': template['meaning'],
        'overall_score': overall,
        'grade': grade,
        'hand_visible_pct': hand_visible_pct,
        'hold_seconds': round(longest, 1),
        'parts': breakdown['parts'],
        'finger_scores': breakdown['finger_scores'],
        'student': {'palm': feat['palm'], 'fingers': feat['fingers']},
        'teacher': {'palm': template['palm'], 'fingers': template['fingers']},
        'best_matches': best_matches,
        'frames_captured': n,
        'feedback': _feedback(template, feat, breakdown, overall, grade, hand_visible_pct, best_matches),
    }


def _grade(score):
    if score >= 80:   return 'Excellent'
    elif score >= 65: return 'Good'
    elif score >= 45: return 'Needs Improvement'
    else:             return 'Keep Practicing'


def _feedback(template, feat, breakdown, overall, grade, hand_visible_pct, best_matches):
    name = template['display']
    tips = [{
        'Excellent':         f"🏆 Excellent! Your {name} is a {overall}% match with the teacher.",
        'Good':              f"👍 Good work — your {name} is a {overall}% match.",
        'Needs Improvement': f"Your {name} is a {overall}% match — a little more practice will help.",
        'Keep Practicing':   f"Your {name} is a {overall}% match so far — watch the teacher's hand closely and try again.",
    }[grade]]

    if hand_visible_pct < 60:
        tips.append("✋ Keep your whole hand inside the camera frame so it can be seen clearly.")

    s_curl, t_curl = feat['fingers']['curl'], template['fingers']['curl']
    worst = sorted(FINGERS, key=lambda f: breakdown['finger_scores'][f])[:2]
    for f in worst:
        if breakdown['finger_scores'][f] >= 80:
            continue
        if s_curl[f] > t_curl[f]:
            tips.append(f"Straighten your {FINGER_LABELS[f]} a little more.")
        else:
            tips.append(f"Bend your {FINGER_LABELS[f]} more.")

    s_pinch, t_pinch = feat['fingers']['pinch'], template['fingers']['pinch']
    for key, finger in (('thumb_index', 'index'), ('thumb_middle', 'middle')):
        if t_pinch[key] < 0.35 and s_pinch[key] - t_pinch[key] > 0.15:
            tips.append(f"Bring your thumb tip closer to your {FINGER_LABELS[finger]} tip.")
        elif t_pinch[key] > 0.6 and t_pinch[key] - s_pinch[key] > 0.25:
            tips.append(f"Keep your thumb away from your {FINGER_LABELS[finger]}.")

    if breakdown['parts']['orientation'] < 60:
        tips.append("Turn your hand so your palm faces the same way as the teacher's.")

    if best_matches and best_matches[0]['name'] != template['name'] and overall < 65:
        tips.append(f"Right now your hand looks more like {best_matches[0]['display']}.")

    if len(tips) == 1 and grade in ('Excellent', 'Good'):
        tips.append("Finger shape and palm direction both look right — keep holding it steady.")
    return tips
