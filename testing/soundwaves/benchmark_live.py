"""Measure causal live-note detection using generated audio, not a physical mic.

    .venv/bin/python -m testing.soundwaves.benchmark_live
    .venv/bin/python -m testing.soundwaves.benchmark_live --json --runs 3

Only audio already captured at each cutoff is submitted to the actual Flask
multipart endpoint. This measures model/HTTP-handler latency and the earliest
tested captured context that detects notes. It excludes device, browser,
network, request-cadence, rendering, and acoustic-room latency. No API keys or
external services are used. Sampled piano is included when the local bank exists.
"""

import argparse
import io
import json
import statistics
import tempfile
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from flask import Flask

from soundwaves.live import ROOT, practice

CASES = {'C4': [60], 'A2': [45], 'C6': [84], 'C major': [60, 64, 67],
         'Two hands': [48, 55, 60, 64, 67]}
CONTEXTS = (.20, .35, .50, .75, 1.0)
EDGE_CONTEXTS = (.05, .075, .10, .125, .15, .20, .25, .35)


def fixture(kind, pitches, onset, directory):
    if kind == 'sampled':
        from testing.render_piano import render
        path = directory / 'fixture.wav'
        render([dict(start_seconds=onset, end_seconds=1.6, pitch=pitch, velocity=90)
                for pitch in pitches], path, tail=.4)
        return sf.read(path)
    rate = 22050
    samples = np.zeros(rate * 2)
    start = round(onset * rate)
    t = np.arange(len(samples) - start) / rate
    envelope = np.minimum(t / .005, 1) * np.exp(-t * 1.8)
    for pitch in pitches:
        frequency = 440 * 2 ** ((pitch - 69) / 12)
        tone = sum(np.sin(2 * np.pi * frequency * harmonic * t) / harmonic ** 2
                   for harmonic in range(1, 5))
        samples[start:] += tone * envelope
    samples *= .7 / max(1e-6, np.max(np.abs(samples)))
    return samples, rate


def request_window(client, samples, rate):
    buffer = io.BytesIO()
    sf.write(buffer, samples, rate, format='WAV', subtype='PCM_16')
    started = time.perf_counter()
    response = client.post('/api/practice/notes', data={'audio': (io.BytesIO(buffer.getvalue()), 'window.wav')})
    elapsed = (time.perf_counter() - started) * 1000
    try:
        if response.status_code != 200:
            raise RuntimeError(f'{response.status_code}: {response.get_json()}')
        return response.get_json(), elapsed
    finally:
        response.close()
        response.request.input_stream.close()


def benchmark(runs=3):
    app = Flask(__name__)
    app.register_blueprint(practice)
    kinds = ['synthetic']
    if (ROOT / 'frontend/static/audio/piano.json').is_file():
        kinds.append('sampled')
    rows = []
    with tempfile.TemporaryDirectory(prefix='soundwaves-latency-') as folder, app.test_client() as client:
        directory = Path(folder)
        samples, rate = fixture(kinds[-1], [60], .05, directory)
        warm, warm_elapsed = request_window(client, samples[:round(.2 * rate)], rate)
        for kind in kinds:
            for label, pitches in CASES.items():
                for sweep, onset, cutoffs in (('context', .05, CONTEXTS),
                                               ('late-edge', .65, [x + .65 for x in EDGE_CONTEXTS])):
                    samples, rate = fixture(kind, pitches, onset, directory)
                    for cutoff in cutoffs:
                        compute, elapsed = [], []
                        for _ in range(runs):
                            result, total_ms = request_window(client, samples[:round(cutoff * rate)], rate)
                            compute.append(result['latencySeconds'] * 1000)
                            elapsed.append(total_ms)
                        notes = result['notes']
                        found = {n['pitch'] for n in notes}
                        rows.append(dict(source=kind, case=label, sweep=sweep,
                                         windowMs=round(cutoff * 1000), capturedAfterOnsetMs=round((cutoff - onset) * 1000),
                                         inferenceMs=round(statistics.median(compute), 2),
                                         endpointMs=round(statistics.median(elapsed), 2),
                                         expected=pitches, detected=sorted(found), missing=sorted(set(pitches) - found),
                                         extra=sorted(found - set(pitches)),
                                         onsetErrorsMs={str(n['pitch']): round((n['onset'] - onset) * 1000, 2)
                                                        for n in notes if n['pitch'] in pitches}))
    summary = []
    for kind in kinds:
        for label, pitches in CASES.items():
            subset = [row for row in rows if row['source'] == kind and row['case'] == label and row['sweep'] == 'late-edge']
            first_all = next((row for row in subset if not row['missing']), None)
            summary.append(dict(source=kind, case=label,
                                earliestAllNotesMs=first_all['capturedAfterOnsetMs'] if first_all else None,
                                earliestResultMs=round(first_all['capturedAfterOnsetMs'] + first_all['endpointMs'], 2) if first_all else None,
                                medianEndpointMs=round(statistics.median(row['endpointMs'] for row in subset), 2),
                                missingAt350Ms=subset[-1]['missing'], extrasAt350Ms=subset[-1]['extra']))
    return dict(scope='Generated audio into Flask test client; not physical-microphone latency.',
                runs=runs, coldInferenceMs=warm['latencySeconds'] * 1000,
                coldEndpointMs=round(warm_elapsed, 2), summary=summary, measurements=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=int, default=3, help='Repeated inference requests per cutoff (1–20).')
    parser.add_argument('--json', action='store_true', help='Print every measurement as JSON.')
    args = parser.parse_args()
    if not 1 <= args.runs <= 20:
        parser.error('--runs must be between 1 and 20')
    result = benchmark(args.runs)
    if not args.json:
        result.pop('measurements')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
