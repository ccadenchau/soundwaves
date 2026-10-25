const $=s=>document.querySelector(s);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
$('#strength').oninput=e=>$('#sv').textContent=e.target.value;
function roll(notes,dur,marks){
  if(!notes.length)return '<p class="dim">No notes detected.</p>';
  const lo=Math.min(...notes.map(n=>n.p))-2,hi=Math.max(...notes.map(n=>n.p))+2,W=940,H=220,x=t=>8+t/Math.max(dur,.5)*(W-16),y=p=>H-8-(p-lo)/(hi-lo)*(H-16),h=Math.max(3,(H-16)/(hi-lo)-1);
  let g='';for(let p=lo;p<=hi;p++){if([1,3,6,8,10].includes(((p%12)+12)%12))g+=`<rect x="0" y="${y(p)-h/2}" width="${W}" height="${h}" fill="#ffffff07"/>`;if(p%12===0)g+=`<text x="2" y="${y(p)+3}" fill="#8fa7a8" font-size="9">C${p/12-1}</text>`;}
  for(const n of notes){const k=marks&&marks.get(n.t.toFixed(2)+':'+n.p);const col=k==='add'?'var(--add)':k==='lost'?'var(--bad)':`hsl(158,62%,${38+n.v/127*30}%)`;g+=`<rect x="${x(n.t)}" y="${y(n.p)-h/2}" width="${Math.max(2,x(n.t+n.d)-x(n.t))}" height="${h}" rx="2" fill="${col}"><title>${n.name} at ${n.t.toFixed(2)} s, ${n.d.toFixed(2)} s long, velocity ${n.v}</title></rect>`;}
  return `<svg class="roll" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${g}</svg>`;
}
function show(r){
  const f=n=>`/api/convert/${r.id}/${n}`,room=r.room;
  let html=`<div class="card"><h2>${esc(r.file)}</h2><p class="dim">Transcriber: <b>${esc(r.engine)}</b> · cleaner strength ${r.strength} · ${r.seconds} s. Loud-to-quiet spread ${room.before_db} dB${room.cleaner_skipped?' (quiet room: room denoising skipped; key-click reduction still applied)':' → '+room.after_db+' dB after cleaning'}.</p>
  <div class="grid" style="margin-top:12px"><div><p class="dim">Original</p><audio controls preload="metadata" src="${f('original')}"></audio></div><div><p class="dim">Cleaned</p><audio controls preload="metadata" src="${f('cleaned.wav')}"></audio></div></div></div>`;
  const marks=new Map();if(r.difference){for(const n of r.difference.only_after_cleaning)marks.set(n.t.toFixed(2)+':'+n.p,'add');for(const n of r.difference.lost_by_cleaning)marks.set(n.t.toFixed(2)+':'+n.p,'lost');}
  if(r.difference){const d=r.difference;html+=`<div class="card"><h2>What cleaning changed</h2><p>${d.only_after_cleaning.length||d.lost_by_cleaning.length?`Cleaning found <b>${d.only_after_cleaning.length}</b> note${d.only_after_cleaning.length===1?'':'s'} the raw audio missed and lost <b>${d.lost_by_cleaning.length}</b>.`:'Nothing. Both versions give the same notes.'}</p>${[...d.only_after_cleaning.map(n=>'+ '+n.name+' at '+n.t.toFixed(2)+' s'),...d.lost_by_cleaning.map(n=>'− '+n.name+' at '+n.t.toFixed(2)+' s')].slice(0,30).map(x=>`<span class="dim" style="margin-right:12px">${x}</span>`).join('')}</div>`;}
  for(const [key,v] of Object.entries(r.versions)){const s=v.stats;
    html+=`<div class="card"><h2>${key==='cleaned'?'MIDI from the cleaned audio':'MIDI from the original audio'}</h2>
    <div class="facts"><div class="fact"><strong>${s.notes}</strong><span>notes</span></div><div class="fact"><strong>${s.chords}</strong><span>chords</span></div><div class="fact"><strong>${s.biggest_chord}</strong><span>biggest chord</span></div><div class="fact"><strong>${s.lowest??'–'}–${s.highest??'–'}</strong><span>range</span></div></div>
    ${roll(v.notes,v.duration,key==='cleaned'?marks:null)}
    ${r.difference?'<div class="legend"><span><i class="sw" style="background:hsl(158,62%,55%)"></i>note (brighter = louder)</span><span><i class="sw" style="background:var(--add)"></i>only found after cleaning</span></div>':''}
    <div class="row">${s.notes?`<span class="dim" style="font-size:14px">Hear the MIDI on a piano:</span><audio controls preload="metadata" src="${f(key+'-as-piano.wav')}" style="max-width:360px"></audio>`:''}<a class="btn" href="${f(key+'.mid')}" download="${esc(r.file.replace(/[.][^.]+$/,''))}-${key}.mid">Download MIDI</a></div>
    <details><summary>All ${s.notes} notes</summary><table><tr><th>Time</th><th>Note</th><th>Length</th><th>Velocity</th></tr>${v.notes.map(n=>`<tr><td>${n.t.toFixed(2)} s</td><td>${n.name}</td><td>${n.d.toFixed(2)} s</td><td>${n.v}</td></tr>`).join('')}</table></details>
    ${v.warnings.length?`<p class="dim" style="margin-top:8px">${v.warnings.map(esc).join(' ')}</p>`:''}</div>`;}
  $('#out').innerHTML=html;history.replaceState(null,'','/convert?id='+r.id);
}
async function send(file){
  $('#msg').className='';$('#msg').textContent='Cleaning and transcribing… a few seconds per minute of audio.';$('#out').innerHTML='';
  const fd=new FormData();fd.append('audio',file);fd.append('strength',$('#strength').value);fd.append('compare',$('#compare').checked?'1':'0');
  try{const res=await fetch('/api/convert',{method:'POST',body:fd});const d=await res.json();if(!res.ok)throw Error(d.error||'Conversion failed.');$('#msg').textContent='';show(d);}
  catch(e){$('#msg').className='err';$('#msg').textContent=e.message;}
}
$('#file').onchange=e=>e.target.files[0]&&send(e.target.files[0]);
const drop=$('#drop');['dragenter','dragover'].forEach(t=>drop.addEventListener(t,e=>{e.preventDefault();drop.classList.add('over');}));
['dragleave','drop'].forEach(t=>drop.addEventListener(t,e=>{e.preventDefault();drop.classList.remove('over');}));
drop.addEventListener('drop',e=>e.dataTransfer.files[0]&&send(e.dataTransfer.files[0]));
const id=new URLSearchParams(location.search).get('id');
if(id)fetch('/api/convert/'+encodeURIComponent(id)+'/result.json').then(r=>r.ok?r.json():Promise.reject()).then(r=>{r.id=id;show(r);}).catch(()=>{$('#msg').className='err';$('#msg').textContent='That conversion was not found.';});
