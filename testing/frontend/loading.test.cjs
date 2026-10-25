const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loading() {
  const document = {activeElement: null};
  class Element extends EventTarget {
    constructor() { super(); this.hidden=false; this.inert=false; this.textContent=''; this.classes=new Set();
      this.classList={add:x=>this.classes.add(x),remove:x=>this.classes.delete(x)};
    }
    setAttribute() {}
    focus() {document.activeElement=this;}
    querySelector(selector) {return this.parts[selector];}
    set innerHTML(value) {
      this.parts=Object.fromEntries(['.analysis-status','.analysis-elapsed','a','button','h2'].map(k=>[k,new Element()]));
    }
  }
  const main=new Element(), previous=new Element(); previous.focus();
  const body=new Element(); body.children=[main]; body.append=element=>body.children.push(element);
  document.body=body; document.createElement=()=>new Element(); document.querySelectorAll=()=>[];
  const window={addEventListener(){}};
  let cleared=0;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../frontend/static/loading.js'),'utf8'),{
    document,window,URL:{createObjectURL:()=> 'blob:take',revokeObjectURL(){}},Date,
    setInterval:()=>1,clearInterval:()=>cleared++,
  });
  return {api:window.SoundwavesLoading,screen:body.children[1],main,previous,document,cleared:()=>cleared};
}

test('analysis screen focuses the dialog and restores the page when dismissed',()=>{
  const p=loading();p.api.show();
  assert.equal(p.screen.hidden,false);assert.equal(p.main.inert,true);
  assert.equal(p.document.activeElement,p.screen);
  p.api.hide();assert.equal(p.main.inert,false);assert.equal(p.screen.hidden,true);
  assert.equal(p.document.activeElement,p.previous);
});

test('failed analysis keeps the recording download and provides a return action',()=>{
  const p=loading();p.api.show();p.api.setRecording({name:'take.webm'});p.api.fail('Try a shorter take.');
  const download=p.screen.querySelector('a'),back=p.screen.querySelector('button');
  assert.equal(download.href,'blob:take');assert.equal(download.download,'take.webm');assert.equal(download.hidden,false);
  assert.equal(p.screen.querySelector('.analysis-status').textContent,'Try a shorter take.');
  assert.equal(back.hidden,false);assert.ok(p.cleared()>0);
  back.dispatchEvent(new Event('click'));assert.equal(p.screen.hidden,true);
});
