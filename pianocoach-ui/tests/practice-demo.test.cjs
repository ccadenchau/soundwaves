'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const PracticeDemo = require('../practice/practice-demo.js');
const LiveScoreFollower = require('../practice/live-matcher.js');

// First eight bars from the project's converted minuet_in_g score endpoint.
// Embedded here so the real-score regression does not require a running server.
const minuetRows = [
  ['n000258',55,0,2,1,1,'L'],['n000259',59,0,2,1,1,'L'],['n000260',62,0,2,1,1,'L'],['n000000',74,0,1,1,1,'R'],['n000001',67,1,.5,1,2,'R'],['n000002',69,1.5,.5,1,2.5,'R'],['n000261',57,2,1,1,3,'L'],['n000003',71,2,.5,1,3,'R'],['n000004',72,2.5,.5,1,3.5,'R'],
  ['n000262',59,3,3,2,1,'L'],['n000005',74,3,1,2,1,'R'],['n000006',67,4,1,2,2,'R'],['n000007',67,5,1,2,3,'R'],
  ['n000263',60,6,3,3,1,'L'],['n000008',76,6,1,3,1,'R'],['n000009',72,7,.5,3,2,'R'],['n000010',74,7.5,.5,3,2.5,'R'],['n000011',76,8,.5,3,3,'R'],['n000012',78,8.5,.5,3,3.5,'R'],
  ['n000264',59,9,3,4,1,'L'],['n000013',79,9,1,4,1,'R'],['n000014',67,10,1,4,2,'R'],['n000015',67,11,1,4,3,'R'],
  ['n000265',57,12,3,5,1,'L'],['n000016',72,12,1,5,1,'R'],['n000017',74,13,.5,5,2,'R'],['n000018',72,13.5,.5,5,2.5,'R'],['n000019',71,14,.5,5,3,'R'],['n000020',69,14.5,.5,5,3.5,'R'],
  ['n000266',55,15,3,6,1,'L'],['n000021',71,15,1,6,1,'R'],['n000022',72,16,.5,6,2,'R'],['n000023',71,16.5,.5,6,2.5,'R'],['n000024',69,17,.5,6,3,'R'],['n000025',67,17.5,.5,6,3.5,'R'],
  ['n000267',62,18,1,7,1,'L'],['n000026',66,18,1,7,1,'R'],['n000268',59,19,1,7,2,'L'],['n000027',67,19,.5,7,2,'R'],['n000028',69,19.5,.5,7,2.5,'R'],['n000269',55,20,1,7,3,'L'],['n000029',71,20,.5,7,3,'R'],['n000030',67,20.5,.5,7,3.5,'R'],
  ['n000270',62,21,1,8,1,'L'],['n000031',71,21,1,8,1,'R'],['n000271',50,22,.5,8,2,'L'],['n000032',69,22,2,8,2,'R'],['n000272',60,22.5,.5,8,2.5,'L'],['n000273',59,23,.5,8,3,'L'],['n000274',57,23.5,.5,8,3.5,'L']
];
function minuet() {
  return {piece: {bpm:126,time_signature:[3,4]}, totalBeats:27,
    bars:Array.from({length:9},(_,i)=>({measure:i+1,startBeat:i*3,endBeat:i*3+3})),
    notes:[...minuetRows.map(([id,pitch,beat,duration,measure,beatInMeasure,hand])=>({id,pitch,beat,duration,measure,beatInMeasure,hand:hand==='R'?'right':'left'})),
      {id:'unplayed-ninth-bar',pitch:74,beat:24,duration:1,measure:9,beatInMeasure:1,hand:'right'}]};
}

test('real Minuet creates exactly the intended two pitch changes and omission', () => {
  const score=minuet(), before=JSON.stringify(score), demo=PracticeDemo.build(score);
  assert.equal(JSON.stringify(score),before);
  assert.deepEqual(demo.changes.map(({id,expected,actual,kind,measure})=>({id,expected,actual,kind,measure})),[
    {id:'n000005',expected:74,actual:75,kind:'pitch',measure:2},
    {id:'n000012',expected:78,actual:77,kind:'pitch',measure:3},
    {id:'n000016',expected:72,actual:undefined,kind:'missing',measure:5}
  ]);
  assert.equal(demo.notes.length,minuetRows.length-1);
  assert.ok(demo.notes.every(note=>note.measure<=8));
  assert.equal(demo.bpm,104);
  assert.equal(demo.notes[0].time,.7);
  assert.equal(demo.endBeat,24);
  assert.ok(Math.abs(demo.duration-(.7+24*60/104+.6))<1e-8);
  assert.ok(demo.notes.every(note=>note.time+note.length<demo.duration));
});

test('real-score demo yields three confirmed findings and no unplayed-suffix findings', () => {
  const score=minuet(), demo=PracticeDemo.build(score), follower=new LiveScoreFollower(score.notes,{bpm:demo.bpm,input:'midi'});
  const marks=new Map(), groups=new Map();
  for(const note of demo.notes){if(!groups.has(note.time))groups.set(note.time,[]);groups.get(note.time).push({pitch:note.pitch,time:note.time,velocity:note.velocity});}
  for(const events of groups.values())for(const mark of follower.feed(events).marks)marks.set(mark.id,mark);
  const findings=[...marks.values()].filter(mark=>mark.kind!=='matched');
  assert.equal(findings.length,3);
  assert.ok(findings.every(mark=>!mark.provisional));
  assert.deepEqual(new Set(findings.map(mark=>mark.id)),new Set(demo.changes.map(change=>change.id)));
  assert.equal(findings.filter(mark=>mark.kind==='pitch').length,2);
  assert.equal(findings.filter(mark=>mark.kind==='missing').length,1);
  assert.equal(marks.has('unplayed-ninth-bar'),false);
  assert.deepEqual(follower.feed([]).marks,[]);
  assert.equal(marks.size,minuetRows.length);
});

test('building twice is deterministic and does not require the score tempo', () => {
  const score=minuet(); delete score.piece.bpm;
  assert.deepEqual(PracticeDemo.build(score),PracticeDemo.build(score));
});

test('short scores remain playable without manufacturing three errors', () => {
  const score={notes:[{id:'only',pitch:60,beat:0,duration:1,measure:1,hand:'right'}]};
  const demo=PracticeDemo.build(score);
  assert.equal(demo.notes.length,1);
  assert.deepEqual(demo.changes,[]);
  assert.equal(demo.notes[0].pitch,60);
  assert.ok(demo.duration>demo.notes[0].time+demo.notes[0].length);
});

test('notes at the end cannot be selected as unconfirmable mistakes', () => {
  const score={notes:[{id:'a',pitch:60,beat:0,duration:1,measure:1,hand:'right'},
    {id:'last',pitch:78,beat:1,duration:1,measure:3,hand:'right'}]};
  assert.deepEqual(PracticeDemo.build(score).changes,[]);
});

test('unknown hands do not receive invented right-hand mistakes', () => {
  const score=minuet(); score.notes.forEach(note=>delete note.hand);
  assert.deepEqual(PracticeDemo.build(score).changes,[]);
});

test('malformed and empty scores fail clearly', () => {
  assert.throws(()=>PracticeDemo.build(null),/Choose a score/);
  assert.throws(()=>PracticeDemo.build({notes:[]}),/Choose a score/);
  const score=minuet(); score.notes[0].pitch=130;
  assert.throws(()=>PracticeDemo.build(score),/valid pitches/);
  const duplicate=minuet(); duplicate.notes[1].id=duplicate.notes[0].id;
  assert.throws(()=>PracticeDemo.build(duplicate),/unique IDs/);
  const bars=minuet();bars.bars[1].endBeat=1;
  assert.throws(()=>PracticeDemo.build(bars),/beat ranges/);
});

test('browser UMD and Node expose the same build API', () => {
  const context=vm.createContext({});vm.runInContext(fs.readFileSync(require.resolve('../practice/practice-demo.js'),'utf8'),context);
  assert.equal(typeof context.PracticeDemo.build,'function');
  assert.equal(typeof PracticeDemo.build,'function');
});
