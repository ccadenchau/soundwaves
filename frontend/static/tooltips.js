(() => {
  const tooltip = document.createElement('div');
  tooltip.id = 'ui-tooltip'; tooltip.className = 'ui-tooltip';
  tooltip.setAttribute('role', 'tooltip'); tooltip.hidden = true;
  document.body.append(tooltip);
  let anchor = null;
  let described = null;
  const hide = () => {
    tooltip.hidden = true;
    if (described) {
      const ids = (described.getAttribute('aria-describedby') || '').split(' ').filter(id => id && id !== tooltip.id);
      ids.length ? described.setAttribute('aria-describedby', ids.join(' ')) : described.removeAttribute('aria-describedby');
    }
    anchor = described = null;
  };
  const targetFor = element => {
    if (!(element instanceof Element)) return null;
    const direct = element.closest('[data-tooltip]');
    if (direct) return direct;
    // Enhanced dropdowns keep their help text on the native select.
    return element.closest('.custom-select')?.querySelector('select[data-tooltip]') || null;
  };
  const show = (target, focus) => {
    if (!target) return;
    hide(); anchor = target;
    tooltip.textContent = target.dataset.tooltip;
    tooltip.hidden = false;
    const visible = target.closest('.custom-select') || target;
    const rect = visible.getBoundingClientRect();
    const box = tooltip.getBoundingClientRect();
    tooltip.style.left = `${Math.max(12, Math.min(window.innerWidth - box.width - 12, rect.left + (rect.width-box.width)/2))}px`;
    tooltip.style.top = `${rect.top >= box.height + 16 ? rect.top-box.height-8 : Math.min(rect.bottom+8, window.innerHeight-box.height-12)}px`;
    described = focus || visible;
    const ids = new Set((described.getAttribute('aria-describedby') || '').split(' ').filter(Boolean));
    ids.add(tooltip.id); described.setAttribute('aria-describedby', [...ids].join(' '));
  };
  document.addEventListener('pointerover', event => { const target=targetFor(event.target); if (target && target !== anchor) show(target); });
  document.addEventListener('pointerout', event => {
    if (anchor && targetFor(event.relatedTarget) !== anchor) hide();
  });
  document.addEventListener('focusin', event => { const target=targetFor(event.target); if (target) show(target,event.target); });
  document.addEventListener('focusout', hide);
  document.addEventListener('keydown', event => { if (event.key === 'Escape') hide(); });
  document.addEventListener('click', event => { if (event.target.closest('.select-trigger')) hide(); });
  window.addEventListener('scroll', hide, true);
  window.addEventListener('resize', hide);
})();
