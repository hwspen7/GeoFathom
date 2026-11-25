import type {Position} from './editing';
import type {ProfileSample} from './TerrainCharts';

/** Return the nearest actual measured profile station to a screen pixel.
 * The projection and hit tolerance are screen-pixel based, independent of CRS. */
export function nearestProfileSample(
 samples:ProfileSample[],pointer:{x:number;y:number},
 project:(position:Position)=>{x:number;y:number},hitPx=16,
):number|null{
 if(!samples.length||hitPx<=0)return null;
 let bestIndex:number|null=null,best=hitPx*hitPx;
 let prev:{index:number;x:number;y:number}|null=null;
 for(let i=0;i<samples.length;i++){
  const coord=samples[i].coordinate;
  if(!coord||!Number.isFinite(coord[0])||!Number.isFinite(coord[1])){prev=null;continue;}
  const p=project(coord);
  if(!Number.isFinite(p.x)||!Number.isFinite(p.y)){prev=null;continue;}
  const dx=pointer.x-p.x,dy=pointer.y-p.y,dd=dx*dx+dy*dy;
  if(dd<=best){best=dd;bestIndex=i;}
  if(prev){
   const ax=p.x-prev.x,ay=p.y-prev.y,len=ax*ax+ay*ay;
   const t=len>0?Math.max(0,Math.min(1,((pointer.x-prev.x)*ax+(pointer.y-prev.y)*ay)/len)):0;
   const vx=pointer.x-(prev.x+t*ax),vy=pointer.y-(prev.y+t*ay),d=vx*vx+vy*vy;
   if(d<best){
    best=d;
    const station=samples[prev.index].distance_m+
      t*(samples[i].distance_m-samples[prev.index].distance_m);
    bestIndex=Math.abs(station-samples[prev.index].distance_m)<
      Math.abs(station-samples[i].distance_m)?prev.index:i;
   }
  }
  prev={index:i,x:p.x,y:p.y};
 }
 return bestIndex;
}
