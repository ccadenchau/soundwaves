const form = document.querySelector('#upload-form');
const convertButton = document.querySelector('#convert');
const status = document.querySelector('#status');
const player = document.querySelector('#player');
const playButton = document.querySelector('#play');
const stopButton = document.querySelector('#stop');
const download = document.querySelector('#download');
let midi;
let audio;
const speed = document.querySelector('#speed');
const notation = document.querySelector('#notation');
const position = document.querySelector('#position');
const progress = document.querySelector('#progress');
let timeline = [];
let timelineIndex = 0;
let frame;
let startTime = 0;
let playbackRate = 1;
let lastMeasure;
let activeNotes = new Set();
let finishTimer;
let playbackId = 0;

function updateScore() {
  const elapsed = Math.max(0, (audio.currentTime - startTime) * playbackRate);
  while (timelineIndex < timeline.length && timeline[timelineIndex].tstamp <= elapsed * 1000) {
    const entry = timeline[timelineIndex++];
    for (const id of entry.off || []) activeNotes.delete(id);
    for (const id of entry.on || []) activeNotes.add(id);
  }
  notation.querySelectorAll('.playing').forEach((note) => note.classList.remove('playing'));
  for (const id of activeNotes) document.getElementById(id)?.classList.add('playing');
  const current = [...activeNotes].map((id) => document.getElementById(id)).find(Boolean);
  const measure = current?.closest('.measure');
  if (measure && measure !== lastMeasure) {
    const top = notation.scrollTop + measure.getBoundingClientRect().top - notation.getBoundingClientRect().top;
    notation.scrollTo({ top: Math.max(0, top - 70), behavior: 'smooth' });
    lastMeasure = measure;
  }
  progress.value = Math.min(elapsed / midi.duration, 1);
  const number = measure?.getAttribute('n');
  position.textContent = `${number ? `Measure ${number} · ` : ''}${elapsed.toFixed(1)} / ${midi.duration.toFixed(1)} seconds · ${playbackRate}×`;
  frame = requestAnimationFrame(updateScore);
}

function displayPage(svg) {
  const document = new DOMParser().parseFromString(svg, 'image/svg+xml');
  document.querySelectorAll('script, foreignObject').forEach((element) => element.remove());
  for (const element of document.querySelectorAll('*')) {
    for (const attribute of [...element.attributes]) {
      if (attribute.name.startsWith('on')) element.removeAttribute(attribute.name);
    }
  }
  notation.append(document.documentElement);
}

function displayReview(review) {
  const repairs = document.querySelector('#repairs-list');
  repairs.replaceChildren();
  const changes = review.applied_fixes || [];
  document.querySelector('#repairs').hidden = changes.length === 0;
  document.querySelector('#repairs-summary').textContent = `${changes.length} automatic repairs applied`;
  for (const change of changes) {
    const item = document.createElement('li');
    item.textContent = `Measure ${change.measure} · ${change.part}: ${change.message} Before: ${JSON.stringify(change.before)}. After: ${JSON.stringify(change.after)}.`;
    repairs.append(item);
  }
  const issues = document.querySelector('#review-issues');
  issues.replaceChildren();
  const unique = new Map((review.issues || []).map((issue) => [
    JSON.stringify([issue.code, issue.part, issue.measure, issue.message]), issue,
  ]));
  for (const issue of unique.values()) {
    const item = document.createElement('li');
    item.textContent = `Measure ${issue.measure}${issue.part ? ` · ${issue.part}` : ''}: ${issue.message}`;
    issues.append(item);
  }
  const details = document.querySelector('#review');
  details.hidden = unique.size === 0;
  details.open = unique.size > 0;
  document.querySelector('#review-summary').textContent = `${unique.size} passages need review`;
  const measures = [...new Set((review.tuplets || [])
    .filter((entry) => entry.ratios.some((ratio) => ratio.actual === 6))
    .map((entry) => entry.measure))];
  document.querySelector('#tuplet-summary').textContent = measures.length
    ? `Sextuplets recognized in measures ${measures.join(', ')}. A bracketed 6 changes note timing; it does not repeat the passage six times.`
    : 'No sextuplets were recognized. If your score has a bracketed 6, check that passage against the original.';
}

function stopPlayback() {
  playbackId += 1;
  clearTimeout(finishTimer);
  cancelAnimationFrame(frame);
  notation.querySelectorAll('.playing').forEach((note) => note.classList.remove('playing'));
  activeNotes.clear();
  timelineIndex = 0;
  lastMeasure = null;
  speed.disabled = false;
  if (audio) audio.close();
  audio = null;
  playButton.disabled = false;
  stopButton.disabled = true;
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  stopPlayback();
  player.hidden = true;
  convertButton.disabled = true;
  status.textContent = 'Reading your score. This may take a few minutes…';
  try {
    const response = await fetch('/convert', { method: 'POST', body: new FormData(form) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error);
    const file = await fetch(result.midi_url);
    if (!file.ok) throw new Error('Could not load the MIDI file.');
    midi = new Midi(await file.arrayBuffer());
    if (!midi.tracks.some((track) => track.notes.length)) {
      throw new Error('No notes were recognized in this score.');
    }
    const previewResponse = await fetch(result.preview_url);
    if (!previewResponse.ok) throw new Error('Could not load the score preview.');
    const preview = await previewResponse.json();
    const pages = await Promise.all(preview.pages.map(async (page) => {
      const response = await fetch(new URL(page, new URL(result.preview_url, location.href)));
      if (!response.ok) throw new Error('Could not load a score page.');
      return response.text();
    }));
    notation.replaceChildren();
    pages.forEach(displayPage);
    timeline = preview.timeline;
    displayReview(preview.review);
    const original = document.querySelector('#original');
    original.hidden = !result.pdf_url;
    if (result.pdf_url) original.src = result.pdf_url;
    else original.removeAttribute('src');
    document.querySelector('#original-message').hidden = Boolean(result.pdf_url);
    document.querySelector('#download-score').href = result.score_url;
    document.querySelector('#download-original').href = result.original_score_url;
    document.querySelector('#download-repairs').href = result.repairs_url;
    position.textContent = 'Ready · Normal speed follows the score tempo';
    progress.value = 0;
    download.href = result.midi_url;
    player.hidden = false;
    status.textContent = preview.review.issues.length ? 'Repairs applied where supported · Review the remaining flagged passages before relying on playback.' : 'Ready to play · Automatic checks found no structural issues; compare with the original.';
  } catch (error) {
    status.textContent = error.message || 'Conversion failed. Try again.';
  } finally {
    convertButton.disabled = false;
  }
});

playButton.addEventListener('click', async () => {
  stopPlayback();
  const id = playbackId;
  try {
    playButton.disabled = true;
    speed.disabled = true;
    stopButton.disabled = false;
    status.textContent = 'Loading piano samples…';
    const context = new AudioContext();
    audio = context;
    await context.resume();
    const buffers = await loadPiano(context, midi.tracks.flatMap((track) => track.notes.map((note) => note.midi)));
    if (id !== playbackId) return;
    status.textContent = 'Playing';
    const master = audio.createGain();
    master.gain.value = 0.4;
    const compressor = audio.createDynamicsCompressor();
    master.connect(compressor);
    compressor.connect(audio.destination);
    playbackRate = Number(speed.value);
    speed.disabled = true;
    startTime = audio.currentTime + 0.1;
    const start = startTime;
    for (const track of midi.tracks) {
      for (const note of track.notes) {
        const onset = start + note.time / playbackRate;
        const duration = Math.max(note.duration / playbackRate, 0.02);
        playPiano(audio, master, buffers, note, onset, duration);
      }
    }
    playButton.disabled = true;
    stopButton.disabled = false;
    frame = requestAnimationFrame(updateScore);
    finishTimer = setTimeout(() => {
      stopPlayback();
      progress.value = 1;
      position.textContent = 'Finished';
    }, (midi.duration / playbackRate + 0.3) * 1000);
  } catch (error) {
    if (id !== playbackId) return;
    stopPlayback();
    status.textContent = error.message || 'Could not start audio playback.';
  }
});

stopButton.addEventListener('click', () => {
  stopPlayback();
  progress.value = 0;
  position.textContent = 'Stopped';
});
