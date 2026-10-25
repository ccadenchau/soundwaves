const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

function navigation(reduced=false){
  const animations=[],listeners={};
  const main={getAnimations:()=>[],animate:(frames,options)=>{animations.push({frames,options});return{finished:Promise.resolve()};}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../frontend/static/navigation.js'),'utf8'),{
    document:{querySelector:()=>main,addEventListener:(name,handler)=>{listeners[name]=handler;}},
    window:{matchMedia:()=>({matches:reduced}),addEventListener:(name,handler)=>{listeners[name]=handler;}},
  });
  return{animations,listeners};
}

test('initial navigation never hides already-painted content or intercepts links',()=>{
  const n=navigation();
  assert.equal(n.animations.length,0);
  assert.equal(n.listeners.click,undefined);
  n.listeners.pageshow({persisted:false});
  assert.equal(n.animations.length,0);
});

test('back/forward restoration slides content without an opacity reset',()=>{
  const n=navigation();n.listeners.pageshow({persisted:true});
  assert.equal(n.animations.length,1);
  assert.equal(n.animations[0].frames[0].transform,'translateX(20px)');
  assert.equal(n.animations[0].frames.at(-1).transform,'translateX(0)');
  assert.ok(n.animations[0].frames.every(frame=>!('opacity' in frame)));
});

test('reduced-motion preference also disables restoration animation',()=>{
  const n=navigation(true);n.listeners.pageshow({persisted:true});
  assert.equal(n.animations.length,0);
});
