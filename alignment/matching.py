"""Monotone onset-sequence alignment followed by one-to-one chord assignment.

The sequence cost deliberately excludes absolute time: a compressed measure
must not push all subsequent notes outside a fixed timestamp window.
"""

from collections import Counter

import numpy as np
from scipy.optimize import linear_sum_assignment


def onset_groups(notes, window):
    groups = []
    for note in notes:
        if not groups or note['onset'] - groups[-1]['onset'] > window:
            groups.append({'onset': note['onset'], 'notes': []})
        groups[-1]['notes'].append(note)
    for group in groups:
        group['pitches'] = Counter(n['pitch'] for n in group['notes'])
    return groups


def sequence_alignment(score, played, maximum_cells):
    n, m = len(score), len(played)
    if (n + 1) * (m + 1) > maximum_cells:
        raise ValueError('Excerpt too long for alignment; select a shorter passage or raise maximum_alignment_cells.')
    # Rolling cost rows and one byte of traceback per cell.
    trace = np.zeros((n + 1, m + 1), dtype=np.uint8)
    trace[0, 1:] = 2
    trace[1:, 0] = 1
    previous = np.arange(m + 1, dtype=float) * 0.9
    for i, s in enumerate(score, 1):
        current = np.empty(m + 1)
        current[0] = i * 0.9
        for j, p in enumerate(played, 1):
            overlap = sum((s['pitches'] & p['pitches']).values())
            total = sum(s['pitches'].values()) + sum(p['pitches'].values())
            substitution = 1.35 * (1 - 2 * overlap / total)
            choices = (previous[j - 1] + substitution,
                       previous[j] + 0.9, current[j - 1] + 0.9)
            step = min(range(3), key=choices.__getitem__)
            current[j], trace[i, j] = choices[step], step
        previous = current
    cost = float(previous[m])
    pairs, i, j = [], n, m
    while i or j:
        step = trace[i, j]
        if step == 0:
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif step == 1:
            pairs.append((i - 1, None))
            i -= 1
        else:
            pairs.append((None, j - 1))
            j -= 1
    return list(reversed(pairs)), cost


def assign_chord(score_notes, played_notes):
    """Exact pitch dominates; dummy nodes permit missing/extra notes.

    A pitch more than an octave away is reported as missing + extra rather
    than asserting an implausible substitution. These costs are heuristics.
    """
    n, m = len(score_notes), len(played_notes)
    if max(n, m) > 256:
        raise ValueError('An onset group contains more than 256 notes; check the input or chord window.')
    if not n:
        return [(None, p) for p in played_notes]
    if not m:
        return [(s, None) for s in score_notes]
    costs = np.zeros((n + m, n + m))
    costs[:n, m:] = 1.0
    costs[n:, :m] = 1.0
    for i, s in enumerate(score_notes):
        for j, p in enumerate(played_notes):
            distance = abs(s['pitch'] - p['pitch'])
            costs[i, j] = 0 if distance == 0 else 1 + distance / 12
    rows, cols = linear_sum_assignment(costs)
    result = []
    for i, j in zip(rows, cols):
        if i < n or j < m:
            result.append((score_notes[i] if i < n else None,
                           played_notes[j] if j < m else None))
    return result
