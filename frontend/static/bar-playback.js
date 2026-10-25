/* Speaker buttons preview a bounded bar on the same audio clock as the score. */
(() => {
  const audio=document.getElementById('audio');if(!audio)return;
  let segment=null,timer=null,version=0;
  const unschedule=()=>{clearTimeout(timer);timer=null;};
  const clear=()=>{segment=null;version++;unschedule();};
  const check=()=>{
    unschedule();if(!segment||audio.paused)return;
    const remaining=segment.end-audio.currentTime;
    if(remaining<=.005){
      const end=segment.end;clear();audio.pause();audio.currentTime=end;
    }else{
      timer=setTimeout(check,Math.max(4,remaining/Math.max(.1,audio.playbackRate)*1000));
    }
  };
  document.querySelectorAll('.seek').forEach(button=>button.addEventListener('click',()=>{
    clear();const start=Number(button.dataset.time),end=Number(button.dataset.end);
    if(!Number.isFinite(start))return;
    if(button.hasAttribute('data-end')&&Number.isFinite(end)&&end>start)segment={start:Math.max(0,start),end,source:audio.src};
    audio.currentTime=Math.max(0,start);
    const requested=version;
    audio.play().then(()=>{if(requested===version)check();}).catch(()=>{if(requested===version)clear();});
  }));
  ['play','timeupdate','ratechange'].forEach(name=>audio.addEventListener(name,check));
  audio.addEventListener('pause',unschedule);
  ['ended','emptied'].forEach(name=>audio.addEventListener(name,clear));
  audio.addEventListener('loadstart',()=>{if(segment&&segment.source!==audio.src)clear();else check();});
  audio.addEventListener('seeking',()=>{
    if(segment&&(audio.currentTime<segment.start-.02||audio.currentTime>=segment.end))clear();
    else check();
  });
})();
