/** Bound coordinate marker density at overview zooms without simplifying the
 * underlying survey polygon or deleting any actual vertex. */
export function boundaryNodeVisible(
 index:number,count:number,zoom:number,editing:boolean,selected:boolean,
):boolean{
 if(selected)return true;
 // Full-size edit nodes are rendered separately; no duplicate compact markers.
 if(editing)return false;
 const limit=zoom<12?16:zoom<15?48:zoom<17?120:Infinity;
 if(count<=limit)return true;
 return index%Math.ceil(count/limit)===0;
}
