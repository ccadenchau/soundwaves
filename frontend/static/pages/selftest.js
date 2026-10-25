const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const CASES=JSON.parse(document.getElementById('selftest-cases').textContent);
const chips=(label,value,cls='')=>`<span class="chip ${cls}">${label} <b>${esc(value)}</b></span>`;
async function status(){
  const s=await (await fetch('/api/selftest/status')).json();
  const base=chips('Transcriber',s.transcriber==='transkun'?'Transkun (best)':'Basic Pitch (install Transkun for better results)',s.transcriber==='transkun'?'good':'warn')+chips('Explanations',s.explainer,s.explainer_key?'good':'')+chips('Piece',s.piece);
  const extra={};const draw=()=>{$('#chips').innerHTML=base+Object.values(extra).join('');};draw();
  const wait=(p,ms)=>Promise.race([p,new Promise((_,no)=>setTimeout(()=>no(Error('timeout')),ms))]);
  (async()=>{try{const m=await wait(navigator.requestMIDIAccess(),4000);const n=[...m.inputs.values()].length;extra.midi=chips('MIDI keyboards',n?`${n} connected`:'none found',n?'good':'');}catch(e){extra.midi=chips('MIDI keyboards','not allowed or not available');}draw();})();
  (async()=>{try{const p=await navigator.permissions.query({name:'microphone'});extra.mic=chips('Microphone',p.state,p.state==='granted'?'good':p.state==='denied'?'warn':'');draw();}catch(e){}})();
}
function renderResult(el,r){
  const state=el.querySelector('.state');state.className='state '+(r.ok?'pass':'fail');
  state.textContent=(r.ok?'PASS':'FAIL')+` · ${r.seconds} s`+(r.transcriber&&r.transcriber!=='n/a'?` · ${r.transcriber}`:'');
  el.querySelector('ul').innerHTML=r.checks.map(c=>`<li><span class="mark ${c.ok?'ok':c.required?'no':'warn'}">${c.ok?'✓':c.required?'✗':'!'}</span><span>${esc(c.label)} <span class="detail">· ${esc(c.detail)}</span></span></li>`).join('');
  const link=el.querySelector('.open');link.hidden=!r.url;if(r.url)link.href=r.url;
}
async function run(kind){
  const el=$('#case-'+kind),btn=el.querySelector('button'),state=el.querySelector('.state');
  btn.disabled=true;state.className='state';state.textContent='Running… the first run renders the piano take and takes a bit longer';el.querySelector('ul').innerHTML='';
  try{const res=await fetch('/api/selftest/run/'+kind,{method:'POST'});const r=await res.json();if(!res.ok)throw Error(r.error||'failed');renderResult(el,r);return r.ok;}
  catch(e){state.className='state fail';state.textContent='FAIL · '+e.message;return false;}
  finally{btn.disabled=false;}
}
$('#cases').innerHTML=Object.entries(CASES).map(([k,c])=>`<div class="card" id="case-${k}"><h2>${esc(c.title)}</h2><p>${esc(c.text)}</p><div class="row"><button onclick="run('${k}')">Run</button><span class="state">Not run yet</span><a class="open" hidden target="_blank">Open the result ↗</a></div><ul class="checks"></ul></div>`).join('');
$('#all').onclick=async()=>{$('#all').disabled=true;let pass=0;for(const k of Object.keys(CASES))if(await run(k))pass++;$('#all').textContent=`${pass} of ${Object.keys(CASES).length} passed · run again`;$('#all').disabled=false;};
$('#own').onsubmit=async e=>{e.preventDefault();const s=$('#own-state');s.textContent='Listening to your take…';try{const res=await fetch('/api/analyze',{method:'POST',body:new FormData(e.target)});const d=await res.json();if(!res.ok)throw Error(d.error||'Analysis failed.');location.href=d.url;}catch(err){s.className='state fail';s.textContent=err.message;}};
window.run=run;status();
