"""One header and footer for every PianoCoach page, so the site reads as one thing."""

NAV = (('live', '/live', 'Play live'), ('check', '/check', 'Check a recording'), ('add', '/upload', 'Add a piece'))


def header(active=''):
    links = ''.join(f'<a href="{href}"{" class=on" if key == active else ""}>{label}</a>' for key, href, label in NAV)
    return ('<header class="site-head"><div class="in"><a class="brand" href="/"><i>♪</i>PianoCoach</a>'
            f'<nav aria-label="Main">{links}</nav></div></header>')


FOOTER = ('<footer class="site-foot">PianoCoach listens to you play from your own sheet music and marks every note, '
          'for people learning piano without a teacher in the room. Made at Cal Hacks 13.0. '
          'Team tools: <a href="/test">self-checks</a> · <a href="/convert">audio to MIDI</a></footer>')

HEAD = '<link rel="stylesheet" href="/site.css">'
