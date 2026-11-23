/** Shared research workspace chrome. Module navigation and command discovery
 * are independent of GIS/Terrain internals so future workbenches can reuse them.
 */
import {useEffect,useMemo,useState,type ReactNode} from 'react';
import {Search,Layers3} from 'lucide-react';

export interface WorkspaceModule {id:string;label:string;description:string}
export const WORKSPACE_MODULES:readonly WorkspaceModule[]=[
  {id:'tools-survey',label:'Survey',description:'Sketch and edit geometry'},
  {id:'tools-gis',label:'GIS',description:'Geospatial operations'},
  {id:'tools-spatial',label:'Analysis',description:'Spatial processing'},
  {id:'tools-terrain',label:'Terrain',description:'Elevation and hydrology'},
  {id:'tools-raster',label:'Raster / AI',description:'Imagery and raster analysis'},
  {id:'tools-style',label:'Cartography',description:'Map layout and labels'},
  {id:'tools-services',label:'Data',description:'Import, manage, polygonize and connect GIS datasets'},
  {id:'tools-export',label:'Export',description:'Vector files, map PDFs, GeoTIFFs and research reports'},
  {id:'tools-ai',label:'Assistant',description:'Local assistant'},
];

export interface WorkspaceCommand {
  id:string;label:string;group:string;description?:string;shortcut?:string;
  keywords?:string;disabled?:boolean;run:()=>void;
}
export function searchWorkspaceCommands(commands:readonly WorkspaceCommand[],search:string){
  const terms=search.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  if(!terms.length)return [...commands];
  return commands.filter(command=>{
    const text=[command.label,command.group,command.description??'',
      command.keywords??'',command.shortcut??''].join(' ').toLocaleLowerCase();
    return terms.every(term=>text.includes(term));
  });
}

export function WorkspaceModuleBar({active,open,onActivate}:{
  active:string;open:boolean;onActivate:(id:string)=>void;
}){
  return <nav aria-label="Workspace tools" className="gis-menu workspace-module-bar">
    <div className="workspace-module-buttons">
      {WORKSPACE_MODULES.map(module=>
        <button key={module.id} type="button"
          aria-controls={module.id}
          aria-pressed={open&&active===module.id}
          title={module.description}
          onClick={()=>onActivate(module.id)}>{module.label}</button>)}
    </div>
    <select className="workspace-module-compact" aria-label="Workspace module"
      value={active} onChange={event=>onActivate(event.target.value)}>
      {WORKSPACE_MODULES.map(module=><option key={module.id} value={module.id}>{module.label}</option>)}
    </select>
  </nav>;
}

export function WorkspaceCommandPalette({open,commands,onClose}:{
  open:boolean;commands:readonly WorkspaceCommand[];onClose:()=>void;
}){
  const [query,setQuery]=useState('');
  const [index,setIndex]=useState(0);
  useEffect(()=>{if(open){setQuery('');setIndex(0);}},[open]);
  const matches=useMemo(()=>searchWorkspaceCommands(commands,query),[commands,query]);
  if(!open)return null;
  function invoke(command:WorkspaceCommand){
    if(command.disabled)return;
    onClose();
    command.run();
  }
  return <div className="workspace-command-shade" onMouseDown={event=>{
    if(event.target===event.currentTarget)onClose();
  }}>
    <div role="dialog" aria-modal="true" aria-label="Workspace commands"
      className="workspace-command-dialog">
      <div className="workspace-command-search"><Search size={16}/>
        <input autoFocus type="search" value={query}
          aria-label="Search workspace commands"
          placeholder="Search tools, actions and modules…"
          onChange={event=>{setQuery(event.target.value);setIndex(0);}}
          onKeyDown={event=>{
            if(event.key==='Escape'){event.preventDefault();onClose();}
            if(event.key==='ArrowDown'){event.preventDefault();setIndex(old=>Math.min(matches.length-1,old+1));}
            if(event.key==='ArrowUp'){event.preventDefault();setIndex(old=>Math.max(0,old-1));}
            if(event.key==='Enter'&&matches[index]&&!matches[index].disabled){
              event.preventDefault();invoke(matches[index]);
            }
          }}/>
        <kbd>Esc</kbd>
      </div>
      <div className="workspace-command-results" role="group" aria-label="Matching commands">
        {matches.map((command,i)=><button type="button"
          className={i===index?'is-focused':''}
          key={command.id} disabled={command.disabled}
          onMouseEnter={()=>setIndex(i)}
          onClick={()=>invoke(command)}>
          <span className="workspace-command-title">{command.label}
            <small>{command.group}{command.description?' · '+command.description:''}</small>
          </span>
          {command.shortcut&&<kbd>{command.shortcut}</kbd>}
        </button>)}
        {!matches.length&&<div className="workspace-command-empty">No matching workspace actions</div>}
      </div>
      <footer>↑ ↓ Navigate · Enter Run · Esc Close</footer>
    </div>
  </div>;
}

interface FeatureItem {id:string;name:string;revision?:number;layer_id?:string}
interface FeatureLayer {id:string;name:string;visible:boolean|number}
function FeatureGroup({name,features,visible,selectedId,onOpen,search}:{
  name:string;features:FeatureItem[];visible:boolean;selectedId:string|null;
  onOpen:(id:string)=>void;search:boolean;
}){
  const [expanded,setExpanded]=useState(true);
  return <details className="workspace-feature-group" open={search||expanded}
    onToggle={event=>{if(!search)setExpanded(event.currentTarget.open);}}>
    <summary><Layers3 size={13}/>{name}<small>{features.length}</small></summary>
    <div className="project-features">
      {features.map(item=><button key={item.id} type="button"
        disabled={!visible} onClick={()=>onOpen(item.id)}
        aria-pressed={selectedId===item.id}
        className={selectedId===item.id?'active':''}
        title={visible?item.name:'Layer hidden: '+name}>
        <span>{item.name}</span>
        {item.revision!==undefined&&<small>r{item.revision}</small>}
      </button>)}
    </div>
  </details>;
}

/** The shared document/object tree only selects objects: mutations continue
 * through the owning project's revisioned API, avoiding duplicate state.
 */
export function WorkspaceFeatureTree<T extends FeatureItem>({
  layers,features,selectedId,onOpen,
}:{
  layers:readonly FeatureLayer[];features:readonly T[];
  selectedId:string|null;onOpen:(feature:T)=>void;
}){
  const [filter,setFilter]=useState('');
  const lowered=filter.trim().toLocaleLowerCase();
  const visibleFeatures=features.filter(f=>!lowered||
    [f.name, f.id,layers.find(l=>l.id===f.layer_id)?.name??'']
      .some(s=>s.toLocaleLowerCase().includes(lowered)));
  const groups=[
    ...layers.map(l=>({id:l.id,name:l.name,visible:Boolean(l.visible),
      items:visibleFeatures.filter(f=>f.layer_id===l.id)})),
    {id:'unassigned',name:'Unassigned / linked',visible:true,
      items:visibleFeatures.filter(f=>!layers.some(l=>l.id===f.layer_id))},
  ].filter(g=>g.items.length>0);
  const lookup=new Map(features.map(f=>[f.id,f]));
  return <div className="workspace-feature-tree" role="region" aria-label="Project feature tree">
    <div className="workspace-tree-header"><strong>Features</strong><span>{features.length}</span></div>
    <label className="workspace-tree-filter"><Search size={13}/>
      <input aria-label="Filter project features" type="search"
        value={filter} placeholder="Filter name or layer"
        onChange={e=>setFilter(e.target.value)}/>
    </label>
    {groups.map(g=><FeatureGroup key={g.id} name={g.name} features={g.items}
      visible={g.visible} search={Boolean(lowered)}
      selectedId={selectedId}
      onOpen={id=>{const f=lookup.get(id);if(f)onOpen(f);}}/>)}
    {!groups.length&&<small className="workspace-tree-empty">
      {lowered?'No matching features':'No saved features yet.'}</small>}
  </div>;
}

export function WorkspaceDockHeading({children,actions}:{
  children:ReactNode;actions?:ReactNode;
}){
  return <div className="dock-heading workspace-dock-heading">
    <span>{children}</span>{actions&&<span className="workspace-dock-actions">{actions}</span>}
  </div>;
}
