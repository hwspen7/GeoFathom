import type {ScratchFeature} from './scratch';
/** Immutable local document transactions. Selection is not a mutation. */
export class ScratchHistory {
 private past:ScratchFeature[][]=[];
 private future:ScratchFeature[][]=[];
 constructor(private value:ScratchFeature[]){}
 get current(){return this.value;}
 get canUndo(){return this.past.length>0;}
 get canRedo(){return this.future.length>0;}
 change(update:(old:ScratchFeature[])=>ScratchFeature[]){
   const next=update(this.value);
   if(next===this.value||JSON.stringify(next)===JSON.stringify(this.value))return this.value;
   this.past.push(this.value);if(this.past.length>50)this.past.shift();
   this.future=[];this.value=next;return next;
 }
 undo(){if(this.canUndo){this.future.push(this.value);this.value=this.past.pop()!;}return this.value;}
 redo(){if(this.canRedo){this.past.push(this.value);this.value=this.future.pop()!;}return this.value;}
 checkpoint(next:ScratchFeature[]){this.value=next;this.past=[];this.future=[];return next;}
}
