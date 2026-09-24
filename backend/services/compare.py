import numpy as np
from typing import List, Dict, Optional


def _smooth(values: List[float], window: int = 3) -> np.ndarray:
    arr = np.array(values, dtype=float)
    if len(arr) < window:
        return arr
    kernel = np.ones(window) / window
    padded = np.pad(arr, (window // 2, window // 2), mode='edge')
    return np.convolve(padded, kernel, mode='valid')


def _velocity(arr: np.ndarray) -> np.ndarray:
    if len(arr) < 2:
        return np.zeros_like(arr)
    return np.diff(arr, prepend=arr[0])


def _extract_signal(seq: List[Dict], axis: str) -> np.ndarray:
    vals = np.array([s[axis] for s in seq], dtype=float)
    vals = _smooth(vals, window=3)
    return vals - np.mean(vals)


def _find_peaks(signal: np.ndarray, min_amplitude: float = None) -> List[Dict]:
    if len(signal) < 3:
        return []

    max_amp = max(abs(signal.max()), abs(signal.min()))
    if max_amp < 0.001:
        return []

    if min_amplitude is None:
        min_amplitude = max_amp * 0.2

    peaks = []
    n = len(signal)
    for i in range(1, n - 1):
        v = signal[i]
        if abs(v) < min_amplitude:
            continue
        if abs(v) >= abs(signal[i-1]) and abs(v) >= abs(signal[i+1]):
            peaks.append({
                'idx':       i,
                'value':     float(v),
                'direction': 'positive' if v > 0 else 'negative',
                'amplitude': float(abs(v)),
            })

    if len(peaks) <= 1:
        return peaks
    merged = [peaks[0]]
    for p in peaks[1:]:
        if p['idx'] - merged[-1]['idx'] < 2:
            if p['amplitude'] > merged[-1]['amplitude']:
                merged[-1] = p
        else:
            merged.append(p)
    return merged


def _build_movement_template(peaks: List[Dict]) -> Dict[str, Dict]:
    template = {}
    for p in peaks:
        d = p['direction']
        if d not in template:
            template[d] = {'amplitudes': []}
        template[d]['amplitudes'].append(p['amplitude'])

    for d, t in template.items():
        amps = t['amplitudes']
        t['mean_amplitude'] = float(np.mean(amps))
        t['min_amplitude']  = float(np.min(amps))
        t['max_amplitude']  = float(np.max(amps))
        t['std_amplitude']  = float(np.std(amps)) if len(amps) > 1 else 0.0
        t['repetitions']    = len(amps)
        del t['amplitudes']

    return template


def _score_student_attempt(stu_peak: Dict, tmpl: Dict) -> tuple:
    target = tmpl['mean_amplitude']
    tol    = max(tmpl['std_amplitude'], target * 0.15)

    diff = abs(stu_peak['amplitude'] - target)
    if diff <= tol:
        ratio = 1.0 - (diff / tol) * 0.1
        match_type = 'match'
    elif stu_peak['amplitude'] > target:
        excess_ratio = stu_peak['amplitude'] / target if target else 0.0
        ratio = 1.0 - (excess_ratio - 1.0) * 0.4
        match_type = 'overshoot'
    else:
        ratio = (stu_peak['amplitude'] / target) if target else 0.0
        ratio = ratio * 0.9
        match_type = 'undershoot'

    ratio = max(0.0, min(1.0, ratio))
    return round(ratio * 100, 1), match_type


def _check_movement_order(ref_peaks: List[Dict], stu_peaks: List[Dict]) -> float:
    if len(ref_peaks) < 2 or len(stu_peaks) < 2:
        return 1.0

    ref_first_idx = {}
    for p in ref_peaks:
        if p['direction'] not in ref_first_idx:
            ref_first_idx[p['direction']] = p['idx']

    stu_first_idx = {}
    for p in stu_peaks:
        if p['direction'] not in stu_first_idx:
            stu_first_idx[p['direction']] = p['idx']

    types = list(ref_first_idx.keys())
    if len(types) < 2:
        return 1.0

    agreements = 0
    total = 0
    for i in range(len(types)):
        for j in range(i + 1, len(types)):
            t1, t2 = types[i], types[j]
            if t1 not in stu_first_idx or t2 not in stu_first_idx:
                continue
            ref_order = ref_first_idx[t1] < ref_first_idx[t2]
            stu_order = stu_first_idx[t1] < stu_first_idx[t2]
            total += 1
            if ref_order == stu_order:
                agreements += 1

    if total == 0:
        return 1.0

    agreement_ratio = agreements / total
    if agreement_ratio >= 0.99:
        return 1.0
    elif agreement_ratio <= 0.01:
        return 0.1
    else:
        return round(0.1 + agreement_ratio * 0.9, 3)


PRIMARY_AXIS = {
    'up-down':    'pitch',
    'right-left': 'yaw',
}


def _valley_index(signal: np.ndarray, i: int, j: int) -> int:
    if j <= i:
        return i
    segment = signal[i:j + 1]
    return i + int(np.argmin(np.abs(segment)))


def align_student_start(
    reference: List[Dict],
    student:   List[Dict],
    video_type: Optional[str],
) -> Dict:
    axis = PRIMARY_AXIS.get(video_type)
    if axis is None or len(reference) < 3 or len(student) < 3:
        return {'sequence': student, 'skipped_frames': 0, 'false_start_detected': False}

    ref_signal = _extract_signal(reference, axis)
    ref_peaks  = _find_peaks(ref_signal)
    if not ref_peaks:
        return {'sequence': student, 'skipped_frames': 0, 'false_start_detected': False}
    first_ref_dir = ref_peaks[0]['direction']

    stu_signal = _extract_signal(student, axis)
    stu_peaks  = _find_peaks(stu_signal)
    if not stu_peaks:
        return {'sequence': student, 'skipped_frames': 0, 'false_start_detected': False}

    first_stu_peak = stu_peaks[0]
    if first_stu_peak['direction'] == first_ref_dir:
        return {'sequence': student, 'skipped_frames': 0, 'false_start_detected': False}

    matching = next((p for p in stu_peaks if p['direction'] == first_ref_dir), None)
    if matching is None:
        return {'sequence': student, 'skipped_frames': 0, 'false_start_detected': True}

    cut_idx = _valley_index(stu_signal, first_stu_peak['idx'], matching['idx'])
    trimmed = student[cut_idx:]

    if len(trimmed) < 3:
        return {'sequence': student, 'skipped_frames': 0, 'false_start_detected': True}

    return {
        'sequence':             trimmed,
        'skipped_frames':       cut_idx,
        'false_start_detected': True,
    }


def _compare_axis(ref_seq: List[Dict], stu_seq: List[Dict], axis: str) -> Dict:
    ref_signal = _extract_signal(ref_seq, axis)
    stu_signal = _extract_signal(stu_seq, axis)

    ref_amplitude = float(np.std(ref_signal))
    stu_amplitude = float(np.std(stu_signal))

    ref_peaks = _find_peaks(ref_signal)

    if len(ref_peaks) == 0:
        if stu_amplitude < ref_amplitude * 2:
            return {'score': 75.0, 'movements': [], 'note': 'low_motion_axis'}
        else:
            return {'score': 40.0, 'movements': [], 'note': 'student_moved_when_teacher_didnt'}

    template   = _build_movement_template(ref_peaks)
    stu_peaks  = _find_peaks(stu_signal, min_amplitude=ref_amplitude * 0.15)
    order_mult = _check_movement_order(ref_peaks, stu_peaks)

    movements = []
    scores    = []

    for move_type, tmpl in template.items():
        candidates = [p for p in stu_peaks if p['direction'] == move_type]

        if not candidates:
            scores.append(0.0)
            movements.append({
                'movement_type':   move_type,
                'ref_amplitude':   round(tmpl['mean_amplitude'], 4),
                'ref_repetitions': tmpl['repetitions'],
                'stu_amplitude':   0.0,
                'stu_attempts':    0,
                'accuracy':        0.0,
                'found':           False,
                'match_type':      None,
            })
            continue

        best_peak  = None
        best_score = -1.0
        best_match_type = 'undershoot'
        for c in candidates:
            s, match_type = _score_student_attempt(c, tmpl)
            if s > best_score:
                best_score = s
                best_peak  = c
                best_match_type = match_type

        final_score = round(best_score * order_mult, 1)

        note = None
        if best_match_type == 'overshoot' and final_score < 95:
            note = 'overshoot'
        elif best_match_type == 'undershoot' and final_score < 95:
            note = 'undershoot'

        scores.append(final_score)
        movements.append({
            'movement_type':   move_type,
            'ref_amplitude':   round(tmpl['mean_amplitude'], 4),
            'ref_repetitions': tmpl['repetitions'],
            'stu_amplitude':   round(best_peak['amplitude'], 4),
            'stu_attempts':    len(candidates),
            'accuracy':        final_score,
            'found':           final_score > 25.0,
            'match_type':      note,
        })

    axis_score = round(float(np.mean(scores)), 1) if scores else 0.0
    return {
        'score':            axis_score,
        'movements':        movements,
        'note':             'template_matched',
        'order_multiplier': order_mult,
    }


VIDEO_TYPE_WEIGHTS = {
    'right-left': {'yaw': 0.90, 'pitch': 0.05, 'roll': 0.05},
    'up-down':    {'yaw': 0.05, 'pitch': 0.90, 'roll': 0.05},
}
DEFAULT_WEIGHTS = {'yaw': 0.45, 'pitch': 0.40, 'roll': 0.15}


def compare_sequences(
    reference:  List[Dict],
    student:    List[Dict],
    weights:    Optional[Dict[str, float]] = None,
    video_type: Optional[str] = None,
) -> Dict:
    if weights is None:
        weights = VIDEO_TYPE_WEIGHTS.get(video_type, DEFAULT_WEIGHTS)

    if len(reference) == 0 or len(student) == 0:
        return _empty_result('No pose data available.')

    if len(student) < 3:
        return _empty_result(
            f'Only {len(student)} frames captured. Keep your face visible to the camera.'
        )

    align = align_student_start(reference, student, video_type)
    student        = align['sequence']
    skipped_frames = align['skipped_frames']
    false_start     = align['false_start_detected']

    if len(student) < 3:
        return _empty_result(
            'Only movement in the wrong direction was captured. '
            'Please try again, starting the movement the teacher shows first.'
        )

    axis_results     = {}
    movement_details = {}

    for axis in ('yaw', 'pitch', 'roll'):
        result = _compare_axis(reference, student, axis)
        axis_results[axis]     = result['score']
        movement_details[axis] = result['movements']

    pitch_moves = movement_details.get('pitch', [])
    down_move   = next((m for m in pitch_moves if m['movement_type'] == 'positive'), None)
    up_move     = next((m for m in pitch_moves if m['movement_type'] == 'negative'), None)
    down_score  = down_move['accuracy'] if down_move else 0.0
    up_score    = up_move['accuracy']   if up_move   else 0.0

    yaw_moves   = movement_details.get('yaw', [])
    right_move  = next((m for m in yaw_moves if m['movement_type'] == 'positive'), None)
    left_move   = next((m for m in yaw_moves if m['movement_type'] == 'negative'), None)
    right_score = right_move['accuracy'] if right_move else 0.0
    left_score  = left_move['accuracy']  if left_move  else 0.0

    overall = round(
        axis_results['yaw']   * weights['yaw']
        + axis_results['pitch'] * weights['pitch']
        + axis_results['roll']  * weights['roll'],
        1,
    )

    timing_score = round(
        min(len(student), len(reference)) / max(len(student), len(reference)) * 100, 1
    )

    grade = _grade(overall)

    feedback = _generate_feedback(
        axis_results, movement_details, timing_score, len(student),
        video_type=video_type, overall_score=overall, grade=grade,
    )

    return {
        'yaw_score':        axis_results['yaw'],
        'pitch_score':      axis_results['pitch'],
        'roll_score':       axis_results['roll'],
        'up_score':         up_score,
        'down_score':       down_score,
        'right_score':      right_score,
        'left_score':       left_score,
        'overall_score':    overall,
        'timing_score':     timing_score,
        'movement_details': movement_details,
        'feedback':         feedback,
        'grade':            grade,
        'false_start_detected': false_start,
        'skipped_frames':       skipped_frames,
    }


AXIS_LABELS = {
    'yaw':   'Left–right head turns',
    'pitch': 'Up–down head tilts',
    'roll':  'Side head tilts',
}

DIRECTION_LABELS = {
    'yaw':   {'positive': 'right turn',      'negative': 'left turn'},
    'pitch': {'positive': 'downward tilt',   'negative': 'upward tilt'},
    'roll':  {'positive': 'right head tilt', 'negative': 'left head tilt'},
}

def _axis_feedback(axis: str, score: float, movements: List[Dict]) -> List[str]:
    label      = AXIS_LABELS.get(axis, axis)
    dir_labels = DIRECTION_LABELS.get(axis, {})
    lines: List[str] = []

    if not movements:
        if score >= 70:
            lines.append(f'{label}: good overall — {round(score)}% match. ✅')
        else:
            lines.append(f'{label}: try to match the teacher\'s movement more closely ({round(score)}% match).')
        return lines

    missed = [m for m in movements if not m['found']]

    if score >= 80:
        lines.append(f'{label}: excellent! {round(score)}% match. ✅')
    elif score >= 60:
        lines.append(
            f'{label}: good effort — {round(score)}% match. '
            f'A bit more range on each movement will get you closer to perfect.'
        )
    elif score >= 35:
        if missed:
            types = ', '.join(sorted(set(
                dir_labels.get(m['movement_type'], m['movement_type']) for m in missed
            )))
            lines.append(
                f'{label}: you didn\'t attempt the {types} movement — '
                f'watch for that part of the teacher\'s motion and try it ({round(score)}% match overall).'
            )
        else:
            lines.append(
                f'{label}: movement detected but too small — {round(score)}% match. '
                f'Move your head more boldly to match the teacher\'s range.'
            )
    else:
        lines.append(
            f'{label}: needs more practice — {round(score)}% match. '
            f'Mirror the teacher\'s full range of motion on this movement.'
        )

    for m in movements:
        note = m.get('match_type')
        if not note:
            continue
        d_label = dir_labels.get(m['movement_type'], m['movement_type'])
        if note == 'overshoot':
            lines.append(
                f'↳ {d_label.capitalize()}: you went past the teacher\'s range '
                f'({m["accuracy"]}% match) — ease back slightly instead of overshooting.'
            )
        elif note == 'undershoot':
            lines.append(
                f'↳ {d_label.capitalize()}: fell a little short of the teacher\'s range '
                f'({m["accuracy"]}% match) — go a touch further to close the gap.'
            )

    return lines


def _generate_feedback(
    scores, details, timing_score, frame_count,
    video_type: Optional[str] = None,
    overall_score: Optional[float] = None,
    grade: Optional[str] = None,
) -> List[str]:
    feedback: List[str] = []

    primary_axis = PRIMARY_AXIS.get(video_type) or max(scores, key=lambda a: scores[a])
    secondary_axes = [a for a in ('yaw', 'pitch', 'roll') if a != primary_axis]

    if overall_score is not None and grade is not None:
        headline = {
            'Excellent':         f'🏆 Excellent! {overall_score}% match with the teacher.',
            'Good':              f'👍 Good work — {overall_score}% match with the teacher.',
            'Needs Improvement': f'You matched {overall_score}% — a bit more practice will help a lot.',
            'Keep Practicing':   f'You matched {overall_score}% so far — let\'s build this up together.',
        }.get(grade, f'Overall match: {overall_score}%.')
        feedback.append(headline)

    feedback.extend(_axis_feedback(primary_axis, scores.get(primary_axis, 0.0), details.get(primary_axis, [])))

    for axis in secondary_axes:
        moves = details.get(axis, [])
        disruptive = [m for m in moves if m.get('found') and m.get('match_type') == 'overshoot']
        if disruptive:
            feedback.append(
                f'Tip: try to keep your {AXIS_LABELS[axis].lower()} steady while focusing on '
                f'the {AXIS_LABELS[primary_axis].lower()}.'
            )
            break

    if frame_count < 5:
        feedback.append('⚠ Very few frames captured — your face was mostly out of view.')
    elif timing_score < 60:
        feedback.append('Tip: keep your face clearly visible the entire time for better tracking.')

    return feedback


def _grade(score: float) -> str:
    if score >= 80:   return 'Excellent'
    elif score >= 65: return 'Good'
    elif score >= 45: return 'Needs Improvement'
    else:             return 'Keep Practicing'


def _empty_result(msg: str) -> Dict:
    return {
        'yaw_score': 0, 'pitch_score': 0, 'roll_score': 0,
        'up_score': 0, 'down_score': 0,
        'right_score': 0, 'left_score': 0,
        'overall_score': 0, 'timing_score': 0,
        'movement_details': {}, 'feedback': [msg], 'grade': 'Error',
        'false_start_detected': False, 'skipped_frames': 0,
    }
