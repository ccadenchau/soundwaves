// Feed per-window detections through the browser's real LiveNoteStream and report what it emits.
// stdin: [{start, end, received, notes:[{pitch, onset, duration, velocity}]}...]  stdout: [{pitch, time, emitted}]
const LiveNoteStream = require('../../pianocoach-ui/live-stream.js');
let input = '';
process.stdin.on('data', d => input += d).on('end', () => {
  const windows = JSON.parse(input), stream = new LiveNoteStream(), out = [];
  for (const w of windows) {
    const batch = stream.ingest(w.notes, {start: w.start, end: w.end});
    for (const e of batch.events) out.push({pitch: e.pitch, time: e.time, emitted: w.received});
  }
  process.stdout.write(JSON.stringify(out));
});
