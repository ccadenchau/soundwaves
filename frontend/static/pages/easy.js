const $=s=>document.querySelector(s);
async function send(file){
  $('#msg').className='muted';$('#msg').textContent='Listening to the recording and writing the easy version…';$('#done').classList.remove('show');$('#pick').textContent=file.name;
  const f=new FormData();f.append('audio',file);f.append('title',$('#name').value.trim());f.append('start',$('#start').value);f.append('bars',$('#bars').value);f.append('bpm',$('#bpm').value);
  f.append('level',document.querySelector('input[name=level]:checked').value);f.append('solo',$('#solo').checked?'1':'0');
  try{const r=await fetch('/api/easy',{method:'POST',body:f});const d=await r.json();if(!r.ok)throw Error(d.error||'Could not make an easy version.');
    $('#msg').textContent='';$('#title').textContent=d.title;
    $('#facts').textContent=`${d.bars} bars, ${d.notes} notes, in ${d.key}. Heard ${d.heard_notes} notes with ${d.transcriber}${d.bpm_detected?`, pulse about ${d.bpm_detected} bpm`:''}; written at ${d.bpm} bpm.`;
    $('#tune').textContent=d.tune.map(t=>t.name).join(' ');
    $('#go-live').href='/live?piece='+encodeURIComponent(d.id);$('#done').classList.add('show');
    const n=await fetch('/api/live/notation/'+encodeURIComponent(d.id));const nd=await n.json();const box=$('#notation');box.innerHTML='';
    if(n.ok)for(const page of nd.pages){const doc=new DOMParser().parseFromString(page,'image/svg+xml');const svg=document.importNode(doc.documentElement,true);svg.setAttribute('viewBox',`0 0 ${parseFloat(svg.getAttribute('width'))} ${parseFloat(svg.getAttribute('height'))}`);box.append(svg);}
  }catch(e){$('#msg').className='err';$('#msg').textContent=e.message;}
}
$('#file').onchange=e=>e.target.files[0]&&send(e.target.files[0]);
const drop=$('#drop');['dragenter','dragover'].forEach(t=>drop.addEventListener(t,e=>{e.preventDefault();drop.classList.add('over');}));
['dragleave','drop'].forEach(t=>drop.addEventListener(t,e=>{e.preventDefault();drop.classList.remove('over');}));
drop.addEventListener('drop',e=>e.dataTransfer.files[0]&&send(e.dataTransfer.files[0]));
