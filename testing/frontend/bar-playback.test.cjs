const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

function playback(){
 const audio=new EventTarget();Object.assign(audio,{currentTime:0,playbackRate:1,paused:true,src:'/take.wav'});
 audio.play=()=>{audio.paused=false;audio.dispatchEvent(new Event('play'));return Promise.resolve();};
 audio.pause=()=>{audio.paused=true;audio.dispatchEvent(new Event('pause'));};
 const button=(time,end)=>{const el=new EventTarget();el.dataset={time:String(time)};if(end!==undefined)el.dataset.end=String(end);el.hasAttribute=name=>name==='data-end'&&end!==undefined;return el;};
 const first=button(2,4),second=button(4,6),finding=button(8),delays=[];
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../frontend/static/bar-playback.js'),'utf8'),{
  document:{getElementById:()=>audio,querySelectorAll:()=>[first,second,finding]},
  setTimeout:(fn,delay)=>{delays.push(delay);return delays.length;},clearTimeout(){},
 });
 return{audio,first,second,finding,delays};
}

test('speaker playback pauses at the selected bar end',async()=>{
 const p=playback();p.first.dispatchEvent(new Event('click'));await new Promise(setImmediate);
 assert.equal(p.audio.currentTime,2);assert.equal(p.audio.paused,false);
 p.audio.currentTime=4.02;p.audio.dispatchEvent(new Event('timeupdate'));
 assert.equal(p.audio.paused,true);assert.equal(p.audio.currentTime,4);
});

test('another bar replaces the previous preview and stopping respects playback speed',async()=>{
 const p=playback();p.first.dispatchEvent(new Event('click'));p.second.dispatchEvent(new Event('click'));await new Promise(setImmediate);
 p.audio.currentTime=4.2;p.audio.dispatchEvent(new Event('timeupdate'));assert.equal(p.audio.paused,false);
 p.audio.playbackRate=.5;p.audio.dispatchEvent(new Event('ratechange'));
 assert.ok(Math.abs(p.delays.at(-1)-3600)<1);
 p.audio.currentTime=6;p.audio.dispatchEvent(new Event('timeupdate'));assert.equal(p.audio.paused,true);
});

test('ordinary finding seeks and a source switch clear the bar limit',async()=>{
 const p=playback();p.first.dispatchEvent(new Event('click'));p.finding.dispatchEvent(new Event('click'));await new Promise(setImmediate);
 p.audio.currentTime=9;p.audio.dispatchEvent(new Event('timeupdate'));assert.equal(p.audio.paused,false);
 p.first.dispatchEvent(new Event('click'));await new Promise(setImmediate);
 p.audio.src='/midi.wav';p.audio.dispatchEvent(new Event('loadstart'));
 p.audio.currentTime=5;p.audio.dispatchEvent(new Event('timeupdate'));assert.equal(p.audio.paused,false);
});

test('initial media loading does not erase a requested bar preview',async()=>{
 const p=playback();p.first.dispatchEvent(new Event('click'));p.audio.dispatchEvent(new Event('loadstart'));await new Promise(setImmediate);
 p.audio.currentTime=4;p.audio.dispatchEvent(new Event('timeupdate'));assert.equal(p.audio.paused,true);
});
