(async()=>{const box=document.getElementById('teacher');if(!box)return;
const status=document.getElementById('teacher-status'),body=document.getElementById('teacher-body');
const el=(tag,text,parent)=>{const e=document.createElement(tag);e.textContent=text;parent.appendChild(e);return e;};
try{const r=await fetch(box.dataset.url);const d=await r.json();if(!r.ok)throw Error(d.error||'Could not get feedback.');
status.remove();el('p',d.summary,body).style.fontSize='18px';
if(d.strengths&&d.strengths.length){el('h3','Going well',body);const u=el('ul','',body);d.strengths.forEach(t=>el('li',t,u));}
if(d.focus_areas&&d.focus_areas.length){el('h3','What to work on',body);d.focus_areas.forEach(f=>{const c=document.createElement('div');c.className='focus';body.appendChild(c);
el('strong',f.title+(f.bars?' · '+f.bars:''),c);el('p',f.what_happened,c);const u=el('ul','',c);f.tips.forEach(t=>el('li',t,u));
const bar=(f.bars||'').match(/[0-9]+/);if(bar&&box.dataset.piece){const a=document.createElement('a');a.className='btn ghost';a.style.cssText='padding:7px 14px;font-size:14px;margin-top:4px';a.href=`/live?piece=${encodeURIComponent(box.dataset.piece)}&bar=${bar[0]}`;a.textContent=`Practise from bar ${bar[0]} live`;c.appendChild(a);}});}
if(d.practice_plan){el('h3','Next practice session',body);el('p',d.practice_plan,body);}
if(d.written_by){const w=el('p',`Written by ${/claude/i.test(d.written_by)?'Claude':'Gemini'} from the note-by-note comparison above.`,body);w.className='muted';w.style.fontSize='13px';}
askBox(d);
}catch(e){status.textContent=e.message;}})();
function askBox(notes){
  const box=document.getElementById('ask'),log=document.getElementById('ask-log'),form=document.getElementById('ask-form'),input=document.getElementById('ask-q'),go=document.getElementById('ask-go');
  const history=[];box.hidden=false;
  const first=(notes.focus_areas||[])[0];
  const chips=[first&&first.bars?`Why do you say that about ${first.bars}?`:'What should I fix first?','What should I practise first tomorrow?','Which hand needs more work?'];
  document.getElementById('ask-chips').innerHTML=chips.map(c=>`<button type="button">${c.replace(/</g,'&lt;')}</button>`).join('');
  document.querySelectorAll('#ask-chips button').forEach(b=>b.addEventListener('click',()=>{input.value=b.textContent;form.requestSubmit();}));
  form.addEventListener('submit',async ev=>{ev.preventDefault();const q=input.value.trim();if(!q||go.disabled)return;
    const qEl=document.createElement('p');qEl.className='q';qEl.textContent=q;log.appendChild(qEl);
    const aEl=document.createElement('p');aEl.className='a muted';aEl.textContent='Thinking…';log.appendChild(aEl);
    input.value='';go.disabled=true;
    try{const r=await fetch(document.getElementById('teacher').dataset.url.replace('/feedback','/ask'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q,history})});
      const d=await r.json();if(!r.ok)throw Error(d.error||'No answer.');aEl.textContent=d.answer;aEl.classList.remove('muted');history.push({role:'user',content:q},{role:'assistant',content:d.answer});
      document.getElementById('ask-note').textContent=`Answered by ${/claude/i.test(d.written_by)?'Claude':'Gemini'} from the note-by-note comparison of this take, not from listening again.`;
    }catch(e){aEl.textContent=e.message;}finally{go.disabled=false;input.focus();}
  });
}
(async()=>{const box=document.getElementById('teacher');if(!box)return;
try{const r=await fetch(box.dataset.url.replace('/feedback','/bar-notes'));const d=await r.json();if(!r.ok)return;
let n=0;for(const [bar,note] of Object.entries(d.bars||{})){const td=document.querySelector(`td[data-bar="${bar}"]`);if(!td)continue;const div=document.createElement('div');div.className='barnote';div.textContent=note;td.prepend(div);n++;}
if(n){const cap=document.getElementById('barnote-caption');cap.textContent=`The first line in each Feedback cell is written by ${/claude/i.test(d.written_by)?'Claude':'Gemini'} from that bar's measurements; the lines after it are the measurements in words.`;cap.hidden=false;}
}catch(e){}})();
document.querySelectorAll('.seek').forEach(button=>button.addEventListener('click',()=>{
const audio=document.getElementById('audio');audio.currentTime=Number(button.dataset.time);audio.play().catch(()=>{});}));
document.querySelectorAll('audio').forEach(player=>player.addEventListener('play',()=>{
document.querySelectorAll('audio').forEach(other=>{if(other!==player)other.pause();});}));
