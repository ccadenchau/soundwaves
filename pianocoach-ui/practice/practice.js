(() => {
'use strict';
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const escape = s => String(s ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pitchNames = ['C','C♯','D','D♯','E','F','F♯','G','G♯','A','A♯','B'];
const pitchName = p => pitchNames[p%12]+(Math.floor(p/12)-1);
const formatTime = t => `${Math.floor(t/60)}:${String(Math.floor(t%60)).padStart(2,'0')}`;
const S = {phase:'idle',mode:'mic',score:null,follower:null,token:0,started:0,follow:true,events:[],open:new Map(),marks:new Map(),played:[],position:0,stream:null,recorder:null,chunks:[],context:null,worklet:null,source:null,mute:null,pcm:[],audioOrigin:0,sampleRate:22050,requestBusy:false,lastRequest:0,midi:null,group:[],groupTimer:null,clockTimer:null,raf:null,voices:new Map(),noteStream:null,levels:Array(24).fill(0),level:0,lag:[],keyTimers:new Map(),demo:null,demoCompleted:false};
const G = {left:86,beat:70,height:350,treble:88,bass:226,gap:11,width:0};
let noteElements = new Map(), referenceNotes = new Map(), pieceLoad = 0;
const pianoCache = new Map();
const MIC = {first:.20, cadence:.10, context:1.5};
function message(text) { $('#message').textContent=text; $('#message').hidden=!text; }
function setStatus(text) { $('#status').textContent=text; }
function phase(value) {
  S.phase=value;
  const active=value==='listening',busy=['starting','finishing'].includes(value);
  $('#piece').disabled=active||busy; $('#input-mode').disabled=active||busy;
  $('#start').disabled=busy||!S.score;
  const demo=S.mode==='demo';
  $('#start span').textContent=active?(demo?'Stop demo':'Finish'):value==='finishing'?'Reviewing…':value==='starting'?(demo?'Loading piano…':'Connecting…'):value==='review'?(demo?'Replay demo':'New take'):'Start';
  $('#demo').disabled=busy||!S.score||(active&&!demo);$('#demo').classList.toggle('playing',active&&demo);$('#demo span').textContent=active&&demo?'Stop demo':'Play demo';$('#demo small').hidden=active&&demo;
  $('#start').classList.toggle('finish',active);
  $('#start svg').innerHTML=active?'<path d="M4 4h8v8H4Z"/>':'<path d="M5 3l8 5-8 5Z"/>';
  $('#source-dot').classList.toggle('live',active);
  $('#live-label').textContent=active?(demo?'Demo playing':S.mode==='mic'?'Listening':'Live'):value==='finishing'?'Finishing':'Ready';
  $$('#piano button').forEach(b=>b.disabled=!(active&&S.mode==='keys'));
}
function staveStep(pitch) { return (Math.floor(pitch/12)-1)*7 + [0,0,1,1,2,3,3,4,4,5,5,6][pitch%12]; }
const noteY = n => (n.hand==='left'?G.bass:G.treble)+4*G.gap-(staveStep(n.pitch)-(n.hand==='left'?18:30))*G.gap/2;
const noteX = beat => G.left + beat*G.beat;
function drawScore() {
  const score=S.score,notes=score.notes; referenceNotes=new Map(notes.map(n=>[n.id,n])); G.width=noteX(score.totalBeats)+40;
  let svg='';
  for (const top of [G.treble,G.bass]) for(let i=0;i<5;i++) svg+=`<line class="stave" x1="12" x2="${G.width-20}" y1="${top+i*G.gap}" y2="${top+i*G.gap}"/>`;
  svg+=`<text class="clef" x="12" y="${G.treble+48}">𝄞</text><text class="clef" x="18" y="${G.bass+31}">𝄢</text>`;
  const signature=score.piece.time_signature||[4,4];
  for(const top of [G.treble,G.bass]) svg+=`<text class="time-signature" x="57" y="${top+20}">${signature[0]}</text><text class="time-signature" x="57" y="${top+42}">${signature[1]}</text>`;
  const measures=new Map();
  for(const n of notes) if(!measures.has(n.measure)) measures.set(n.measure,n.beat-(n.beatInMeasure-1));
  for(const [measure,beat] of measures) { const x=noteX(beat)-15; svg+=`<line class="barline" x1="${x}" x2="${x}" y1="${G.treble}" y2="${G.bass+44}"/><text class="measure-number" x="${x+7}" y="48">${measure}</text>`; }
  for(const n of notes) {
    const x=noteX(n.beat),y=noteY(n),top=n.hand==='left'?G.bass:G.treble,up=y>top+22,stemX=x+(up?6:-6),stemY=y+(up?-31:31);
    svg+=`<g class="score-note" data-note="${escape(n.id)}"><title>${escape(pitchName(n.pitch))}, bar ${n.measure}</title>`;
    for(let line=top-11;line>=y-1;line-=11) svg+=`<line class="stem" x1="${x-11}" x2="${x+11}" y1="${line}" y2="${line}"/>`;
    for(let line=top+55;line<=y+1;line+=11) svg+=`<line class="stem" x1="${x-11}" x2="${x+11}" y1="${line}" y2="${line}"/>`;
    if([1,3,6,8,10].includes(n.pitch%12)) svg+=`<text class="accidental" x="${x-20}" y="${y+5}">♯</text>`;
    svg+=`<circle class="note-halo" cx="${x}" cy="${y}" r="15"/><ellipse class="notehead" cx="${x}" cy="${y}" rx="6.3" ry="4.6" transform="rotate(-20 ${x} ${y})" ${n.duration>=2?'style="fill:var(--paper)"':''}/>`;
    if(n.duration<4) svg+=`<line class="stem" x1="${stemX}" x2="${stemX}" y1="${y}" y2="${stemY}"/>`;
    if(n.duration<1) svg+=`<path class="stem" fill="none" d="M${stemX} ${stemY}q${up?11:-11} ${up?8:-8} 6 ${up?18:-18}"/>`;
    if(Math.abs(n.duration-1.5)<.01||Math.abs(n.duration-3)<.01) svg+=`<circle fill="currentColor" cx="${x+12}" cy="${y-2}" r="1.8"/>`;
    svg+=`<circle class="mark-dot" cx="${x}" cy="${y+(up?15:-15)}" r="3"/></g>`;
  }
  svg+=`<g id="cursor" hidden><line class="score-cursor" x1="0" x2="0" y1="62" y2="297"/><circle class="cursor-cap" cx="0" cy="62" r="3"/></g>`;
  $('#score').innerHTML=`<svg class="notation" width="${G.width}" height="${G.height}" viewBox="0 0 ${G.width} ${G.height}" role="img" aria-label="Piano score, treble and bass, ${score.piece.measures} bars">${svg}</svg>`;
  noteElements=new Map($$('.score-note').map(e=>[e.dataset.note,e]));
  $('#score').scrollLeft=0;
  $('#score-info').textContent=`${score.piece.measures} bars`;
  $('#bar-label').textContent='Bar 1';$('#piece-progress').style.width='0%';$('.piece-progress').setAttribute('aria-valuenow','0');updateExpectedKeys();renderComparison();
}
function moveCursor(beat) {
  S.position=beat; const x=noteX(beat),cursor=$('#cursor'); cursor.hidden=false; cursor.removeAttribute('hidden'); cursor.setAttribute('transform',`translate(${x},0)`);
  const n=S.score.notes.findLast(n=>n.beat<=beat+.01); $('#bar-label').textContent=`Bar ${n?.measure||1}`;
  const progress=Math.min(100,Math.round(beat/S.score.totalBeats*100));$('#piece-progress').style.width=`${progress}%`;$('.piece-progress').setAttribute('aria-valuenow',String(progress));
  if(S.follow) { const view=$('#score'); view.scrollLeft=Math.max(0,x-Math.max(G.left,view.clientWidth*.35)); }
}
function updateExpectedKeys() {
  const next=S.follower?S.follower.available(S.follower.cursor):(S.score?.notes.filter(n=>n.beat===S.score.notes[0].beat)||[]);
  const pitches=new Set(next.map(n=>n.pitch));
  $$('#piano button').forEach(key=>key.classList.toggle('expected',pitches.has(Number(key.dataset.pitch))));
}
function setFeedback(kind,title,copy,symbol) {
  $('#feedback').dataset.kind=kind;$('#feedback-title').textContent=title;$('#feedback-copy').textContent=copy;$('#feedback-symbol').textContent=symbol;
}
function resetFeedback() {
  setFeedback('ready','Make it light up.','Play a note. See how it fits the song.','♪');
  $('#matched-count').textContent='0';$('#check-count').textContent='0';$('#check-count-wrap').hidden=true;
  $('#last-note').textContent='Your piano';$('#expected-label').textContent='Up next';$('#played-label').textContent='Waiting for your first note';
  $('#input-state').textContent='Sound → notes → feedback';$('#practice-hint').textContent='Play from the beginning. The music follows you.';$('#demo-credit').hidden=true;$('#live-note').textContent='Your summary appears when you finish.';
  S.levels=Array(24).fill(0);S.level=0;renderWave();
}
function acceptPlayed(events) {
  if(S.phase!=='listening'||!events.length) return;
  const result=S.follower.feed(events);
  for(const mark of result.marks) {
    S.marks.set(mark.id,mark); const el=noteElements.get(mark.id);
    if(el) { el.classList.remove('matched','pitch','missing','provisional'); el.classList.add(mark.kind); if(mark.provisional) el.classList.add('provisional'); }
  }
  // Keep the follower's event references so a later confirmed position can also
  // resolve previously pending points in the visual trail.
  for(const played of result.played) S.played.push(Object.assign(played,{shown:performance.now()}));
  S.played=S.played.sort((a,b)=>a.time-b.time).slice(-100);
  if(result.aligned) moveCursor(result.positionBeat);
  if(result.played.length) $('#lane-empty').hidden=true;
  const latest=events.at(-1); $('#last-note').textContent=`You played ${pitchName(latest.pitch)}`;
  const checked=result.played.findLast(n=>n.kind==='pitch'),matched=result.played.findLast(n=>n.kind==='matched');
  const note=checked||matched,expected=note&&referenceNotes.get(note.id);
  if(checked&&expected) {
    const higher=checked.pitch<expected.pitch;
    setFeedback('pitch',higher?'A little higher':'A little lower',`Your note sounds ${higher?'lower':'higher'} than the song.`,higher?'↗':'↘');
  } else if(matched) setFeedback('matched',S.mode==='mic'?'Looks right':'Right note','Your playing and the song line up.','✓');
  else setFeedback('listening','Hearing you…','Keep playing while we find your place.','♪');
  $('#expected-label').textContent=expected?pitchName(expected.pitch):'Finding your place';
  $('#played-label').textContent=[...new Set(result.played.map(n=>pitchName(n.pitch)))].join(' · ');
  const marks=[...S.marks.values()];$('#matched-count').textContent=marks.filter(n=>n.kind==='matched').length;
  const checks=marks.filter(n=>n.kind==='pitch'||n.kind==='missing').length;
  $('#check-count').textContent=checks;$('#check-count-wrap').hidden=!checks;
  for(const n of result.played) if(S.mode==='mic'||!S.open.has(n.pitch))flashKey(n.pitch,n.kind);else if(n.kind==='pitch')$(`#piano [data-pitch="${n.pitch}"]`)?.classList.add('check');
  updateExpectedKeys();renderComparison();
}
function queueNote(event) {
  S.group.push(event);
  if(S.groupTimer) return;
  S.groupTimer=setTimeout(()=>{const group=S.group; S.group=[]; S.groupTimer=null; acceptPlayed(group);},35);
}
function renderComparison() {
  const played=S.played.slice(-8),preview=!played.length;
  const notes=preview?(S.score?.notes.filter(n=>n.hand==='right').slice(0,8)||[]).map(n=>({pitch:n.pitch,id:n.id})):played;
  const pitches=notes.flatMap(n=>[n.pitch,referenceNotes.get(n.id)?.pitch]).filter(Number.isFinite);
  const low=Math.min(55,...pitches)-2,high=Math.max(79,...pitches)+2;
  const y=(pitch,row)=>row+78-(pitch-low)/(high-low)*64;
  const points=notes.map((n,i)=>({n,x:22+i*44,expected:referenceNotes.get(n.id)}));
  let svg='';
  for(const row of [0,120]) for(const dy of [20,50,80])svg+=`<line class="lane-guide" x1="0" x2="360" y1="${row+dy}" y2="${row+dy}"/>`;
  for(const [i,p] of points.entries()) {
    const previous=points[i-1],expected=p.expected;
    if(expected) {
      const py=y(expected.pitch,0);
      if(previous?.expected)svg+=`<path class="lane-path" d="M${previous.x} ${y(previous.expected.pitch,0)} L${p.x} ${py}"/>`;
      svg+=`<circle class="lane-expected" cx="${p.x}" cy="${py}" r="${i===points.length-1&&!preview?7:5}"/>`;
    }
    if(!preview) {
      const py=y(p.n.pitch,120),kind=['matched','pitch'].includes(p.n.kind)?p.n.kind:'unknown';
      if(previous)svg+=`<path class="lane-path" d="M${previous.x} ${y(previous.n.pitch,120)} L${p.x} ${py}" ${kind==='pitch'?'style="stroke:var(--coral)"':''}/>`;
      if(kind==='pitch'&&expected)svg+=`<line x1="${p.x}" x2="${p.x}" y1="${y(expected.pitch,120)}" y2="${py}" stroke="var(--coral)" stroke-dasharray="2 3"/><circle class="lane-expected" cx="${p.x}" cy="${y(expected.pitch,120)}" r="5" style="opacity:.5"/>`;
      svg+=`<circle class="lane-played ${kind} ${i===points.length-1?'current':''}" cx="${p.x}" cy="${py}" r="8"/>`;
      if(kind==='matched')svg+=`<text class="lane-match-symbol" x="${p.x}" y="${py+3.5}" text-anchor="middle">✓</text>`;
      if(kind==='pitch')svg+=`<text class="lane-match-symbol" x="${p.x}" y="${py+3.5}" text-anchor="middle">${expected&&p.n.pitch<expected.pitch?'↑':'↓'}</text>`;
    }
  }
  $('#lane-notes').innerHTML=svg;
}
function renderWave() {
  $('#sound-wave').innerHTML=S.levels.map((v,i)=>{const h=2+Math.min(22,v*22);return `<rect x="${i*4.2}" y="${13-h/2}" width="2" height="${h}" rx="1" fill="currentColor" opacity="${.25+i/32}"/>`;}).join('');
}
function drawLane() {
  if(S.phase!=='listening') return;
  const now=performance.now();
  if(!S.lastMeter||now-S.lastMeter>45){S.lastMeter=now;S.levels.push(S.level);S.levels.shift();renderWave();}
  S.raf=requestAnimationFrame(drawLane);
}
function paintKey(pitch,on) { const key=$(`#piano [data-pitch="${pitch}"]`);if(key){key.classList.toggle('down',on);if(!on)key.classList.remove('check');} }
function flashKey(pitch,kind) {
  clearTimeout(S.keyTimers.get(pitch));paintKey(pitch,true);
  $(`#piano [data-pitch="${pitch}"]`)?.classList.toggle('check',kind==='pitch');
  S.keyTimers.set(pitch,setTimeout(()=>{paintKey(pitch,false);S.keyTimers.delete(pitch);},260));
}
function synth(pitch,on) {
  if(!on) { const voice=S.voices.get(pitch); if(voice){voice.gain.gain.setTargetAtTime(.0001,voice.ctx.currentTime,.08);voice.osc.stop(voice.ctx.currentTime+.5);S.voices.delete(pitch);} return; }
  synth(pitch,false); const ctx=S.context; if(!ctx)return;
  const osc=ctx.createOscillator(),gain=ctx.createGain(); osc.type='triangle';osc.frequency.value=440*Math.pow(2,(pitch-69)/12);gain.gain.setValueAtTime(.0001,ctx.currentTime);gain.gain.exponentialRampToValueAtTime(.12,ctx.currentTime+.012);gain.gain.exponentialRampToValueAtTime(.045,ctx.currentTime+.3);osc.connect(gain).connect(ctx.destination);osc.start();S.voices.set(pitch,{osc,gain,ctx});
}
function inputNote(pitch,on,velocity=90,scheduledTime) {
  if(S.phase!=='listening')return;
  const time=scheduledTime??(performance.now()-S.started)/1000;
  if(on&&S.open.has(pitch)) inputNote(pitch,false,0);
  S.events.push({t:time*1000,on,pitch,velocity});
  if(on) {S.open.set(pitch,time);queueNote({pitch,time,velocity});} else S.open.delete(pitch);
  paintKey(pitch,on);S.level=on?velocity/127:(S.open.size ? 0.5 : 0); $('#level').style.width=`${S.level*100}%`;
  if(S.mode==='keys')synth(pitch,on);
}
function renderPiano() {
  const pitches=Array.from({length:37},(_,i)=>i+48),whiteCount=pitches.filter(p=>![1,3,6,8,10].includes(p%12)).length; let white=0;
  for(const pitch of pitches){ const black=[1,3,6,8,10].includes(pitch%12),key=document.createElement('button');key.type='button';key.dataset.pitch=pitch;key.className=black?'black':'';key.disabled=true;key.setAttribute('aria-label',`Play ${pitchName(pitch)}`);
    if(black)key.style.left=`calc(${white/whiteCount*100}% - 1.5%)`;else{white++;key.textContent=pitch%12===0?pitchName(pitch):'';}
    key.addEventListener('pointerdown',ev=>{if(key.disabled)return;ev.preventDefault();key.setPointerCapture(ev.pointerId);inputNote(pitch,true);});
    for(const event of ['pointerup','pointercancel','lostpointercapture'])key.addEventListener(event,()=>{if(S.open.has(pitch))inputNote(pitch,false);});
    key.addEventListener('keydown',ev=>{if([' ','Enter'].includes(ev.key)&&!ev.repeat){ev.preventDefault();inputNote(pitch,true);}});key.addEventListener('keyup',ev=>{if([' ','Enter'].includes(ev.key)){ev.preventDefault();inputNote(pitch,false);}});$('#piano').append(key);
  }

}
async function loadPiece() {
  const load=++pieceLoad; $('#start').disabled=true;$('#demo').disabled=true;message('');setStatus('Loading the score…');
  try{const res=await fetch(`/api/practice/score/${encodeURIComponent($('#piece').value)}`);const data=await res.json();if(!res.ok)throw Error(data.error||'Could not load this score.');if(load!==pieceLoad)return;S.score=data;S.follower=null;S.played=[];S.marks.clear();resetFeedback();$('#summary').hidden=true;$('#live-view').hidden=false;$('#lane-empty').hidden=false;$('#latency').textContent='';drawScore();phase('idle');setStatus('Choose an input, then start.');}
  catch(error){if(load===pieceLoad){S.score=null;phase('idle');message(error.message);setStatus('Score unavailable.');}}
}
function encodeWav(samples,rate){const data=new ArrayBuffer(44+samples.length*2),view=new DataView(data);const ascii=(offset,text)=>{for(let i=0;i<text.length;i++)view.setUint8(offset+i,text.charCodeAt(i));};ascii(0,'RIFF');view.setUint32(4,data.byteLength-8,true);ascii(8,'WAVE');ascii(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,rate,true);view.setUint32(28,rate*2,true);view.setUint16(32,2,true);view.setUint16(34,16,true);ascii(36,'data');view.setUint32(40,samples.length*2,true);for(let i=0;i<samples.length;i++){const v=Math.max(-1,Math.min(1,samples[i]));view.setInt16(44+i*2,v<0?v*32768:v*32767,true);}return new Blob([data],{type:'audio/wav'});}
async function sendWindow() {
  if(S.phase!=='listening'||S.mode!=='mic'||S.requestBusy||!S.pcm.length)return;
  const end=S.pcm.at(-1).time+S.pcm.at(-1).samples.length/S.sampleRate;
  if(end<MIC.first||end-S.lastRequest<MIC.cadence)return;
  const start=Math.max(0,end-MIC.context),samples=new Float32Array(Math.round((end-start)*S.sampleRate));
  for(const chunk of S.pcm){const offset=Math.round((chunk.time-start)*S.sampleRate),from=Math.max(0,-offset),to=Math.min(chunk.samples.length,samples.length-offset);if(to>from)samples.set(chunk.samples.subarray(from,to),Math.max(0,offset));}
  S.lastRequest=end;S.requestBusy=true;const token=S.token,form=new FormData();form.append('audio',encodeWav(samples,S.sampleRate),'window.wav');
  try{const res=await fetch('/api/practice/notes',{method:'POST',body:form,signal:AbortSignal.timeout(20000)});if(res.status===503)return;const data=await res.json();if(!res.ok)throw Error(data.error||'Live listening is unavailable.');if(token!==S.token||S.phase!=='listening')return;
    const batch=S.noteStream.ingest(data.notes,{start,end});
    for(const n of batch.late)S.played.push({...n,kind:'unplaced',provisional:true,shown:performance.now()});
    acceptPlayed(batch.events);
    if(batch.events.length){
      // Measure capture onset → visible feedback, including input buffering,
      // request scheduling and network time, rather than model compute alone.
      const capturedNow=S.context.currentTime-S.audioOrigin;
      for(const n of batch.events)S.lag.push(Math.max(0,capturedNow-n.time)*1000);
      S.lag=S.lag.slice(-20);const ordered=S.lag.slice().sort((a,b)=>a-b);
      $('#latency').textContent=`~${Math.round(ordered[Math.floor(ordered.length/2)])} ms`;
      $('#latency').dataset.lastLagMs=String(Math.round(Math.max(0,capturedNow-batch.events.at(-1).time)*1000));
    }
    $('#input-state').textContent=S.level>.015?'Hearing your piano':'Listening for notes';

  }catch(error){if(token===S.token&&S.phase==='listening'){ $('#latency').textContent='Live marks unavailable';message('Live listening could not keep up. Your recording is still being saved for the final review.'); }}
  finally{if(token===S.token){S.requestBusy=false;void sendWindow();}}
}
async function connectMic() {
  S.stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:false,noiseSuppression:false,autoGainControl:false},video:false});
  S.context=new AudioContext({sampleRate:22050});await S.context.resume();S.sampleRate=S.context.sampleRate;
  await S.context.audioWorklet.addModule('/practice-assets/live-audio-worklet.js');
  S.source=S.context.createMediaStreamSource(S.stream);S.worklet=new AudioWorkletNode(S.context,'practice-capture');S.mute=S.context.createGain();S.mute.gain.value=0;
  S.audioOrigin=S.context.currentTime;S.worklet.port.onmessage=({data})=>{if(S.phase!=='listening')return;const time=Math.max(0,data.frame/S.sampleRate-S.audioOrigin);S.pcm.push({time,samples:data.samples});S.pcm=S.pcm.filter(c=>c.time>time-MIC.context-.2);let energy=0;for(const v of data.samples)energy+=v*v;S.level=Math.min(1,Math.sqrt(energy/data.samples.length)*8);$('#level').style.width=`${S.level*100}%`;void sendWindow();};
  S.source.connect(S.worklet).connect(S.mute).connect(S.context.destination);
  S.chunks=[];S.recorder=new MediaRecorder(S.stream);S.recorder.addEventListener('dataavailable',event=>{if(event.data.size)S.chunks.push(event.data);});S.recorder.start(1000);
  for(const track of S.stream.getAudioTracks())track.addEventListener('ended',()=>{if(S.phase==='listening'){message('The microphone disconnected. Finishing this take.');void finish();}});
}
async function connectMidi() {
  if(!navigator.requestMIDIAccess)throw Error('This browser does not support MIDI. Open this page in Chrome.');
  S.midi=await navigator.requestMIDIAccess({sysex:false});
  const inputs=[...S.midi.inputs.values()].filter(i=>i.state==='connected');if(!inputs.length)throw Error('No MIDI keyboard found. Connect it by USB, then press Start again.');
  for(const input of inputs)input.onmidimessage=event=>{const [status,pitch,velocity]=event.data,kind=status&0xf0;if(kind===0x90||kind===0x80)inputNote(pitch,kind===0x90&&velocity>0,velocity);};
  S.midi.onstatechange=()=>{if(S.phase==='listening'&&![...S.midi.inputs.values()].some(i=>i.state==='connected')){message('The keyboard disconnected. Finishing this take.');void finish();}};
}
async function prepareDemo() {
  const plan=PracticeDemo.build(S.score),context=new AudioContext();S.context=context;await context.resume();
  const buffers=new Map();
  await Promise.all([...new Set(plan.notes.map(n=>n.pitch))].map(async pitch=>{
    let bytes=pianoCache.get(pitch);
    if(!bytes){const response=await fetch(`/api/practice/piano/${pitch}`,{signal:AbortSignal.timeout(10000)});if(!response.ok)throw Error('Could not load the demo piano. Try again.');bytes=await response.arrayBuffer();pianoCache.set(pitch,bytes);}
    buffers.set(pitch,await context.decodeAudioData(bytes.slice(0)));
  }));
  const timeline=plan.notes.flatMap(n=>[{time:n.time,on:true,pitch:n.pitch,velocity:n.velocity},{time:n.time+n.length,on:false,pitch:n.pitch,velocity:0}]).sort((a,b)=>a.time-b.time||Number(a.on)-Number(b.on));
  S.demo={plan,buffers,timeline,index:0,sources:new Set(),timer:null,origin:0};
}
function beginDemo() {
  const demo=S.demo,ctx=S.context;demo.origin=ctx.currentTime;
  // Audio uses the hardware clock; visual/MIDI events retain those same times
  // even if a background browser tab delays an animation frame.
  for(const note of demo.plan.notes){
    const source=ctx.createBufferSource(),gain=ctx.createGain(),at=demo.origin+note.time;
    source.buffer=demo.buffers.get(note.pitch);const volume=.40*Math.pow(note.velocity/127,1.2);
    gain.gain.setValueAtTime(.0001,at);gain.gain.linearRampToValueAtTime(volume,at+.008);
    gain.gain.setValueAtTime(volume,at+Math.max(.009,note.length-.04));gain.gain.exponentialRampToValueAtTime(.0001,at+note.length+.12);
    source.connect(gain).connect(ctx.destination);source.start(at);source.stop(at+note.length+.16);demo.sources.add(source);source.onended=()=>{demo.sources.delete(source);source.disconnect();gain.disconnect();};
  }
  $('#practice-hint').textContent=`A ${Math.round(demo.plan.duration)}-second example with ${demo.plan.changes.length} intentional ${demo.plan.changes.length===1?'mistake':'mistakes'}. Watch the notes light up.`;
  $('#live-note').textContent='Sample performance. Same live feedback. No microphone needed.';$('#demo-credit').hidden=false;
  $('#input-state').textContent='Demo piano';setStatus('Demo playing · the summary follows automatically.');
  demo.timer=setInterval(()=>{
    if(S.phase!=='listening'||S.mode!=='demo')return;
    const time=ctx.currentTime-demo.origin;
    while(demo.index<demo.timeline.length&&demo.timeline[demo.index].time<=time){const event=demo.timeline[demo.index++];inputNote(event.pitch,event.on,event.velocity,event.time);}
    $('#clock').textContent=`${formatTime(Math.min(time,demo.plan.duration))} / ${formatTime(demo.plan.duration)}`;
    if(time>=demo.plan.duration){S.demoCompleted=true;void finish();}
  },20);
}
async function start() {
  if(!S.score)return;message('');S.token++;S.mode=$('#input-mode').value;phase('starting');
  S.events=[];S.open.clear();S.marks.clear();S.played=[];S.group=[];S.pcm=[];S.lastRequest=0;S.requestBusy=false;S.position=0;S.demoCompleted=false;S.lag=[];S.noteStream=new LiveNoteStream();resetFeedback();
  S.follower=new LiveScoreFollower(S.score.notes,{bpm:S.score.piece.bpm,input:S.mode==='mic'?'mic':'midi'});drawScore();$('#summary').hidden=true;$('#live-view').hidden=false;$('#lane-empty').hidden=false;$('#lane-notes').innerHTML='';$('#latency').textContent='';$('#live-note').textContent=S.mode==='mic'?'Live hints. Your recording is checked again when you finish.':'Your summary appears when you finish.';renderComparison();
  try{if(S.mode==='mic')await connectMic();else if(S.mode==='midi')await connectMidi();else if(S.mode==='demo')await prepareDemo();else{S.context=new AudioContext();await S.context.resume();}
    S.started=performance.now();phase('listening');setStatus('Play from the beginning. Finish for your summary.');$('#input-state').textContent=S.mode==='mic'?'Listening for notes':'Keyboard connected';$('#clock').textContent='0:00';if(S.mode==='demo')beginDemo();else S.clockTimer=setInterval(()=>$('#clock').textContent=formatTime((performance.now()-S.started)/1000),250);drawLane();
  }catch(error){await cleanup();phase('idle');setStatus('Ready when you are.');message(error.message);}
}
async function cleanup() {
  if(S.demo){clearInterval(S.demo.timer);for(const source of S.demo.sources){source.stop();source.disconnect();}S.demo=null;}
  for(const timer of S.keyTimers.values())clearTimeout(timer);S.keyTimers.clear();S.level=0;
  clearInterval(S.clockTimer);clearTimeout(S.groupTimer);S.groupTimer=null;cancelAnimationFrame(S.raf);
  if(S.stream){S.stream.getTracks().forEach(t=>t.stop());S.stream=null;}
  if(S.midi){for(const input of S.midi.inputs.values())input.onmidimessage=null;S.midi.onstatechange=null;}
  S.worklet?.disconnect();S.source?.disconnect();S.mute?.disconnect();S.worklet=null;S.source=null;S.mute=null;
  for(const pitch of S.voices.keys())synth(pitch,false);if(S.context){await S.context.close();S.context=null;}
  $$('#piano button').forEach(b=>b.classList.remove('down','check'));$('#level').style.width='0%';
}
function encodeMidi(events){const bytes=[0,255,81,3,7,161,32],vlq=value=>{const out=[value&127];while((value>>=7)>0)out.unshift((value&127)|128);return out;},u32=n=>[(n>>>24)&255,(n>>>16)&255,(n>>>8)&255,n&255];let last=0;for(const e of events.slice().sort((a,b)=>a.t-b.t)){const tick=Math.round(e.t*.96);bytes.push(...vlq(Math.max(0,tick-last)),e.on?144:128,e.pitch,e.on?Math.max(1,e.velocity):0);last=tick;}bytes.push(0,255,47,0);return new Blob([new Uint8Array([77,84,104,100,...u32(6),0,0,0,1,1,224,77,84,114,107,...u32(bytes.length),...bytes])],{type:'audio/midi'});}
async function finish() {
  if(S.phase!=='listening')return;
  for(const pitch of [...S.open.keys()])inputNote(pitch,false,0);
  if(S.group.length){acceptPlayed(S.group);S.group=[];}
  const elapsed=(performance.now()-S.started)/1000;phase('finishing');S.token++;message('');setStatus('Preparing your summary…');let file;
  try{
    if(S.mode==='mic'){const recorder=S.recorder;await new Promise(resolve=>{recorder.addEventListener('stop',resolve,{once:true});recorder.stop();});const type=recorder.mimeType||'audio/webm';file=new File(S.chunks,`take.${type.includes('mp4')?'m4a':'webm'}`,{type});}
    else if(S.events.some(e=>e.on))file=new File([encodeMidi(S.events)],'take.mid',{type:'audio/midi'});
    await cleanup();
    if(!file){showSummary({detectedNotes:0,errors:[],completed:false,reachedMeasure:null},elapsed);return;}
    const form=new FormData();form.append('piece',$('#piece').value);form.append('performance',file);form.append('hands','both');if(S.mode==='keys'||S.mode==='demo')form.append('explain','0');
    const response=await fetch('/api/analyze',{method:'POST',body:form,signal:AbortSignal.timeout(180000)});const result=await response.json();if(!response.ok)throw Error(result.error||'Could not finish the review.');
    const summaryResponse=await fetch(`/api/practice/summary/${encodeURIComponent(result.id)}`,{signal:AbortSignal.timeout(30000)});const summary=await summaryResponse.json();if(!summaryResponse.ok)throw Error(summary.error||'Could not load the summary.');
    showSummary(summary,elapsed);
  }catch(error){await cleanup();phase('review');setStatus('Take ended.');message(error.name==='TimeoutError'?'The review took too long. Your take is available to save below.':error.message);showLocalSummary(elapsed,file);}
}
function showSummary(data,elapsed) {
  phase('review');$('#live-view').hidden=true;$('#summary').hidden=false;$('#summary-duration').textContent=formatTime(elapsed);$('#summary-title').textContent=S.mode==='demo'?(S.demoCompleted?'Demo complete':'Demo stopped'):data.completed?'Take complete':'Your take';
  const errors=data.errors||[],heard=data.detectedNotes>0,counts=new Map();for(const e of errors)counts.set(e.category,(counts.get(e.category)||0)+1);
  $('#summary-copy').textContent=!heard?'No notes were detected. Check your input and try again.':typeof data.coach==='string'&&data.coach?data.coach:data.reachedMeasure?`${data.completed?'Completed':'Played through'} bar ${data.reachedPrintedMeasure??data.reachedMeasure}. ${errors.length?`${errors.length} ${errors.length===1?'place':'places'} to revisit.`:'No findings in the completed passage.'}`:'There wasn’t enough of the piece to align this take. Try a longer phrase.';
  const names={wrong_pitch:'Different key',missing:'Skipped note',extra:'Extra note',timing:'Early or late',duration:'Held too long or short',unsure:'Worth another listen'};
  $('#summary-counts').innerHTML=[...counts].slice(0,3).map(([key,count])=>`<div class="summary-stat"><strong>${count}</strong><span>${names[key]||escape(key)}</span></div>`).join('');
  $('#summary-findings').innerHTML=errors.slice(0,3).map(e=>`<div class="finding"><small>BAR ${e.measure} · ${names[e.category]||'Check'}</small><p>${escape(e.explanation)}</p>${e.tip?`<p class="tip">${escape(e.tip)}</p>`:''}</div>`).join('');
  const report=$('#report-link');report.hidden=!data.completed||!data.reportUrl;report.removeAttribute('download');report.textContent='Open full review ↗';if(data.reportUrl)report.href=data.reportUrl;setStatus(S.mode==='demo'?'Demo finished. Replay or choose your instrument.':'Finished. Ready for another take.');
}
let recoveryUrl=null;
function showLocalSummary(elapsed,file) {$('#live-view').hidden=true;$('#summary').hidden=false;$('#summary-title').textContent='Take ended';$('#summary-duration').textContent=formatTime(elapsed);$('#summary-copy').textContent='The final review couldn’t finish. The marks on the score are still provisional.';$('#summary-counts').innerHTML='';$('#summary-findings').innerHTML='';const link=$('#report-link');link.hidden=!file;if(file){if(recoveryUrl)URL.revokeObjectURL(recoveryUrl);recoveryUrl=URL.createObjectURL(file);link.href=recoveryUrl;link.download=file.name;link.textContent='Save your take ↓';}}
$('#start').addEventListener('click',()=>{if(S.phase==='listening')void finish();else void start();});
$('#demo').addEventListener('click',()=>{if(S.phase==='listening'&&S.mode==='demo')void finish();else if(!['listening','starting','finishing'].includes(S.phase)){$('#input-mode').value='demo';void start();}});
$('#piece').addEventListener('change',loadPiece);
$('#input-mode').addEventListener('change',()=>{S.mode=$('#input-mode').value;phase(S.phase);$('#keyboard-help').textContent=$('#input-mode').value==='keys'?'Click the outlined keys after starting':'Outlined = next · Lit up = you';});
$('#follow').addEventListener('click',()=>{S.follow=!S.follow;$('#follow').setAttribute('aria-pressed',String(S.follow));if(S.follow&&S.phase==='listening')moveCursor(S.position);});
$('#score').addEventListener('keydown',event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const el=$('#score');el.scrollLeft=event.key==='Home'?0:event.key==='End'?el.scrollWidth:el.scrollLeft+(event.key==='ArrowRight'?210:-210);}});
new ResizeObserver(()=>{if(S.phase==='listening'&&S.follow)moveCursor(S.position);}).observe($('#score'));
window.addEventListener('pagehide',()=>{S.phase='idle';void cleanup();});
renderPiano();resetFeedback();
(async()=>{try{const response=await fetch('/api/pieces');if(!response.ok)throw Error('Could not load the pieces.');const pieces=await response.json();if(!pieces.length)throw Error('No scores are available.');$('#piece').innerHTML=pieces.map(p=>`<option value="${escape(p.id)}">${escape(p.title)}</option>`).join('');const want=new URLSearchParams(location.search).get('piece');if(want&&pieces.some(p=>p.id===want))$('#piece').value=want;await loadPiece();}catch(error){message(error.message);setStatus('Could not open the practice room.');}})();
})();
