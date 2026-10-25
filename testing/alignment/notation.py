"""Render score notation and attach performance matches without changing audio."""

import json
from collections import defaultdict, deque
from importlib.resources import files

from music21 import pitch

from alignment.inputs import load_performance


def build_notation(musicxml, reference, performance, report):
    import verovio

    toolkit = verovio.toolkit(False)
    toolkit.setResourcePath(str(files('verovio') / 'data'))
    toolkit.setOptions(dict(pageWidth=1500, pageHeight=2000, scale=45,
                            adjustPageHeight=True, breaks='auto'))
    if not toolkit.loadFile(str(musicxml)):
        raise ValueError('Could not render the recognized score.')
    toolkit.renderToMIDI()
    score = json.loads(reference.read_text(encoding='utf-8'))
    from pianocoach.report import _omr_wedges, _recognition_files, score_metadata
    notes = score['notes']
    played, _, _ = load_performance(performance)
    played = {n['id']: n for n in played}
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
            candidates = [m for m in located
                          if m['measure_occurrence'] == match['measure_occurrence']
                          and m['audio_time'] is not None]
            if candidates:
                anchor = min(candidates, key=lambda m: abs(m['audio_time'] - match['audio_time']))
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
