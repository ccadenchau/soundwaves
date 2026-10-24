import re
import shutil
import sys
from pathlib import Path
from uuid import uuid4
from threading import Lock

from flask import (
    Flask,
    abort,
    jsonify,
    render_template,
    request,
    send_from_directory,
    url_for,
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from soundwaves import convert_score
from preview import create_preview

app = Flask(
    __name__,
    instance_path=str(Path(__file__).resolve().parent / "instance"),
)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
UPLOADS = Path(app.instance_path) / "uploads"
preview_lock = Lock()


@app.after_request
def disable_file_cache(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/convert")
def convert():
    upload = request.files.get("score")
    extension = Path(upload.filename or "").suffix.lower() if upload else ""
    if extension not in {".pdf", ".xml", ".musicxml", ".mxl"}:
        return jsonify(error="Choose a PDF or MusicXML file."), 400
    if extension == ".pdf" and not upload.stream.read(1024).lstrip().startswith(b"%PDF-"):
        return jsonify(error="This file is not a PDF."), 400
    upload.stream.seek(0)
    content = upload.read()
    job_id = uuid4().hex
    folder = UPLOADS / job_id
    folder.mkdir(parents=True)
    source = folder / f"score{extension}"
    source.write_bytes(content)
    try:
        result = convert_score(source, folder)
        with preview_lock:
            create_preview(result.midi.parent)
    except Exception as error:
        shutil.rmtree(folder, ignore_errors=True)
        message = (
            str(error)
            if isinstance(error, (ValueError, RuntimeError))
            else "Could not convert this score."
        )
        return jsonify(error=message), 422
    return jsonify(
        midi_url=url_for("download", job_id=job_id, filename="reference.mid"),
        preview_url=url_for("download", job_id=job_id, filename="preview.json"),
        pdf_url=(
            url_for("download", job_id=job_id, filename="score.pdf")
            if extension == ".pdf"
            else None
        ),
        score_url=url_for("download", job_id=job_id, filename="reference.musicxml"),
        original_score_url=url_for("download", job_id=job_id, filename="original.musicxml"),
        repairs_url=url_for("download", job_id=job_id, filename="repairs.json"),
    )


@app.get("/files/<job_id>/<filename>")
def download(job_id, filename):
    if not re.fullmatch(r"[a-f0-9]{32}", job_id):
        abort(404)
    if filename == "score.pdf":
        return send_from_directory(UPLOADS / job_id, filename, max_age=0)
    allowed = {
        "reference.mid", "reference.wav", "reference.json",
        "preview.json", "reference.musicxml", "original.musicxml", "repairs.json",
    }
    if filename not in allowed and not re.fullmatch(r"page_[1-9][0-9]*\.svg", filename):
        abort(404)
    return send_from_directory(UPLOADS / job_id / "reference", filename, max_age=0)


@app.errorhandler(413)
def upload_too_large(error):
    return jsonify(error="Choose a file smaller than 20 MB."), 413


def run():
    app.run(host="127.0.0.1", port=5000)


if __name__ == '__main__':
    run()
