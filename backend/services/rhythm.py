"""
rhythm.py — is the student moving in time with the music?

The teacher video's music is the shared clock: every student frame carries the
teacher video's playback time, and the teacher's own frames are stamped with
the same video time. A student is "on the beat" when each head movement peaks
at the same music time as the teacher's matching movement.

Comparing against the teacher's movement times (rather than the raw beat
times) matters: the extreme of a head turn naturally lands a little after the
drum hit, and the teacher shows exactly where it should land. The beat
period from extract_beats.py sets how much lateness is forgiven and lets
feedback speak in beats.

Per teacher movement:
    offset = student peak time - teacher peak time   (+ late, - early)
    credit = 1 within ON_BEAT_TOLERANCE, falling to 0 one beat later
    missing movement = 0
rhythm_score = average credit x 100
"""

from typing import Dict, List, Optional

import numpy as np

from services.compare import PRIMARY_AXIS, _extract_signal, _find_peaks

ON_BEAT_TOLERANCE = 0.15   # seconds; about a third of a beat at 136 BPM
LATENCY_ALLOWANCE = 0.10   # seconds of camera + processing delay before a frame is stamped
MIN_PEAK_FRACTION = 0.3    # a student peak must reach 30% of the teacher's amplitude to count
SEARCH_BEATS = 2.0         # look this many beats either side for the matching movement


def _peak_times(seq: List[Dict], axis: str, min_amplitude: Optional[float] = None) -> List[Dict]:
    """Peaks of one head axis, with sub-sample timing from a parabola through each peak."""
    if len(seq) < 3:
        return []
    times = np.array([s['time'] for s in seq], dtype=float)
    signal = _extract_signal(seq, axis)
    peaks = _find_peaks(signal, min_amplitude=min_amplitude)

    out = []
    for p in peaks:
        i, t = p['idx'], times[p['idx']]
        a, b, c = (abs(signal[i - 1]), abs(signal[i]), abs(signal[i + 1])) if 0 < i < len(signal) - 1 else (0, 0, 0)
        denom = a - 2 * b + c
        if denom < 0:
            delta = float(np.clip(0.5 * (a - c) / denom, -0.5, 0.5))
            t += delta * (times[i + 1] - times[i - 1]) / 2
        out.append({'time': float(t), 'direction': p['direction'], 'amplitude': p['amplitude']})
    return out


def rhythm_score(
    reference: List[Dict],
    student: List[Dict],
    video_type: Optional[str],
    beats: Dict,
) -> Optional[Dict]:
    axis = PRIMARY_AXIS.get(video_type)
    if axis is None or not beats:
        return None

    beat_period = float(beats.get('beat_period') or 60.0 / beats['tempo_bpm'])
    visible = [s for s in student if s.get('visible', True)]

    teacher_moves = _peak_times(reference, axis)
    if not teacher_moves or len(visible) < 3:
        return None

    mean_amp = {d: np.mean([m['amplitude'] for m in teacher_moves if m['direction'] == d])
                for d in {m['direction'] for m in teacher_moves}}
    student_moves = _peak_times(visible, axis, min_amplitude=MIN_PEAK_FRACTION * min(mean_amp.values()))
    for m in student_moves:
        m['time'] -= LATENCY_ALLOWANCE

    # A peak only shows up once a frame after it has been captured.
    last_detectable = max(s['time'] for s in visible) - LATENCY_ALLOWANCE - 0.2
    window = SEARCH_BEATS * beat_period
    used = set()
    moves = []
    for tm in teacher_moves:
        if tm['time'] > last_detectable:
            continue  # student stopped before the music reached this movement
        candidates = [
            (abs(sm['time'] - tm['time']), k) for k, sm in enumerate(student_moves)
            if k not in used and sm['direction'] == tm['direction'] and abs(sm['time'] - tm['time']) <= window
        ]
        if not candidates:
            moves.append({'teacher_time': round(tm['time'], 2), 'direction': tm['direction'],
                          'student_time': None, 'offset': None, 'credit': 0.0})
            continue
        _, k = min(candidates)
        used.add(k)
        offset = student_moves[k]['time'] - tm['time']
        credit = float(np.clip(1.0 - max(0.0, abs(offset) - ON_BEAT_TOLERANCE) / beat_period, 0.0, 1.0))
        moves.append({'teacher_time': round(tm['time'], 2), 'direction': tm['direction'],
                      'student_time': round(student_moves[k]['time'], 2),
                      'offset': round(offset, 2), 'credit': round(credit, 2)})

    if not moves:
        return None

    matched = [m for m in moves if m['offset'] is not None]
    on_beat = sum(1 for m in matched if abs(m['offset']) <= ON_BEAT_TOLERANCE)
    mean_offset = float(np.median([m['offset'] for m in matched])) if matched else None
    score = round(100 * float(np.mean([m['credit'] for m in moves])), 1)

    return {
        'rhythm_score':     score,
        'rhythm_offset':    round(mean_offset, 2) if mean_offset is not None else None,
        'rhythm_on_beat':   on_beat,
        'rhythm_total':     len(moves),
        'tempo_bpm':        beats.get('tempo_bpm'),
        'beat_period':      round(beat_period, 3),
        'rhythm_moves':     moves,
        'rhythm_feedback':  _feedback(score, mean_offset, on_beat, len(moves), len(matched), beat_period),
    }


def _feedback(score, mean_offset, on_beat, total, matched, beat_period) -> List[str]:
    if matched == 0:
        return ["🎵 We couldn't match your movements to the music — listen to the beat and move along with it."]

    lines = []
    if score >= 80:
        lines.append(f"🎵 Great rhythm! {on_beat} of {total} movements landed right on the music's beat.")
    elif score >= 50:
        lines.append(f"🎵 Rhythm: you're close — {on_beat} of {total} movements were exactly on the beat.")
    else:
        lines.append(f"🎵 Rhythm: only {on_beat} of {total} movements were on the beat — let the music guide you.")

    if mean_offset is not None and abs(mean_offset) > ON_BEAT_TOLERANCE:
        beats_off = abs(mean_offset) / beat_period
        how_much = ('about half a beat' if beats_off < 0.75
                    else 'about 1 beat' if beats_off < 1.25
                    else f'about {beats_off:.1f} beats')
        if mean_offset > 0:
            lines.append(f"↳ You moved {abs(mean_offset):.2f}s ({how_much}) after the music. "
                         "Move on the beat instead of waiting to copy the teacher.")
        else:
            lines.append(f"↳ You moved {abs(mean_offset):.2f}s ({how_much}) before the music. "
                         "Wait for the beat before each movement.")

    if matched < total:
        lines.append(f"↳ {total - matched} movement(s) were missed — keep moving until the music ends.")
    return lines
