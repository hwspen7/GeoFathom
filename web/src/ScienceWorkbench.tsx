import {spatialMetricLabel,spatialMetricValue} from './spatialPresentation';

type Tab='overview'|'figures'|'data';
// Shared presentation only; analysis and exports remain owned by each module.
export function ScienceResultTabs({value,onChange}:{value:Tab;onChange:(tab:Tab)=>void}){
 return <nav className="temporal-tabs" aria-label="Result views">{(['overview','figures','data'] as const).map(tab=><button key={tab} type="button" aria-pressed={value===tab} onClick={()=>onChange(tab)}>{tab[0].toUpperCase()+tab.slice(1)}</button>)}</nav>;
}
export function ScienceMetrics({entries,limit=12}:{entries:ReadonlyArray<readonly [string,unknown]>;limit?:number}){
 const seen=new Set<string>();
 const visible=entries.filter(([key,value])=>{if(seen.has(key)||typeof value!=='number'||!Number.isFinite(value))return false;seen.add(key);return true;}).slice(0,limit);
 return visible.length?<div className="temporal-metrics science-metrics">{visible.map(([key,value])=><div key={key}><small>{spatialMetricLabel(key)}</small><strong>{spatialMetricValue(key,value as number)}</strong></div>)}</div>:null;
}
