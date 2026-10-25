/* Styled dropdowns keep native selects as the form and application data source. */
(() => {
  let opened = null;
  let serial = 0;
  function enhance(select) {
    if (select.multiple || select.size > 1 || select.closest('.custom-select')) return;
    const wrapper = document.createElement('span');
    wrapper.className = 'custom-select';
    select.before(wrapper); wrapper.append(select);
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'select-trigger';
    button.setAttribute('role', 'combobox'); button.setAttribute('aria-haspopup', 'listbox');
    button.setAttribute('aria-expanded', 'false');
    const text = document.createElement('span'); text.className = 'select-value'; button.append(text);
    const menu = document.createElement('span'); menu.className = 'select-menu';
    menu.id = `select-menu-${++serial}`; menu.hidden = true; menu.setAttribute('role', 'listbox');
    button.setAttribute('aria-controls', menu.id);
    const label = select.closest('label');
    const labelText = label ? [...label.childNodes].filter(node => node.nodeType === 3).map(node => node.textContent).join(' ').trim() : '';
    const name = select.getAttribute('aria-label') || labelText || select.name || 'Choose';
    menu.setAttribute('aria-label', name);
    wrapper.append(button, menu);
    select.tabIndex = -1; select.setAttribute('aria-hidden', 'true');
    const close = () => { menu.hidden = true; button.setAttribute('aria-expanded', 'false'); if (opened === close) opened = null; };
    const choices = () => [...menu.querySelectorAll('button:not(:disabled)')];
    const choose = index => {
      select.selectedIndex = index;
      select.dispatchEvent(new Event('input', {bubbles: true}));
      select.dispatchEvent(new Event('change', {bubbles: true}));
      sync(); close(); button.focus();
    };
    const sync = () => {
      text.textContent = select.selectedOptions[0]?.textContent || 'Choose';
      button.disabled = select.disabled;
      button.setAttribute('aria-label', `${name}: ${text.textContent}`);
      menu.replaceChildren();
      [...select.options].forEach((option, index) => {
        const item = document.createElement('button'); item.type = 'button'; item.tabIndex = -1;
        item.className = 'select-option'; item.textContent = option.textContent;
        item.disabled = option.disabled || option.parentElement.disabled === true;
        item.setAttribute('role', 'option'); item.setAttribute('aria-selected', String(option.selected));
        item.addEventListener('click', event => { event.preventDefault(); choose(index); });
        menu.append(item);
      });
      if (select.hasAttribute('data-piece-picker')) {
        const add = document.createElement('button');
        add.type = 'button'; add.tabIndex = -1; add.className = 'select-option select-new';
        add.textContent = 'New piece'; add.setAttribute('role', 'option');
        add.addEventListener('click', event => {
          event.preventDefault(); close(); window.SoundwavesPieces?.open(select);
        });
        menu.append(add);
      }
      if (select.disabled) close();
    };
    const open = () => {
      if (opened && opened !== close) opened();
      sync(); menu.hidden = false; button.setAttribute('aria-expanded', 'true'); opened = close;
      (menu.querySelector('[aria-selected=true]:not(:disabled)') || choices()[0])?.focus();
    };
    button.addEventListener('click', event => { event.preventDefault(); menu.hidden ? open() : close(); });
    wrapper.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); close(); button.focus(); return; }
      if (event.key === 'Tab') { close(); return; }
      if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
        event.preventDefault();
        if (menu.hidden) { open(); return; }
        const items = choices(); const current = items.indexOf(document.activeElement);
        const index = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1
          : (current + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
        items[index]?.focus();
      } else if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && event.key !== ' ') {
        if (menu.hidden) open();
        choices().find(item => item.textContent.toLowerCase().startsWith(event.key.toLowerCase()))?.focus();
      }
    });
    wrapper.addEventListener('focusout', event => { if (!wrapper.contains(event.relatedTarget)) close(); });
    document.addEventListener('pointerdown', event => { if (!wrapper.contains(event.target)) close(); });
    select.addEventListener('change', sync);
    select.addEventListener('focus', () => button.focus());
    select.addEventListener('invalid', () => button.focus());
    select.form?.addEventListener('reset', () => queueMicrotask(sync));
    new MutationObserver(sync).observe(select, {childList: true, subtree: true, characterData: true, attributes: true});
    sync();
  }
  document.querySelectorAll('label.drop').forEach(label => {
    const input = label.querySelector('input[type=file]');
    if (!input) return;
    label.tabIndex = 0; label.setAttribute('role', 'button');
    label.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); input.click(); }
    });
  });
  document.querySelectorAll('select').forEach(enhance);
  new MutationObserver(records => {
    for (const record of records) for (const node of record.addedNodes) {
      if (node.nodeType !== 1) continue;
      if (node.matches('select')) enhance(node);
      node.querySelectorAll('select').forEach(enhance);
    }
  }).observe(document.body, {childList: true, subtree: true});
})();
