/* CSS starts the slide on first paint; links keep normal browser navigation. */
(() => {
  const main=document.querySelector('main');
  if(!main)return;
  const motion=window.matchMedia('(prefers-reduced-motion: reduce)');
  // Back/forward cache restores do not rerun CSS animations.
  window.addEventListener('pageshow',event=>{
    if(!event.persisted)return;
    main.getAnimations?.().forEach(animation=>animation.cancel());
    if(motion.matches||!main.animate)return;
    main.animate([
      {transform:'translateX(20px)'},
      {transform:'translateX(0)'}
    ],{duration:280,easing:'cubic-bezier(.2,.75,.25,1)'});
  });
})();
