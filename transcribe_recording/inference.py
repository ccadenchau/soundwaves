from pathlib import Path

from .audio import SAMPLE_RATE

WINDOW_SAMPLES = 43844
FRAME_HOP = 256
OVERLAP_FRAMES = 30
OUTPUTS = {
    'note': 'StatefulPartitionedCall:1',
    'onset': 'StatefulPartitionedCall:2',
    'contour': 'StatefulPartitionedCall:0',
}


def infer_frames(session, audio_path: Path, save_contours: bool) -> dict:
    import numpy as np
    import soundfile as sf

    samples, sample_rate = sf.read(audio_path, dtype='float32')
    if sample_rate != SAMPLE_RATE or samples.ndim != 1 or not len(samples):
        raise ValueError('The model requires nonempty mono 22,050 Hz audio.')
    margin = OVERLAP_FRAMES // 2
    hop = WINDOW_SAMPLES - OVERLAP_FRAMES * FRAME_HOP
    padded = np.pad(samples, (margin * FRAME_HOP, 0))
    names = ['note', 'onset', 'contour'] if save_contours else ['note', 'onset']
    features = {name: [] for name in names}
    timestamps = []
    input_name = session.get_inputs()[0].name
    for start in range(0, len(samples), hop):
        window = padded[start:start + WINDOW_SAMPLES]
        window = np.pad(window, (0, WINDOW_SAMPLES - len(window)))
        outputs = session.run(
            [OUTPUTS[name] for name in names],
            {input_name: window.reshape(1, WINDOW_SAMPLES, 1)},
        )
        frame_count = outputs[0].shape[1] - 2 * margin
        times = (start + np.arange(frame_count) * FRAME_HOP) / SAMPLE_RATE
        keep = times < len(samples) / SAMPLE_RATE
        timestamps.append(times[keep])
        for name, values in zip(names, outputs):
            features[name].append(values[0, margin:-margin][keep])
    result = {name: np.concatenate(windows) for name, windows in features.items()}
    result['frame_times'] = np.concatenate(timestamps)
    return result
