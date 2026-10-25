from fractions import Fraction

from music21 import clef, duration, stream


def inspect_score(score):
    issues = []
    tuplets = []
    measure_spans = {}

    def report(code, part, measure, message, beat=None):
        issues.append({
            "code": code,
            "part": str(part.id),
            "measure": measure.number,
            "beat": beat,
            "message": message,
        })

    for part in score.parts:
        measures = list(part.getElementsByClass(stream.Measure))
        previous_pitches = {}
        active_ties = {}
        for index, measure in enumerate(measures):
            signature = measure.timeSignature or measure.getContextByClass('TimeSignature')
            expected = float(signature.barDuration.quarterLength) if signature else None
            span = float(measure.highestTime)
            measure_spans.setdefault(measure.number, []).append((str(part.id), span))
            if expected and span > expected + 0.001:
                report('overfull_measure', part, measure,
                       'Notes extend beyond the time signature. Check voices, tuplets, and barlines.')
            elif expected and span < expected - 0.001 and index not in (0, len(measures) - 1):
                report('short_measure', part, measure,
                       'Measure is shorter than its time signature. Check missing notes, rests, and false tuplets.')
            clefs = list(measure.recurse().getElementsByClass(clef.Clef))
            voices = list(measure.voices) or [measure]
            for voice in voices:
                voice_id = str(voice.id) if isinstance(voice, stream.Voice) else '1'
                previous_end = None
                for element in voice.recurse().notesAndRests:
                    if element.duration.isGrace:
                        continue
                    onset = float(element.getOffsetInHierarchy(measure))
                    length = float(element.quarterLength)
                    if previous_end is not None and onset < previous_end - 0.001:
                        report('voice_overlap', part, measure,
                               f'Voice {voice_id} has overlapping events. Simultaneous pitches should form a chord.', onset + 1)
                    previous_end = max(previous_end or 0, onset + length)
                    if element.duration.tuplets:
                        ratios = []
                        multiplier = Fraction(1)
                        for tuplet in element.duration.tuplets:
                            actual = tuplet.numberNotesActual
                            normal = tuplet.numberNotesNormal
                            if actual <= 0 or normal <= 0:
                                report('invalid_tuplet', part, measure, 'Tuplet has an invalid ratio.', onset + 1)
                                continue
                            multiplier *= Fraction(tuplet.tupletMultiplier())
                            ratios.append({"actual": actual, "normal": normal})
                        tuplets.append({
                            "part": str(part.id), "measure": measure.number,
                            "voice": voice_id, "offset": onset,
                            "duration": length, "ratios": ratios,
                        })
                        if element.duration.type not in ('complex', 'inexpressible'):
                            written = duration.Duration(type=element.duration.type, dots=element.duration.dots)
                            sounding = float(Fraction(written.quarterLength) * multiplier)
                            if abs(sounding - length) > 0.001:
                                report('tuplet_duration', part, measure,
                                       'Written tuplet ratio disagrees with its playback duration.', onset + 1)
                    if element.isRest:
                        previous_pitches.pop(voice_id, None)
                        continue
                    pitches = sorted(p.midi for p in element.pitches)
                    previous = previous_pitches.get(voice_id)
                    if previous and pitches and min(abs(a - b) for a in previous for b in pitches) >= 19 and not clefs:
                        report('pitch_jump', part, measure,
                               'Large pitch jump without a clef change. Check for a missed clef or octave marking.', onset + 1)
                    previous_pitches[voice_id] = pitches
                    members = element.notes if element.isChord else [element]
                    for member in members:
                        key = (voice_id, member.pitch.nameWithOctave)
                        tie = member.tie.type if member.tie else None
                        absolute = float(measure.offset) + onset
                        if tie in ('continue', 'stop'):
                            previous_offset = active_ties.get(key)
                            if previous_offset is None or abs(previous_offset - absolute) > 0.001:
                                report('broken_tie', part, measure,
                                       f'Tie on {member.pitch.nameWithOctave} has no contiguous matching note in this voice.', onset + 1)
                        if tie in ('start', 'continue'):
                            active_ties[key] = absolute + length
                        else:
                            active_ties.pop(key, None)
        if active_ties and measures:
            report('open_tie', part, measures[-1], 'One or more ties have no ending note in this score.')

    for number, spans in measure_spans.items():
        if len(spans) > 1 and max(s for _, s in spans) - min(s for _, s in spans) > 0.001:
            issues.append({
                "code": "staff_duration_mismatch", "part": None, "measure": number,
                "beat": None,
                "message": "Staves have different measure lengths. Check misplaced voices, rests, and tuplet groups.",
            })
    return {"issues": issues, "tuplets": tuplets}
