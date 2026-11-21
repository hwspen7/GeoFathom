/* Spatial-hash snap index built from map coordinates once per map view change.

The browser must not call FastAPI or scan all visible vertices on every drag
mousemove. Server-side programmatic GIS uses the C++ BVH instead.
*/
import type {Position} from './editing';

type Segment={
  a:Position;b:Position;
  ax:number;ay:number;bx:number;by:number;
  vertex:boolean;
};
type Snapped={point:Position;kind:'vertex'|'edge'|'none';distancePx:number};

export class PixelSnapIndex {
  private readonly buckets=new Map<string,number[]>();
  private readonly longSegments:number[]=[];
  private readonly segments:Segment[]=[];
  constructor(
    paths:Position[][], project:(position:Position)=>Position,
    private readonly cellSize=48,
  ) {
    if(cellSize<=0)throw new Error('Cell size must be positive.');
    const insert=(entry:Segment)=>{
      const n=this.segments.push(entry)-1;
      const x0=Math.floor(Math.min(entry.ax,entry.bx)/cellSize);
      const x1=Math.floor(Math.max(entry.ax,entry.bx)/cellSize);
      const y0=Math.floor(Math.min(entry.ay,entry.by)/cellSize);
      const y1=Math.floor(Math.max(entry.ay,entry.by)/cellSize);
      if((x1-x0+1)*(y1-y0+1)>100) {
        this.longSegments.push(n);
        return;
      }
      for(let x=x0;x<=x1;x++)for(let y=y0;y<=y1;y++){
        const key=x+':'+y;
        const bucket=this.buckets.get(key)??[];
        bucket.push(n);
        this.buckets.set(key,bucket);
      }
    };
    for(const path of paths){
      const coords=path.map(project);
      for(let i=0;i<path.length;i++){
        const p=coords[i];
        insert({a:path[i],b:path[i],ax:p[0],ay:p[1],bx:p[0],by:p[1],vertex:true});
        if(i+1<path.length) {
          const next=coords[i+1];
          insert({a:path[i],b:path[i+1],ax:p[0],ay:p[1],
                  bx:next[0],by:next[1],vertex:false});
        }
      }
    }
  }
  get size():number{return this.segments.length;}

  snap(pixel:Position,threshold=12,exclude?:Position):Snapped {
    let best=threshold,point:Position=[...pixel],kind:Snapped['kind']='none';
    const x=Math.floor(pixel[0]/this.cellSize);
    const y=Math.floor(pixel[1]/this.cellSize);
    const refs=new Set(this.longSegments);
    for(let dx=-1;dx<=1;dx++)for(let dy=-1;dy<=1;dy++){
      for(const id of this.buckets.get((x+dx)+':'+(y+dy))??[])refs.add(id);
    }
    // A vertex wins over an edge when both are within the snap tolerance.
    for(const mode of [true,false]){
      if(kind==='vertex')break;
      for(const id of refs){
        const edge=this.segments[id];
        if(edge.vertex!==mode)continue;
        if(mode&&exclude&&edge.a[0]===exclude[0]&&edge.a[1]===exclude[1])continue;
        const dx=edge.bx-edge.ax,dy=edge.by-edge.ay;
        const length=dx*dx+dy*dy;
        const t=length>0?Math.max(0,Math.min(1,
          ((pixel[0]-edge.ax)*dx+(pixel[1]-edge.ay)*dy)/length)):0;
        const distance=Math.hypot(pixel[0]-edge.ax-t*dx,pixel[1]-edge.ay-t*dy);
        if(distance<best){
          best=distance;
          point=[edge.a[0]+(edge.b[0]-edge.a[0])*t,
                 edge.a[1]+(edge.b[1]-edge.a[1])*t];
          kind=mode?'vertex':'edge';
        }
      }
    }
    return {point,kind,distancePx:best};
  }
}
