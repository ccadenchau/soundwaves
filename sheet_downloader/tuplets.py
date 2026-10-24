from fractions import Fraction
from xml.etree import ElementTree
from zipfile import ZipFile

TYPES = {
    "whole": 4, "half": 2, "quarter": 1, "eighth": Fraction(1, 2),
    "16th": Fraction(1, 4), "32nd": Fraction(1, 8), "64th": Fraction(1, 16),
    "128th": Fraction(1, 32), "256th": Fraction(1, 64),
}


def read_xml(source):
    if source.suffix.lower() != '.mxl':
        root = ElementTree.parse(source).getroot()
    else:
        with ZipFile(source) as archive:
            container = ElementTree.fromstring(archive.read('META-INF/container.xml'))
            entry = next(node for node in container.iter() if node.tag.endswith('rootfile'))
            root = ElementTree.fromstring(archive.read(entry.attrib['full-path']))
    for node in root.iter():
        node.tag = node.tag.rsplit('}', 1)[-1]
    return root


def inspect_tuplets(source):
    issues = []
    root = read_xml(source)
    for part in root.findall('part'):
        active = {}
        divisions = Fraction(1)
        for measure in part.findall('measure'):
            number = measure.get('number')
            for node in measure:
                if node.tag == 'attributes' and node.findtext('divisions'):
                    divisions = Fraction(node.findtext('divisions'))
                if node.tag != 'note' or node.find('grace') is not None:
                    continue
                voice = node.findtext('voice', '1')
                brackets = node.findall('notations/tuplet')
                for bracket in brackets:
                    if bracket.get('type') == 'start':
                        key = (voice, bracket.get('number', '1'))
                        active[key] = {
                            'measure': number, 'notes': [],
                            'actual': bracket.findtext('tuplet-actual/tuplet-number')
                                or node.findtext('time-modification/actual-notes'),
                        }
                if node.find('chord') is None:
                    for (group_voice, _), group in active.items():
                        if group_voice == voice:
                            group['notes'].append(node)
                for bracket in brackets:
                    if bracket.get('type') != 'stop':
                        continue
                    group = active.pop((voice, bracket.get('number', '1')), None)
                    if group is None:
                        issues.append(issue(part, number, 'Tuplet bracket has no matching start in its voice.'))
                        continue
                    notes = group['notes']
                    if any(n.find('time-modification') is None for n in notes):
                        issues.append(issue(part, group['measure'],
                            'Tuplet bracket includes notes without a playback ratio. Its rhythm needs review.'))
                    if group['actual'] == '6':
                        lengths = [written_length(n) for n in notes]
                        if lengths and all(lengths):
                            units = sum(lengths) / min(lengths)
                            if units != 6:
                                issues.append(issue(part, group['measure'],
                                    'Sextuplet bracket does not cover six written note units. Check its endpoints, note values, and voice assignment.'))
                modification = node.find('time-modification')
                written = written_length(node)
                if modification is not None and written and node.findtext('duration'):
                    actual = int(modification.findtext('actual-notes', '0'))
                    normal = int(modification.findtext('normal-notes', '0'))
                    if actual <= 0 or normal <= 0 or divisions <= 0:
                        issues.append(issue(part, number, 'Tuplet ratio or timing divisions are invalid.'))
                    elif abs(float(Fraction(node.findtext('duration')) / divisions - written * Fraction(normal, actual))) > 0.001:
                        issues.append(issue(part, number,
                            'Tuplet ratio disagrees with the MusicXML duration. Review the recognized rhythm.'))
        for group in active.values():
            issues.append(issue(part, group['measure'], 'Tuplet bracket has no matching end in its voice.'))
    return issues


def written_length(note):
    value = TYPES.get(note.findtext('type'))
    if value is None:
        return None
    return Fraction(value) * sum(Fraction(1, 2 ** dot) for dot in range(len(note.findall('dot')) + 1))


def issue(part, measure, message):
    return {'code': 'tuplet_notation', 'part': part.get('id'), 'measure': measure,
            'beat': None, 'message': message}
