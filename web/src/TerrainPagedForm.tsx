import {Children,Fragment,isValidElement,useLayoutEffect,useRef,useState,type ReactNode} from 'react';
import {ChevronLeft,ChevronRight} from 'lucide-react';

type FormRow={key:string;node:ReactNode};
function rowsFrom(children:ReactNode,prefix=''):FormRow[]{
 // Preserve React identity when optional warnings, credentials or parameter rows appear.
 return Children.toArray(children).flatMap((child,index)=>{
  const key=prefix+(isValidElement(child)?child.key??index:index);
  return isValidElement<{children?:ReactNode}>(child)&&child.type===Fragment?rowsFrom(child.props.children,key+'/'):[{key,node:child}];
 });
}
type Placement={page:number;top:number};
export function paginateTerrainRows(heights:number[],capacity:number,gap=6):Placement[]{
 let page=0,top=0;
 return heights.map(height=>{
  if(top>0&&top+height>capacity){page++;top=0;}
  const entry={page,top};top+=height+gap;return entry;
 });
}
/** All inputs remain mounted and controlled by the workbench. Only the
 * current page is interactive; other rows are measured at the same width. */
export default function TerrainPagedForm({children,active,name,resetKey}:{children:ReactNode;active:boolean;name:string;resetKey?:string}){
 const rows=rowsFrom(children);
 const rowKeys=JSON.stringify(rows.map(row=>row.key));
 const host=useRef<HTMLDivElement>(null);
 const [layout,setLayout]=useState<Placement[]>([]);
 const [page,setPage]=useState(0);
 useLayoutEffect(()=>{setPage(0);},[resetKey]);
 useLayoutEffect(()=>{
  if(!active||!host.current)return;
  const node=host.current;
  const measure=()=>{
   if(!node.clientHeight)return;
   const entries=Array.from(node.children) as HTMLElement[];
   const next=paginateTerrainRows(entries.map(el=>el.offsetHeight),node.clientHeight);
   setLayout(old=>JSON.stringify(old)===JSON.stringify(next)?old:next);
  };
  measure();
  const observer=typeof ResizeObserver==='undefined'?null:new ResizeObserver(measure);
  observer?.observe(node);
  for(const child of Array.from(node.children))observer?.observe(child);
  return()=>observer?.disconnect();
 },[active,rowKeys,resetKey]);
 const count=Math.max(1,1+(layout[layout.length-1]?.page??0));
 const current=Math.min(page,count-1);
 return <div className="terrain-paged-form professional-form" aria-label={name}>
  <div className="terrain-page-viewport" ref={host}>
   {rows.map((row,i)=>{
    const pos=layout[i];const visible=(pos?.page??0)===current;
    return <div className="terrain-page-row" key={row.key} aria-hidden={!visible} inert={!visible}
      style={{top:pos?.top??0,visibility:visible?'visible':'hidden',pointerEvents:visible?'auto':'none'}}>{row.node}</div>;
   })}
  </div>
  <div className="workspace-object-pager terrain-form-pager" style={{visibility:count===1?'hidden':'visible'}} aria-hidden={count===1}>
    <button type="button" title="Previous terrain page" aria-label="Previous terrain page" disabled={current===0} onClick={()=>setPage(current-1)}><ChevronLeft size={14}/></button>
    <span>{current+1} / {count}</span>
    <button type="button" title="Next terrain page" aria-label="Next terrain page" disabled={current>=count-1} onClick={()=>setPage(current+1)}><ChevronRight size={14}/></button>
  </div>
 </div>;
}
