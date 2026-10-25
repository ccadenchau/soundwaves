"""One header and footer for every Soundwaves page, so the site reads as one thing."""

NAV = (('live', '/live', 'Play live'), ('check', '/check', 'Check a recording'), ('add', '/upload', 'Add a piece'), ('easy', '/easy', 'Make it easy'), ('learn', '/learn', 'Learn a tune'))


from pathlib import Path
from flask import render_template

PARTIALS = Path(__file__).resolve().parents[1] / 'frontend' / 'templates' / 'partials'
HEAD = (PARTIALS / 'head.html').read_text()
FOOTER = (PARTIALS / 'footer.html').read_text()


def header(active=''):
    return render_template('partials/header.html', nav=NAV, active=active)
