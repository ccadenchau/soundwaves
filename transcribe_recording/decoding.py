from .models import TranscriptionConfig


def decode_notes(features: dict, duration: float, config: TranscriptionConfig) -> list:
    import numpy as np
    from scipy.signal import find_peaks

    frames = features['note']
    onsets = features['onset']
    times = features['frame_times']
    events = []
    for pitch in range(config.lowest_pitch, config.highest_pitch + 1):
        index = pitch - 21
        activation = frames[:, index]
        attack = onsets[:, index]
        rising = np.maximum(0, np.diff(activation, prepend=0))
        evidence = np.maximum(attack, rising)
        starts, _ = find_peaks(
            np.pad(evidence, (1, 1)), height=config.onset_threshold, distance=2
        )
        starts = starts - 1
        for position, start in enumerate(starts):
            boundary = starts[position + 1] if position + 1 < len(starts) else len(times)
            end = boundary
            inactive = 0
            for frame in range(start + 1, boundary):
                inactive = inactive + 1 if activation[frame] < config.frame_threshold else 0
                if inactive == 3:
                    end = frame - 2
                    break
            onset = float(times[start])
            offset = float(times[end]) if end < len(times) else duration
            if offset - onset < config.minimum_note_length_ms / 1000:
                continue
            score = float(np.mean(activation[start:end]))
            events.append((onset, offset, pitch, score))
    return sorted(events)
