"""Render score notation and attach performance matches without changing audio."""

import json
from collections import defaultdict, deque
from importlib.resources import files

import numpy as np
from music21 import pitch

from alignment.inputs import load_performance


def _extra_anchor(extra, report, located, locations, notes, note_by_id):
    """The score note an extra played note should be drawn next to, or None.

    Nearest-in-time alone pins a right-hand slip to a left-hand note that happens to sound
    beside it, so the page shows an extra on the left and a missing note on the right. Prefer,
    in order: (1) the missing score note in this bar that the extra is most likely a wrong
    version of (same key, or a near or octave-off pitch, at about the same beat); (2) the
    nearest played note on the staff whose pitch range fits the extra; (3) the nearest played
    note on any staff."""
    same = [m for m in located if m['measure_occurrence'] == extra['measure_occurrence']
            and m['audio_time'] is not None]
    if not same:
        return None
    nearest = min(same, key=lambda m: abs(m['audio_time'] - extra['audio_time']))
    pitch_ = extra['actual_pitch']
    anchors = report.get('alignment', {}).get('anchors') or []
    beat = None
    if pitch_ is not None and len(anchors) >= 2:
        times = [a['audio_time'] for a in anchors]
        if times[0] <= extra['audio_time'] <= times[-1]:
            beat = float(np.interp(extra['audio_time'], times, [a['score_beat'] for a in anchors]))
    if beat is not None:
        wanted = []
        for m in report['matches']:
            if (m['category'] != 'missing' or m['score_note_id'] not in locations
                    or m['measure_occurrence'] != extra['measure_occurrence'] or m['score_beat'] is None):
                continue
            gap = abs(pitch_ - m['expected_pitch'])
            if (gap <= 2 or (gap <= 26 and gap % 12 in (0, 1, 2, 10, 11))) and abs(m['score_beat'] - beat) <= 0.75:
                wanted.append((abs(m['score_beat'] - beat) + gap / 100, m))
        if wanted:
            return min(wanted, key=lambda w: w[0])[1]
    measure = note_by_id[nearest['score_note_id']]['measure']
    ranges = {}
    for n in notes:
        if n['measure'] == measure:
            low, high = ranges.setdefault(n['part'], [n['pitch'], n['pitch']])
            ranges[n['part']] = [min(low, n['pitch']), max(high, n['pitch'])]
    if pitch_ is not None and len(ranges) > 1:
        part = min(ranges, key=lambda p: (max(ranges[p][0] - pitch_, pitch_ - ranges[p][1], 0),
                                          abs(pitch_ - sum(ranges[p]) / 2)))
        on_staff = [m for m in same if note_by_id[m['score_note_id']]['part'] == part]
        if on_staff:
            return min(on_staff, key=lambda m: abs(m['audio_time'] - extra['audio_time']))
    return nearest


def render_score(musicxml, notes):
    """Engrave the score with Verovio. Returns (toolkit, {score note id: engraved element id})."""
    import verovio

    toolkit = verovio.toolkit(False)
    toolkit.setResourcePath(str(files('verovio') / 'data'))
    toolkit.setOptions(dict(pageWidth=1500, pageHeight=2000, scale=45,
                            adjustPageHeight=True, breaks='auto'))
    if not toolkit.loadFile(str(musicxml)):
        raise ValueError('Could not render the recognized score.')
    toolkit.renderToMIDI()
    by_position = defaultdict(deque)
    for n in notes:
        by_position[(round(n['onset'], 5), n['pitch'])].append(n['id'])
    locations = {}
    for entry in toolkit.renderToTimemap():
        for xml_id in entry.get('on', []):
            midi = toolkit.getMIDIValuesForElement(xml_id)
            key = (round(entry['qstamp'], 5), midi.get('pitch'))
            if by_position[key]:
                locations[by_position[key].popleft()] = xml_id
    return toolkit, locations


def build_notation(musicxml, reference, performance, report):
    score = json.loads(reference.read_text(encoding='utf-8'))
    from pianocoach.report import _omr_wedges, _recognition_files, score_metadata
    notes = score['notes']
    toolkit, locations = render_score(musicxml, notes)
    played, _, _ = load_performance(performance)
    played = {n['id']: n for n in played}

    # Audiveris retains the PDF hairpins in its OMR file even though its
    # MusicXML export drops them. Map those score positions onto Verovio note IDs.
    notation = score_metadata(musicxml)
    numerator, denominator = notation.get('time_signature', [4, 4])
    unit = denominator / 4.0
    bar_beats = numerator / unit
    starts = {}
    for note in notes:
        measure = int(note['measure'])
        starts.setdefault(measure, note['onset'] - (note.get('beat_in_measure', 1.0) - 1) / unit)
    first_chunk = {measure: dict(start_beat=start, end_beat=start + bar_beats)
                   for measure, start in starts.items()}
    ui_measure = {measure: measure for measure in first_chunk}
    score_wedges = []
    for omr in _recognition_files(musicxml):
        score_wedges.extend(_omr_wedges(omr, first_chunk, ui_measure,
                                        lambda onset, chunk: 1 + (onset - chunk['start_beat']) * unit))
    note_by_id = {note['id']: note for note in notes}
    wedges = []
    for wedge in score_wedges:
        endpoints = []
        for measure, beat in ((wedge['start_measure'], wedge['start_beat']),
                               (wedge['end_measure'], wedge['end_beat'])):
            chunk = first_chunk.get(measure)
            if chunk is None:
                endpoints = []
                break
            target = chunk['start_beat'] + (beat - 1) / unit
            candidates = [note for note in notes if int(note['measure']) == measure and note['id'] in locations]
            if not candidates:
                endpoints = []
                break
            nearest = min(candidates, key=lambda note: abs(note['onset'] - target))
            endpoints.append(locations[nearest['id']])
        if len(endpoints) != 2:
            continue
        measure_reports = [bar for bar in report.get('measures', [])
                           if bar.get('number') in range(wedge['start_measure'], wedge['end_measure'] + 1)]
        needs = wedge['kind'] + '_needs_more'
        followed = wedge['kind'] + '_followed'
        status = ('wrong' if any(bar.get('dynamics_trend') == needs for bar in measure_reports)
                  else 'good' if any(bar.get('dynamics_trend') == followed for bar in measure_reports)
                  else '')
        wedges.append(dict(kind=wedge['kind'], start_xml_id=endpoints[0], end_xml_id=endpoints[1],
                           status=status))

    annotations, unplaced = [], []
    located = [m for m in report['matches'] if m['score_note_id'] in locations]
    for match in report['matches']:
        xml_id = locations.get(match['score_note_id'])
        anchor = match
        if xml_id is None and match['category'] == 'extra':
            anchor = _extra_anchor(match, report, located, locations, notes, note_by_id)
            if anchor is not None:
                xml_id = locations[anchor['score_note_id']]
        if xml_id is None:
            unplaced.append(match)
            continue
        actual = match['actual_pitch']
        shift = 0
        if actual is not None:
            # Read the engraved spelling so enharmonic notes sit on the right line.
            attrs = toolkit.getElementAttr(xml_id)
            engraved = pitch.Pitch(attrs['pname'] + str(attrs['oct']))
            detected = pitch.Pitch(midi=actual)
            shift = detected.diatonicNoteNum - engraved.diatonicNoteNum
        event = played.get(match['performance_note_id'])
        annotations.append(dict(match, xml_id=xml_id, display_beat=anchor.get('score_beat'), staff_steps=shift,
                                actual_name=pitch.Pitch(midi=actual).nameWithOctave if actual is not None else None,
                                expected_name=pitch.Pitch(midi=match['expected_pitch']).nameWithOctave
                                if match['expected_pitch'] is not None else None,
                                duration=event['duration'] if event else 0))
    return dict(pages=[toolkit.renderToSVG(page) for page in range(1, toolkit.getPageCount() + 1)],
                annotations=annotations, unplaced=unplaced, wedges=wedges)
