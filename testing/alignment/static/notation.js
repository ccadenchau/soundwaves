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
    const describe = item => `${item.category.replaceAll('_', ' ')}${item.maybe_noise ? ' (possibly background noise)' : ''}: expected ${item.expected_name || 'no note'}, played ${item.actual_name || 'no note'}${item.audio_time === null ? '' : ` at ${item.audio_time.toFixed(2)}s`}`;
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
        if (item.maybe_noise) group.classList.add('faint');
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
    for (const wedge of data.wedges || []) {
      const start = elements.get(wedge.start_xml_id), end = elements.get(wedge.end_xml_id);
      if (!start || !end) continue;
      const headOf = el => el.querySelector('.notehead') || el;
      const a = headOf(start).getBBox(), b = headOf(end).getBBox();
      const staff = start.closest('.staff');
      const staffLines = [...(staff?.querySelectorAll(':scope > path') || [])]
        .map(el => el.getBBox()).filter(box => box.width > 100);
      const y = staffLines.length ? Math.max(...staffLines.map(box => box.y + box.height)) + 55
        : Math.max(a.y + a.height, b.y + b.height) + 65;
      const x1 = a.x + a.width / 2, x2 = b.x + b.width / 2;
      if (x2 <= x1 + 3) continue;
      const narrow = wedge.kind === 'crescendo' ? 2 : 14;
      const wide = wedge.kind === 'crescendo' ? 14 : 2;
      const group = document.createElementNS(ns, 'g');
      const cls = `dynamic-wedge${wedge.status ? ` ${wedge.status}` : ''}`;
      for (const sign of [-1, 1]) {
        const path = document.createElementNS(ns, 'path');
        path.setAttribute('class', cls);
        path.setAttribute('d', `M${x1} ${y + sign * narrow} L${x2} ${y + sign * wide}`);
        group.append(path);
      }
      const title = document.createElementNS(ns, 'title');
      title.textContent = `${wedge.kind === 'crescendo' ? 'Crescendo' : 'Decrescendo'}${wedge.status === 'wrong' ? ' needs more shaping' : wedge.status === 'good' ? ' followed in the performance' : ''}`;
      group.append(title);
      start.ownerSVGElement.append(group);
    }
    // Low-confidence alignments can occasionally place one detected note in a
    // much later bar. Use nearby exact pitch matches as a progress guide and
    // suppress annotations that jump well outside the expected score position.
    const scoreAnchors = [...new Map(timed.filter(({item}) => item.category === 'correct'
      && item.score_beat !== null && Number.isFinite(item.audio_time))
      .sort((a,b) => a.item.audio_time - b.item.audio_time)
      .map(({item}) => [item.audio_time.toFixed(3), {time:item.audio_time, beat:item.score_beat}])).values()];
    const rates = scoreAnchors.slice(1).map((point,i) =>
      (point.beat-scoreAnchors[i].beat)/(point.time-scoreAnchors[i].time))
      .filter(rate => Number.isFinite(rate) && rate > 0 && rate < 12).sort((a,b) => a-b);
    const typicalRate = rates.length ? rates[Math.floor(rates.length/2)] : null;
    const stableAnchors = [];
    for (const point of scoreAnchors) {
      const previous = stableAnchors.at(-1);
      if (!previous) { stableAnchors.push(point); continue; }
      const elapsed = point.time-previous.time, advance = point.beat-previous.beat;
      // Keep the score cursor near a plausible pace, even if several later
      // pitch matches share the same bad measure assignment.
      const maximumAdvance = typicalRate ? Math.max(2, typicalRate*elapsed*2.5+1) : 12;
      if (elapsed <= 0 || (advance >= 0 && advance <= maximumAdvance)) stableAnchors.push(point);
    }
    const scoreBeatAt = time => {
      if (!stableAnchors.length) return null;
      if (stableAnchors.length === 1) return stableAnchors[0].beat + (time-stableAnchors[0].time)*(typicalRate || 2);
      let right = stableAnchors.findIndex(point => point.time >= time);
      if (right < 0) return stableAnchors.at(-1).beat + (time-stableAnchors.at(-1).time)*(typicalRate || 2);
      if (right === 0) return stableAnchors[0].beat + (time-stableAnchors[0].time)*(typicalRate || 2);
      const left = stableAnchors[right-1], next = stableAnchors[right];
      const portion = Math.max(0, Math.min(1, (time-left.time)/(next.time-left.time)));
      return left.beat + portion*(next.beat-left.beat);
    };
    const plausible = item => {
      const expected = scoreBeatAt(item.audio_time);
      const position = item.display_beat ?? item.score_beat ?? item.alignment_beat;
      return expected === null || position === null || Math.abs(position-expected) <= 1.5;
    };
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
      const current = timed.filter(({item}) => audio.currentTime >= item.audio_time && audio.currentTime < item.audio_time + item.duration && plausible(item));
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
