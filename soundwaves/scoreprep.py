"""Make the reference playable before alignment.

A piano has one string set per key. When two voices in the score land on the
same pitch at the same instant, the page and the aligner should expect one
attack, not two. The same goes for a note that starts while the same pitch is
still sounding in another voice: the key is already down, so there is no
second attack to hear. Both are kept in the score notes for display purposes
only when they would show as distinct noteheads; for alignment they are merged
into the note that is already sounding.
"""

import copy
from collections import defaultdict


def prepare_reference(reference, *, overlap=True):
    """Return (reference_copy, dropped_ids). Removes unison duplicates and, when
    `overlap` is true, same-pitch notes that begin under a still-sounding note
    of that pitch. The surviving note is extended to cover the dropped one."""
    reference = copy.deepcopy(reference)
    notes = sorted(reference['notes'], key=lambda n: (n['onset'], -n['duration'], n['id']))
    dropped, sounding = set(), {}
    for note in notes:
        current = sounding.get(note['pitch'])
        if current is not None:
            end = current['onset'] + current['duration']
            same_onset = abs(current['onset'] - note['onset']) < 1e-4
            if same_onset or (overlap and note['onset'] < end - 1e-6):
                current['duration'] = max(current['duration'], note['onset'] + note['duration'] - current['onset'])
                dropped.add(note['id'])
                continue
        sounding[note['pitch']] = note
    reference['notes'] = [n for n in reference['notes'] if n['id'] not in dropped]
    for chunk in reference.get('chunks', []):
        chunk['notes'] = [entry for entry in chunk['notes'] if entry['note_id'] not in dropped]
    return reference, dropped
