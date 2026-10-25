(() => {
  const dialog=document.createElement('dialog');dialog.className='piece-modal';dialog.setAttribute('aria-labelledby','new-piece-title');
  dialog.innerHTML='<form><div class="modal-heading"><h2 id="new-piece-title">New piece</h2><button type="button" class="ghost" data-cancel>Cancel</button></div><label>Sheet music<input name="score" type="file" accept=".pdf,.musicxml,.xml,.mxl" required></label><div class="modal-fields"><label>Name <small>optional</small><input name="title" placeholder="Piece title" maxlength="120"></label><label>Tempo <small>BPM</small><input name="bpm" type="number" value="100" min="20" max="400" required></label></div><div class="loading-inline" data-loading hidden role="status"><div class="analysis-wave" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div><span>Reading score…</span></div><p class="modal-error" role="alert" hidden></p><button type="submit" class="modal-submit">Add piece</button></form>';
  document.body.append(dialog);
  const form=dialog.querySelector('form'),cancel=dialog.querySelector('[data-cancel]'),submit=form.querySelector('[type=submit]');
  const status=dialog.querySelector('.modal-error'),loading=dialog.querySelector('[data-loading]');
  let picker=null,previous=null,busy=false;
  const open=select=>{
    picker=select||document.querySelector('select[data-piece-picker]');
    previous=picker?.closest('.custom-select')?.querySelector('.select-trigger')||document.activeElement;
    form.reset();status.hidden=true;status.textContent='';loading.hidden=true;
    if(!dialog.open) dialog.showModal();
  };
  const close=()=>{if(!busy)dialog.close();};
  cancel.addEventListener('click',close);
  const outside=event=>{
    const rect=dialog.getBoundingClientRect();
    return event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom;
  };
  let backdropPress=false;
  dialog.addEventListener('pointerdown',event=>{backdropPress=event.target===dialog&&outside(event);});
  dialog.addEventListener('click',event=>{
    if(backdropPress&&event.target===dialog&&outside(event))close();
    backdropPress=false;
  });
  dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});
  dialog.addEventListener('close',()=>{previous?.focus();});
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(busy||!form.reportValidity())return;
    const data=new FormData(form);busy=true;status.hidden=true;loading.hidden=false;
    cancel.disabled=submit.disabled=true;form.querySelectorAll('input').forEach(input=>{input.disabled=true;});
    try{
      const response=await fetch('/api/pieces/upload',{method:'POST',body:data});
      const piece=await response.json();if(!response.ok)throw Error(piece.error||'Could not add this piece.');
      document.querySelectorAll('select[data-piece-picker]').forEach(select=>{
        let option=[...select.options].find(item=>item.value===piece.id);
        if(!option){option=new Option(piece.title,piece.id);select.add(option);}else option.textContent=piece.title;
      });
      busy=false;dialog.close();
      if(picker){picker.value=piece.id;picker.dispatchEvent(new Event('change',{bubbles:true}));}
      else location.href=`/live?piece=${encodeURIComponent(piece.id)}`;
    }catch(error){status.textContent=error.message;status.hidden=false;}
    finally{busy=false;loading.hidden=true;cancel.disabled=submit.disabled=false;form.querySelectorAll('input').forEach(input=>{input.disabled=false;});}
  });
  document.addEventListener('click',event=>{if(event.target.closest('[data-open-piece]'))open();});
  window.SoundwavesPieces={open};
  const query=new URLSearchParams(location.search);
  if(query.has('add-piece')){
    open();query.delete('add-piece');history.replaceState(null,'',location.pathname+(query.size?'?'+query.toString():''));
  }
})();
