const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

function modal(success=true){
  const document={activeElement:{focus(){}}};
  class Element extends EventTarget{
    constructor(){super();this.hidden=false;this.disabled=false;this.open=false;this.textContent='';}
    getBoundingClientRect(){return{left:100,top:100,right:500,bottom:500};}
    setAttribute(){} focus(){document.activeElement=this;}
    querySelector(selector){return this.parts[selector];}
    querySelectorAll(){return this.inputs||[];}
    reset(){} reportValidity(){return true;}
    showModal(){this.open=true;}close(){this.open=false;this.dispatchEvent(new Event('close'));}
    set innerHTML(value){
      const form=new Element();form.parts={'[type=submit]':new Element()};form.inputs=[new Element(),new Element()];
      this.parts={'form':form,'[data-cancel]':new Element(),'.modal-error':new Element(),'[data-loading]':new Element()};
    }
  }
  const picker=new Element();picker.options=[{value:'old',textContent:'Existing piece'}];picker.value='old';
  picker.add=option=>picker.options.push(option);const trigger=new Element();picker.closest=()=>({querySelector:()=>trigger});
  let dialog=null,changes=0,submitted=null;picker.addEventListener('change',()=>changes++);
  document.createElement=()=>new Element();document.body={append:element=>{dialog=element;}};
  document.querySelector=()=>picker;document.querySelectorAll=()=>[picker];document.addEventListener=()=>{};
  const window={};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../frontend/static/piece-modal.js'),'utf8'),{
    document,window,Event,URLSearchParams,location:{search:'',pathname:'/live'},history:{replaceState(){}},
    FormData:class{constructor(form){this.form=form;}},Option:class{constructor(text,value){this.textContent=text;this.value=value;}},
    fetch:async(url,args)=>{submitted={url,args};return{ok:success,json:async()=>success?{id:'new',title:'New score'}:{error:'Choose a MusicXML file.'}};},
  });
  return{api:window.SoundwavesPieces,dialog,picker,changes:()=>changes,submitted:()=>submitted};
}

test('successful upload selects the new piece and notifies the existing page',async()=>{
  const p=modal();p.api.open(p.picker);assert.equal(p.dialog.open,true);
  p.dialog.querySelector('form').dispatchEvent(new Event('submit',{cancelable:true}));
  await new Promise(setImmediate);
  assert.equal(p.submitted().url,'/api/pieces/upload');
  assert.equal(p.picker.value,'new');assert.equal(p.changes(),1);assert.equal(p.dialog.open,false);
  assert.equal(p.picker.options.at(-1).textContent,'New score');
});

test('failed upload keeps the modal open with the original selection',async()=>{
  const p=modal(false);p.api.open(p.picker);
  p.dialog.querySelector('form').dispatchEvent(new Event('submit',{cancelable:true}));
  await new Promise(setImmediate);
  assert.equal(p.dialog.open,true);assert.equal(p.picker.value,'old');assert.equal(p.changes(),0);
  assert.equal(p.dialog.querySelector('.modal-error').textContent,'Choose a MusicXML file.');
  assert.equal(p.dialog.querySelector('[data-cancel]').disabled,false);
});

function pointer(target,type,x,y){
  const event=new Event(type,{bubbles:true});
  Object.defineProperties(event,{clientX:{value:x},clientY:{value:y}});
  target.dispatchEvent(event);
}

test('clicking the backdrop cancels while clicks inside the dialog keep it open',()=>{
  const p=modal();p.api.open(p.picker);
  pointer(p.dialog,'pointerdown',200,200);pointer(p.dialog,'click',200,200);
  assert.equal(p.dialog.open,true);
  pointer(p.dialog,'pointerdown',20,20);pointer(p.dialog,'click',20,20);
  assert.equal(p.dialog.open,false);assert.equal(p.changes(),0);
});
