(() => {
  const screen=document.createElement('div'); screen.className='analysis-screen'; screen.hidden=true;
  screen.setAttribute('role','dialog'); screen.setAttribute('aria-modal','true');
  screen.setAttribute('aria-labelledby','analysis-title'); screen.tabIndex=-1;
  screen.innerHTML='<div class="analysis-panel"><div class="analysis-wave" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div><h2 id="analysis-title">Preparing your review</h2><p class="analysis-status" role="status">Analyzing your take…</p><span class="analysis-elapsed">0:00</span><div class="analysis-actions"><a class="btn ghost" hidden download="recording.webm">Save recording</a><button class="btn" type="button" hidden>Return</button></div></div>';
  document.body.append(screen);
  const status=screen.querySelector('.analysis-status'),elapsed=screen.querySelector('.analysis-elapsed');
  const download=screen.querySelector('a'),back=screen.querySelector('button');
  let timer=null,started=0,recordingUrl=null,previousFocus=null,locked=[];
  const hide=()=>{
    clearInterval(timer); screen.hidden=true; document.body.classList.remove('analyzing');
    locked.forEach(([element,inert])=>{element.inert=inert;});locked=[];
    previousFocus?.focus();
  };
  const show=()=>{
    if(!screen.hidden) return;
    previousFocus=document.activeElement;
    download.hidden=true;
    if(recordingUrl){URL.revokeObjectURL(recordingUrl);recordingUrl=null;}
    locked=[...document.body.children].filter(el=>el!==screen).map(el=>[el,el.inert]);
    locked.forEach(([el])=>{el.inert=true;});
    screen.hidden=false; document.body.classList.add('analyzing'); screen.classList.remove('failed'); back.hidden=true;
    status.textContent='Analyzing your take…'; screen.querySelector('h2').textContent='Preparing your review';
    elapsed.textContent='0:00'; started=Date.now();
    timer=setInterval(()=>{const s=Math.floor((Date.now()-started)/1000);elapsed.textContent=`${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`;},1000);
    screen.focus();
  };
  const setRecording=blob=>{
    if(recordingUrl) URL.revokeObjectURL(recordingUrl);
    recordingUrl=URL.createObjectURL(blob);download.href=recordingUrl;download.download=blob.name||'recording.webm';download.hidden=false;
  };
  const fail=message=>{
    clearInterval(timer);screen.classList.add('failed');screen.querySelector('h2').textContent='Could not finish';status.textContent=message;back.hidden=false;back.focus();
  };
  back.addEventListener('click',hide);
  window.SoundwavesLoading={show,hide,setRecording,fail};
  document.querySelectorAll('form[data-analysis]').forEach(form=>form.addEventListener('submit',()=>{
    show();const recording=form.querySelector('input[type=file][name=recording]')?.files[0];if(recording)setRecording(recording);
  }));
  window.addEventListener('pageshow',()=>{
    if(!screen.hidden)hide();
    document.querySelectorAll('form[data-analysis] button[type=submit]').forEach(button=>{button.disabled=false;});
  });
})();
