(async()=>{const box=document.getElementById('teacher');if(!box)return;
const status=document.getElementById('teacher-status'),body=document.getElementById('teacher-body');
const el=(tag,text,parent)=>{const e=document.createElement(tag);e.textContent=String(text??'').replace(/\u00b7/g,' / ');parent.appendChild(e);return e;};
try{const r=await fetch(box.dataset.url);const d=await r.json();if(!r.ok)throw Error(d.error||'Could not get feedback.');
status.remove();el('p',d.summary,body).style.fontSize='18px';
if(d.strengths&&d.strengths.length){el('h3','Going well',body);const u=el('ul','',body);d.strengths.forEach(t=>el('li',t,u));}
if(d.focus_areas&&d.focus_areas.length){el('h3','Focus',body);d.focus_areas.forEach(f=>{const c=document.createElement('div');c.className='focus';body.appendChild(c);
el('strong',f.title+(f.bars?'  /  '+f.bars:''),c);el('p',f.what_happened,c);const u=el('ul','',c);f.tips.forEach(t=>el('li',t,u));
const bar=(f.bars||'').match(/[0-9]+/);if(bar&&box.dataset.piece){const a=document.createElement('a');a.className='btn ghost';a.style.cssText='padding:7px 14px;font-size:14px;margin-top:4px';a.href=`/live?piece=${encodeURIComponent(box.dataset.piece)}&bar=${bar[0]}`;a.textContent=`Practice bar ${bar[0]}`;c.appendChild(a);}});}
if(d.practice_plan){el('h3','Next session',body);el('p',d.practice_plan,body);}
askBox(d);
}catch(e){status.textContent=e.message;}})();
function askBox(notes){
  const box=document.getElementById('ask'),log=document.getElementById('ask-log'),form=document.getElementById('ask-form'),input=document.getElementById('ask-q'),go=document.getElementById('ask-go');
  const history=[];box.hidden=false;
  const first=(notes.focus_areas||[])[0];
  const chips=[first&&first.bars?`Explain ${first.bars}`:'What first?','Next session?','Which hand?'];
  document.getElementById('ask-chips').innerHTML=chips.map(c=>`<button type="button">${c.replace(/</g,'&lt;')}</button>`).join('');
  document.querySelectorAll('#ask-chips button').forEach(b=>b.addEventListener('click',()=>{input.value=b.textContent;form.requestSubmit();}));
  form.addEventListener('submit',async ev=>{ev.preventDefault();const q=input.value.trim();if(!q||go.disabled)return;
    const qEl=document.createElement('p');qEl.className='q';qEl.textContent=q;log.appendChild(qEl);
    const aEl=document.createElement('p');aEl.className='a muted';aEl.innerHTML='<span class="analysis-wave coach-wave" aria-label="Thinking"><i></i><i></i><i></i><i></i><i></i></span>';log.appendChild(aEl);
    input.value='';go.disabled=true;
    try{const r=await fetch(document.getElementById('teacher').dataset.url.replace('/feedback','/ask'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q,history})});
      const d=await r.json();if(!r.ok)throw Error(d.error||'No answer.');aEl.textContent=d.answer.replace(/\u00b7/g,' / ');aEl.classList.remove('muted');history.push({role:'user',content:q},{role:'assistant',content:d.answer});
      document.getElementById('ask-note').textContent=`Answered by ${/claude/i.test(d.written_by)?'Claude':'Gemini'} from the note-by-note comparison of this take, not from listening again.`;
    }catch(e){aEl.textContent=e.message;}finally{go.disabled=false;input.focus();}
  });
}
(async()=>{const box=document.getElementById('teacher');if(!box)return;
try{const r=await fetch(box.dataset.url.replace('/feedback','/bar-notes'));const d=await r.json();if(!r.ok)return;
let n=0;for(const [bar,note] of Object.entries(d.bars||{})){const td=document.querySelector(`td[data-bar="${bar}"]`);if(!td)continue;const div=document.createElement('div');div.className='barnote';div.textContent=note.replace(/\u00b7/g,' / ');td.prepend(div);n++;}
if(n){const cap=document.getElementById('barnote-caption');cap.textContent='';cap.hidden=true;}
}catch(e){}})();
document.querySelectorAll('audio').forEach(player=>player.addEventListener('play',()=>{
document.querySelectorAll('audio').forEach(other=>{if(other!==player)other.pause();});}));
