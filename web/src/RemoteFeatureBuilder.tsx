import {useEffect,useState} from 'react';

export interface ModelFeatureBand {image_id:string;band:number;encoding:string;scale:number;offset:number;unit:string;quantity?:string}
interface Row extends ModelFeatureBand {role:string}
const quantities=[['reflectance','Reflectance'],['slope','Slope (degrees)'],['aspect','Aspect (degrees)'],['distance_m','Elevation / distance (m)'],['power','SAR linear power'],['db','SAR backscatter (dB)'],['fraction','Fraction'],['kelvin','Temperature (K)'],['numeric','Other declared measurement']];

export default function RemoteFeatureBuilder({assets,bound,onChange}:{assets:Array<{id:string;name:string}>;bound:Record<string,ModelFeatureBand>|null;onChange:(features:Record<string,ModelFeatureBand>|null)=>void}){
 const [rows,setRows]=useState<Row[]>([]),[manual,setManual]=useState(false);
 const valid=rows.length>0&&rows.length<=16&&rows.every(r=>/^[a-zA-Z][a-zA-Z0-9_]{0,79}$/.test(r.role)&&!!r.image_id&&Number.isInteger(r.band)&&r.band>0&&r.band<=1024&&(r.quantity!=='numeric'||!!r.unit.trim()))&&new Set(rows.map(r=>r.role)).size===rows.length;
 useEffect(()=>{onChange(manual?(valid?Object.fromEntries(rows.map(({role,...band})=>[role,band])):null):bound);},[manual,rows,valid,bound,onChange]);
 function update(i:number,patch:Partial<Row>){setRows(old=>old.map((r,j)=>i===j?{...r,...patch}:r));}
 return <details><summary>Multi-source model features</summary>
 <label><input type="checkbox" checked={manual} onChange={e=>{setManual(e.target.checked);if(e.target.checked&&!rows.length&&bound)setRows(Object.entries(bound).map(([role,b])=>({role,...b,quantity:b.quantity??'reflectance'})));}}/>Build a custom feature set</label>
 {manual&&<><p>Combine prepared optical, terrain, SAR and LiDAR rasters on the same grid. Feature names and physical units must match when reusing the model.</p>
 {rows.map((r,i)=><div key={i}><label>Feature {i+1} name<input value={r.role} onChange={e=>update(i,{role:e.target.value})}/></label><label>Feature {i+1} imagery<select value={r.image_id} onChange={e=>update(i,{image_id:e.target.value})}><option value="">Choose imagery</option>{assets.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select></label>
 <label>Feature {i+1} band<input type="number" min="1" max="1024" value={r.band} onChange={e=>update(i,{band:Number(e.target.value)})}/></label>
 <label>Feature {i+1} quantity<select value={r.quantity} onChange={e=>update(i,{quantity:e.target.value,unit:''})}>{quantities.map(([id,label])=><option value={id} key={id}>{label}</option>)}</select></label>
 <label>Feature {i+1} unit<input value={r.unit} onChange={e=>update(i,{unit:e.target.value})}/></label>
 <button onClick={()=>setRows(old=>old.filter((_,j)=>j!==i))}>Remove feature {i+1}</button></div>)}
 <button disabled={rows.length>=16} onClick={()=>setRows(old=>[...old,{role:'feature_'+(old.length+1),image_id:'',band:1,encoding:'metadata',scale:1,offset:0,unit:'',quantity:'numeric'}])}>Add model feature</button>
 {!valid&&<p>Choose unique feature names, imagery and declared numeric units.</p>}</>}
 </details>;
}
