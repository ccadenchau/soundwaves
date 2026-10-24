let pianoSamples;

async function loadPiano(context, notes) {
  pianoSamples ??= fetch('/static/audio/piano.json').then((response) => {
    if (!response.ok) throw new Error('Could not load the piano samples.');
    return response.json();
  });
  const samples = await pianoSamples;
  const buffers = new Map();
  await Promise.all([...new Set(notes)].map(async (pitch) => {
    const names = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B'];
    const name = names[pitch % 12] + (Math.floor(pitch / 12) - 1);
    const data = samples[name];
    if (!data) throw new Error(`No piano sample is available for ${name}.`);
    const bytes = Uint8Array.from(atob(data.split(',')[1]), (character) => character.charCodeAt(0));
    buffers.set(pitch, await context.decodeAudioData(bytes.buffer));
  }));
  return buffers;
}

function playPiano(context, destination, buffers, note, onset, duration) {
  const source = context.createBufferSource();
  source.buffer = buffers.get(note.midi);
  const gain = context.createGain();
  const volume = note.velocity ** 2;
  gain.gain.setValueAtTime(volume, onset);
  gain.gain.setValueAtTime(volume, onset + duration);
  gain.gain.exponentialRampToValueAtTime(0.0001, onset + duration + 0.15);
  source.connect(gain);
  gain.connect(destination);
  source.start(onset);
  source.stop(onset + duration + 0.16);
}
