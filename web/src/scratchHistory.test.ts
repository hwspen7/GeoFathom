import {expect,it} from 'vitest';
import {ScratchHistory} from './scratchHistory';
import {localMeasurement,type ScratchFeature} from './scratch';
function item(id:string):ScratchFeature{
 const geometry:GeoJSON.Point={type:'Point',coordinates:[0,0]};
 return {id,name:id,geometry,measurement:localMeasurement(geometry),visible:true};
}
it('undoes create, delete and visibility without losing unrelated features',()=>{
 const a=item('scratch-a'),b=item('scratch-b'),h=new ScratchHistory([]);
 h.change(()=>[a]);h.change(old=>[...old,b]);h.change(old=>old.filter(f=>f.id!==a.id));
 expect(h.undo()).toEqual([a,b]);expect(h.redo()).toEqual([b]);
 h.change(old=>old.map(f=>({...f,visible:false})));expect(h.undo()).toEqual([b]);
 h.undo();expect(h.current).toEqual([a,b]);h.change(old=>old.filter(f=>f.id!==b.id));expect(h.canRedo).toBe(false);
});
it('does not restore a draft promoted to server storage',()=>{
 const h=new ScratchHistory([]);h.change(()=>[item('scratch-a')]);h.checkpoint([]);
 expect(h.canUndo).toBe(false);expect(h.canRedo).toBe(false);
});
