const $=s=>document.querySelector(s);
async function send(file){
  $('#msg').className='muted';$('#msg').textContent='Reading the score…';$('#done').classList.remove('show');$('#pick').textContent=file.name;
  const f=new FormData();f.append('score',file);f.append('bpm',$('#bpm').value);f.append('title',$('#name').value.trim());
  try{const r=await fetch('/api/pieces/upload',{method:'POST',body:f});const d=await r.json();if(!r.ok)throw Error(d.error||'Could not read this score.');
    $('#msg').textContent='';$('#title').textContent=d.title+(d.composer?' · '+d.composer:'');
    $('#facts').innerHTML=[`${d.bars} bar${d.bars===1?'':'s'} in ${d.time_signature[0]}/${d.time_signature[1]}`,`${d.notes} notes, tempo ${Math.round(d.bpm)}`,d.reused?'This score was already here.':'Saved.'].map(t=>`<li>${t}</li>`).join('');
    $('#go-live').href='/live?piece='+encodeURIComponent(d.id);$('#done').classList.add('show');
  }catch(e){$('#msg').className='err';$('#msg').textContent=e.message;}
}
$('#file').onchange=e=>e.target.files[0]&&send(e.target.files[0]);
const drop=$('#drop');['dragenter','dragover'].forEach(t=>drop.addEventListener(t,e=>{e.preventDefault();drop.classList.add('over');}));
['dragleave','drop'].forEach(t=>drop.addEventListener(t,e=>{e.preventDefault();drop.classList.remove('over');}));
drop.addEventListener('drop',e=>e.dataTransfer.files[0]&&send(e.dataTransfer.files[0]));
