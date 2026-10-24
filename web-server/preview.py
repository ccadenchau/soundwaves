import json
from importlib.resources import files

import verovio


def create_preview(folder):
    toolkit = verovio.toolkit(False)
    resources = str(files("verovio") / "data")
    if not toolkit.setResourcePath(resources):
        raise RuntimeError(
            "Verovio font resources are missing. Reinstall the verovio package."
        )
    toolkit.setOptions({"pageWidth": 1600, "pageHeight": 2200, "scale": 40})
    if not toolkit.loadFile(str(folder / "reference.musicxml")):
        raise ValueError("Could not display the recognized score.")
    toolkit.renderToMIDI()
    pages = []
    for page in range(1, toolkit.getPageCount() + 1):
        filename = f"page_{page}.svg"
        (folder / filename).write_text(toolkit.renderToSVG(page))
        pages.append(filename)
    timeline = toolkit.renderToTimemap()
    reference = json.loads((folder / "reference.json").read_text())
    tempi = reference["tempo_changes"]
    for entry in timeline:
        beat = entry["qstamp"]
        elapsed = 0.0
        for index, (start, bpm) in enumerate(tempi):
            if start >= beat:
                break
            end = tempi[index + 1][0] if index + 1 < len(tempi) else beat
            elapsed += (min(beat, end) - start) * 60 / bpm
        entry["tstamp"] = elapsed * 1000
    (folder / "preview.json").write_text(json.dumps({"version": 4, "pages": pages, "timeline": timeline, "review": reference["review"]}))
