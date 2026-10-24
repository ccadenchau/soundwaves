import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from transcribe_recording import transcribe_recording

AUDIO_PATH = '/Users/caden/Downloads/test recording 1.mp3'


if __name__ == '__main__':
    result = transcribe_recording(AUDIO_PATH)
    print(result.midi_path)
