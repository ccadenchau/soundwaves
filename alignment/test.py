"""Start the browser upload UI, or compare supplied files from the command line.

python alignment/test.py
python alignment/test.py score.pdf take.mp3
python alignment/test.py https://example.com/score.pdf take.mp3
Artifacts are reused from testing/alignment/cache/.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sheet', nargs='?', help='Optional PDF/MusicXML path or direct download URL')
    parser.add_argument('recording', nargs='?', type=Path, help='Optional local recording.mp3')
    parser.add_argument('--port', type=int, default=5001, help='Upload server port (default 5001)')
    parser.add_argument('--bpm', type=float, default=120, help='Fallback score tempo (default 120)')
    parser.add_argument('--output', type=Path, help='Optional new JSON report path')
    args = parser.parse_args()
    if bool(args.sheet) != bool(args.recording):
        parser.error('Supply both files for CLI comparison, or neither to upload in the browser.')
    if not args.sheet:
        if args.output or args.bpm != 120:
            parser.error('--output and --bpm require CLI files; choose the tempo in the upload form instead.')
        if not 1 <= args.port <= 65535:
            parser.error('--port must be between 1 and 65535.')
        from testing.alignment.app import run_server

        run_server(port=args.port)
        return
    from testing.alignment.pipeline import compare_files

    try:
        result = compare_files(args.sheet, args.recording, bpm=args.bpm)
        report = result['report']
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open('x', encoding='utf-8') as handle:
                handle.write(json.dumps(report, indent=2, allow_nan=False) + '\n')
    except Exception as error:
        parser.exit(1, f'Comparison failed: {error}\n')
    print(f"Score cache: {'reused' if result['cache']['sheet_hit'] else 'created'}")
    print(f"Recording cache: {'reused' if result['cache']['recording_hit'] else 'created'}")
    print(f"Cleaned audio cache: {'reused' if result['cache']['cleaning_hit'] else 'created'}")
    print(f"Report: {result['report_path']}")
    print(json.dumps(report['metrics'], indent=2))
    for bar in report['measures']:
        print(f"Bar {bar['number']}: pitches={bar['correct_notes']}/{bar['expected_notes']}, "
              f"tempo={bar['tempo_status']}, BPM={bar['performed_average_bpm']}")
        for message in bar['feedback']:
            print('  ' + message)
    for warning in report['warnings']:
        print('Warning: ' + warning)


if __name__ == '__main__':
    main()
