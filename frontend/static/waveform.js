/* One waveform player per audio element; the original element remains the playback clock. */
(() => {
  const clock = seconds => {
    if (!Number.isFinite(seconds)) return '0:00';
    return `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
  };
  function enhance(audio) {
    if (audio.dataset.waveform || audio.hidden || !audio.controls) return;
    const source = () => audio.getAttribute('src') || audio.querySelector('source')?.getAttribute('src');
    if (!source()) return;
    audio.dataset.waveform = 'true';
    const root = document.createElement('div'); root.className = 'waveform-player';
    const play = document.createElement('button'); play.type = 'button'; play.className = 'waveform-play';
    play.textContent = 'Play'; play.setAttribute('aria-label', 'Play audio');
    const track = document.createElement('div'); track.className = 'waveform-track is-loading'; track.tabIndex = 0;
    track.setAttribute('role', 'slider'); track.setAttribute('aria-label', 'Playback position');
    track.setAttribute('aria-valuemin', '0'); track.setAttribute('aria-valuenow', '0'); track.setAttribute('aria-valuemax', '0');
    const canvas = document.createElement('canvas'); canvas.setAttribute('aria-hidden', 'true'); track.append(canvas);
    const time = document.createElement('span'); time.className = 'waveform-time'; time.textContent = '0:00 / 0:00';
    const status = document.createElement('span'); status.className = 'waveform-status'; status.textContent = 'Loading waveform…';
    root.append(play, track, time, status); audio.after(root);
    audio.controls = false; audio.classList.add('waveform-source');
    let data = null, frame = null, dragging = false, request = null, currentSource = '';
    const duration = () => Number.isFinite(audio.duration) ? audio.duration : data?.duration || 0;
    const draw = () => {
      if (!data) return;
      const width = track.clientWidth, height = track.clientHeight;
      if (width < 1 || height < 1) return;
      const ratio = window.devicePixelRatio || 1;
      if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
        canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
      }
      const ctx = canvas.getContext('2d'); if (!ctx) return;
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0); ctx.clearRect(0, 0, width, height);
      const fraction = Math.min(1, audio.currentTime / Math.max(.001, duration()));
      const count = Math.min(data.peaks.length, Math.max(1, Math.floor(width / 5)));
      const step = width / count;
      for (let i = 0; i < count; i++) {
        const from = Math.floor(i * data.peaks.length / count), to = Math.max(from + 1, Math.floor((i+1) * data.peaks.length / count));
        let peak = 0; for (let j = from; j < to; j++) peak = Math.max(peak, data.peaks[j]);
        const barHeight = Math.max(2, peak * (height - 10));
        ctx.fillStyle = i / count <= fraction && audio.currentTime > 0 ? '#319c89' : '#b9cfca';
        ctx.beginPath(); ctx.roundRect(i * step, (height-barHeight)/2, Math.max(2,step-2), barHeight, 2); ctx.fill();
      }
      if (audio.currentTime > 0) { ctx.fillStyle = '#256e64'; ctx.fillRect(Math.min(width-1,fraction*width),0,1,height); }
      time.textContent = `${clock(audio.currentTime)} / ${clock(duration())}`;
      track.setAttribute('aria-valuenow', String(Math.round(audio.currentTime)));
      track.setAttribute('aria-valuemax', String(Math.round(duration())));
      track.setAttribute('aria-valuetext', `${clock(audio.currentTime)} of ${clock(duration())}`);
    };
    const toggle = () => audio.paused ? audio.play().catch(() => { status.textContent = 'Could not play audio.'; }) : audio.pause();
    play.addEventListener('click', toggle);
    const seek = value => { if (duration()) audio.currentTime = Math.max(0, Math.min(duration(), value)); draw(); };
    const seekPointer = event => { const rect=track.getBoundingClientRect(); seek((event.clientX-rect.left)/Math.max(1,rect.width)*duration()); };
    track.addEventListener('pointerdown', event => {
      if (event.button !== 0 || !data) return;
      dragging = true; track.setPointerCapture(event.pointerId); track.focus(); seekPointer(event);
    });
    track.addEventListener('pointermove', event => { if (dragging) seekPointer(event); });
    track.addEventListener('pointerup', () => { dragging = false; });
    track.addEventListener('pointercancel', () => { dragging = false; });
    track.addEventListener('keydown', event => {
      const key=event.key;
      if (['ArrowLeft','ArrowRight','Home','End',' ','Enter'].includes(key)) event.preventDefault();
      if (key==='ArrowLeft') seek(audio.currentTime-5);
      if (key==='ArrowRight') seek(audio.currentTime+5);
      if (key==='Home') seek(0); if (key==='End') seek(duration());
      if (key===' ' || key==='Enter') toggle();
    });
    const tick = () => { draw(); if (!audio.paused && !audio.ended) frame=requestAnimationFrame(tick); };
    audio.addEventListener('play', () => {
      document.querySelectorAll('audio').forEach(other => { if (other !== audio) other.pause(); });
      play.textContent='Pause'; play.setAttribute('aria-label','Pause audio'); cancelAnimationFrame(frame); tick();
    });
    ['pause','ended'].forEach(name=>audio.addEventListener(name,()=>{
      play.textContent='Play'; play.setAttribute('aria-label','Play audio'); cancelAnimationFrame(frame); draw();
    }));
    ['timeupdate','seeked','loadedmetadata','durationchange'].forEach(name=>audio.addEventListener(name,draw));
    new ResizeObserver(draw).observe(track);
    async function load() {
      const url = new URL(source(),location.href);
      if (url.href === currentSource) return;
      currentSource=url.href; request?.abort(); request=new AbortController();
      data=null; track.classList.add('is-loading'); status.textContent='Loading waveform…';
      try {
        if (url.origin !== location.origin || !/^\/(artifact|api\/convert)\//.test(url.pathname)) throw Error('No waveform source');
        const response=await fetch(url.pathname+'/waveform',{signal:request.signal});
        if (!response.ok) throw Error('Waveform unavailable');
        const result=await response.json();
        if (!Array.isArray(result.peaks) || !result.peaks.length) throw Error('Empty waveform');
        if (url.href!==currentSource) return;
        data=result; root.hidden=false; audio.controls=false; audio.classList.add('waveform-source'); track.classList.remove('is-loading'); status.textContent=''; draw();
      } catch (error) {
        if (error.name==='AbortError' || url.href!==currentSource) return;
        // Playback remains available if decoding or the waveform endpoint fails.
        root.hidden=true; audio.controls=true; audio.classList.remove('waveform-source');
      }
    }
    audio.addEventListener('loadstart', load);
    new MutationObserver(load).observe(audio,{attributes:true,attributeFilter:['src']});
    if ('IntersectionObserver' in window) {
      const visible=new IntersectionObserver(entries=>{
        if(entries.some(entry=>entry.isIntersecting)){void load();visible.disconnect();}
      });
      visible.observe(root);
    } else { void load(); }
  }
  document.querySelectorAll('audio[controls]').forEach(enhance);
  new MutationObserver(records=>{
    for(const record of records) for(const node of record.addedNodes){
      if(node.nodeType!==1) continue;
      if(node.matches('audio[controls]')) enhance(node);
      node.querySelectorAll('audio[controls]').forEach(enhance);
    }
  }).observe(document.body,{childList:true,subtree:true});
})();
