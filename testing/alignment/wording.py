"""Plain words for the aligner's bar notes, shared by the report and the live page."""


def plain_feedback(bar):
    """The aligner's bar notes, said the way a teacher would."""
    import re as _re
    out = []
    for line in bar.get('feedback') or []:
        m = _re.match(r'This bar was approximately (\d+%) (faster|slower) than the score tempo', line)
        if m:
            out.append(f'About {m.group(1)} {m.group(2)} than written.')
        elif line.startswith('All expected pitches matched'):
            out.append('Every note right.')
        elif line.startswith('Review the candidate pitch'):
            parts = [f"{bar['missing_notes']} skipped" if bar.get('missing_notes') else '',
                     f"{bar['wrong_pitch_notes']} wrong" if bar.get('wrong_pitch_notes') else '',
                     f"{bar['extra_notes']} extra" if bar.get('extra_notes') else '']
            parts = [x for x in parts if x]
            if parts:
                out.append('Check the coloured notes: ' + ', '.join(parts) + '.')
        elif line.startswith('Not enough reliable'):
            out.append('Too few clear notes here to judge the tempo.')
        elif line.startswith('Timing within this bar was irregular'):
            out.append('The beat wobbled inside this bar.')
        elif 'relative level is stronger' in line:
            out.append('Louder than the rest of your playing; the score wants it softer.')
        elif 'relative level is softer' in line:
            out.append('Quieter than the rest of your playing; bring it out more.')
        else:
            out.append(line)
    return out
