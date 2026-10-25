// Run the browser's LiveNoteStream + LiveScoreFollower exactly as practice.js does for the microphone.
// stdin: {score:[{id,pitch,beat,duration}], bpm, input, windows:[{start,end,received,notes:[...]}]}
// stdout: {marks:{id:{kind,actual}}, timeline:[{received, id, kind}]}
const LiveNoteStream = require('../../pianocoach-ui/live-stream.js');
const LiveScoreFollower = require('../../pianocoach-ui/live-matcher.js');
let input = '';
process.stdin.on('data', d => input += d).on('end', () => {
  const job = JSON.parse(input);
  const stream = new LiveNoteStream();
  const follower = new LiveScoreFollower(job.score, {bpm: job.bpm, input: job.input || 'mic'});
  const marks = {}, timeline = [], late = [], fed = [];
  for (const w of job.windows) {
    const batch = w.events ? {events: w.events} : stream.ingest(w.notes, {start: w.start, end: w.end});
    for (const n of (batch.late || [])) late.push(n);
    for (const n of batch.events) fed.push(n);
    if (!batch.events.length) continue;
    const result = follower.feed(batch.events.map(e => ({pitch: e.pitch, time: e.time, velocity: e.velocity})));
    for (const m of result.marks) { marks[m.id] = {kind: m.kind, actual: m.actual, provisional: m.provisional}; timeline.push({received: w.received, id: m.id, kind: m.kind}); }
  }
  process.stdout.write(JSON.stringify({marks, timeline, late, fed}));
});
