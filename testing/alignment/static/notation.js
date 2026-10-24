/* Performance overlays use detected audio times, never reference MIDI times. */
async function displayNotation() {
  const section = document.getElementById('score-view');
  if (!section) return;
  const container = document.getElementById('notation');
  const status = document.getElementById('notation-status');
  const audio = document.getElementById('audio');
  const ns = 'http://www.w3.org/2000/svg';
  try {
    const response = await fetch(section.dataset.url);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Could not render score.');
    const elements = new Map();
    for (const page of data.pages) {
      const doc = new DOMParser().parseFromString(page, 'image/svg+xml');
      if (doc.querySelector('parsererror')) throw new Error('Invalid score page.');
      doc.querySelectorAll('script,foreignObject').forEach(el => el.remove());
      for (const el of doc.querySelectorAll('*')) {
        for (const attr of [...el.attributes]) {
          if (/^on/i.test(attr.name) || (/href$/i.test(attr.name) && !attr.value.startsWith('#'))) {
            el.removeAttribute(attr.name);
          }
        }
      }
      const svg = document.importNode(doc.documentElement, true);
      svg.setAttribute('viewBox', `0 0 ${parseFloat(svg.getAttribute('width'))} ${parseFloat(svg.getAttribute('height'))}`);
      container.append(svg);
      svg.querySelectorAll('[id]').forEach(el => elements.set(el.id, el));
    }
    const seek = time => {
      if (time === null || !Number.isFinite(time)) return;
      audio.currentTime = Math.max(0, time);
      audio.play().catch(() => {});
    };
    const describe = item => `${item.category.replaceAll('_', ' ')}: expected ${item.expected_name || 'no note'}, played ${item.actual_name || 'no note'}${item.audio_time === null ? '' : ` at ${item.audio_time.toFixed(2)}s`}`;
    const interactive = (el, item) => {
      const title = document.createElementNS(ns, 'title');
      title.textContent = describe(item);
      el.append(title);
      el.setAttribute('tabindex', '0');
      el.setAttribute('role', item.audio_time === null ? 'img' : 'button');
      el.setAttribute('aria-label', title.textContent);
      el.addEventListener('click', event => { event.stopPropagation(); seek(item.audio_time); });
      el.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); seek(item.audio_time); }
      });
    };
    const timed = [];
    for (const item of data.annotations) {
      const note = elements.get(item.xml_id);
      if (!note) continue;
      if (item.category !== 'extra') {
        note.classList.add(({correct: 'matched', missing: 'missed', wrong_pitch: 'wrong'})[item.category]);
        interactive(note, item);
      }
      let target = note;
      if (item.category === 'wrong_pitch' || item.category === 'extra') {
        const head = note.querySelector('.notehead');
        if (!head) continue;
        const box = head.getBBox();
        const staff = note.closest('.staff');
        const lines = [...(staff?.children || [])].filter(el => el.tagName === 'path').map(el => el.getBBox().y).sort((a,b) => a-b);
        const gap = lines.length > 1 ? lines[1] - lines[0] : box.height;
        const x = box.x + box.width / 2 + (item.category === 'extra' ? box.width * 1.4 : 0);
        const y = box.y + box.height / 2 - item.staff_steps * gap / 2;
        const group = document.createElementNS(ns, 'g');
        group.classList.add('played-marker');
        const ellipse = document.createElementNS(ns, 'ellipse');
        for (const [key, value] of Object.entries({cx:x, cy:y, rx:box.width/2, ry:box.height/2})) ellipse.setAttribute(key, value);
        group.append(ellipse);
        // Exact pitch labels disambiguate accidentals and approximate extra-note positions.
        const label = document.createElementNS(ns, 'text');
        label.setAttribute('x', x + box.width * .7);
        label.setAttribute('y', y - box.height * .7);
        label.setAttribute('font-size', gap * .7);
        label.textContent = `${item.category === 'extra' ? '+ ' : ''}${item.actual_name}`;
        group.append(label);
        if (lines.length >= 5) {
          for (let ly = lines[0] - gap; ly >= y - gap / 4; ly -= gap) ledger(ly);
          for (let ly = lines[4] + gap; ly <= y + gap / 4; ly += gap) ledger(ly);
        }
        function ledger(ly) {
          const line = document.createElementNS(ns, 'line');
          for (const [key, value] of Object.entries({x1:x-box.width*.8,x2:x+box.width*.8,y1:ly,y2:ly,'stroke-width':12,stroke:'currentColor'})) line.setAttribute(key,value);
          group.append(line);
        }
        note.append(group);
        interactive(group, item);
        target = group;
      }
      if (item.audio_time !== null) timed.push({item, target, note});
    }
    const unplaced = document.getElementById('unplaced-notes');
    unplaced.hidden = !data.unplaced.length;
    for (const item of data.unplaced) {
      const row = document.createElement('p');
      row.textContent = `${item.category.replaceAll('_', ' ')} · MIDI pitch ${item.actual_pitch ?? item.expected_pitch}`;
      if (item.audio_time !== null) {
        const button = document.createElement('button');
        button.textContent = `Listen at ${item.audio_time.toFixed(2)}s`;
        button.addEventListener('click', () => seek(item.audio_time));
        row.append(' ', button);
      }
      unplaced.querySelector('div').append(row);
    }
    document.getElementById('show-overlays').addEventListener('change', event => container.classList.toggle('hide-overlays', !event.target.checked));
    document.getElementById('score-zoom').addEventListener('change', event => {
      const zoom = Number(event.target.value);
      container.querySelectorAll(':scope > svg').forEach(svg => {
        svg.style.width = `${zoom * 100}%`;
        svg.style.minWidth = `${zoom * 900}px`;
      });
    });
    let lastMeasure, frame;
    const update = () => {
      container.querySelectorAll('.active-note').forEach(el => el.classList.remove('active-note'));
      const current = timed.filter(({item}) => audio.currentTime >= item.audio_time && audio.currentTime < item.audio_time + item.duration);
      current.forEach(({target}) => target.classList.add('active-note'));
      const caption = current.length ? `Playing: ${[...new Set(current.map(({item}) => item.actual_name))].join(', ')}` : 'Between detected notes';
      const label = document.getElementById('playing-notes');
      if (label.textContent !== caption) label.textContent = caption;
      const measure = current[0]?.note.closest('.measure');
      if (measure && measure !== lastMeasure && document.getElementById('follow-score').checked) {
        const offset = measure.getBoundingClientRect().top - container.getBoundingClientRect().top;
        if (offset < 0 || offset > container.clientHeight - 120) container.scrollTo({top:container.scrollTop + offset - 60, behavior:'smooth'});
        lastMeasure = measure;
      }
    };
    const tick = () => { update(); if (!audio.paused) frame = requestAnimationFrame(tick); };
    audio.addEventListener('play', () => { cancelAnimationFrame(frame); tick(); });
    ['timeupdate', 'seeked', 'pause', 'ended'].forEach(name => audio.addEventListener(name, update));
    status.textContent = `${data.annotations.length} note comparisons shown${data.unplaced.length ? `; ${data.unplaced.length} without a score location` : ''}.`;
    if (!audio.paused) tick();
  } catch (error) {
    status.textContent = error.message;
    status.classList.add('error');
  }
}
displayNotation();
