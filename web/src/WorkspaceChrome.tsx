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
  {id:'tools-spatial-science',label:'Spatial Analysis',description:'Spatial scientific computing and research figures'},
  {id:'tools-remote-sensing',label:'Remote Sensing',description:'Calibrated spectral, thermal, radar and temporal research'},
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

interface FeatureItem {id:string;name:string;revision?:number;layer_id?:string;geometry?:GeoJSON.Geometry}
interface FeatureLayer {id:string;name:string;visible:boolean|number;locked?:boolean|number}
export interface WorkspaceObjectGroup {
  id:string;name:string;items:FeatureItem[];selectedId:string|null;
  onOpen:(id:string)=>void;
  onRename?:(id:string,name:string)=>Promise<void>;
  onDelete?:(id:string)=>Promise<void>;
}
function ObjectRow({item,selected,disabled,locked,busy,onOpen,onRename,onDelete}:{
  item:FeatureItem;selected:boolean;disabled:boolean;locked:boolean;busy:boolean;
  onOpen:()=>void;onRename?:(name:string)=>Promise<void>;onDelete?:()=>Promise<void>;
}){
  const [renaming,setRenaming]=useState(false),[name,setName]=useState(item.name);
  const [working,setWorking]=useState(false),[error,setError]=useState('');
  async function mutate(action:()=>Promise<void>){
    if(working||busy)return;
    setWorking(true);setError('');
    try{await action();setRenaming(false);}
    catch(cause){setError(cause instanceof Error?cause.message:'Object action failed.');}
    finally{setWorking(false);}
  }
  return <div className={'workspace-object-row'+(selected?' is-selected':'')}
    role="group" aria-label={'Object '+item.name} data-object-id={item.id}>
    {renaming?<form className="workspace-object-rename" onSubmit={event=>{
      event.preventDefault();if(name.trim()&&onRename)void mutate(()=>onRename(name.trim()));
    }} onKeyDown={event=>{
      if(event.key==='Escape'){event.preventDefault();event.stopPropagation();setRenaming(false);setError('');}
    }}>
      <input autoFocus aria-label="Object name" value={name} maxLength={200} disabled={working||busy}
        onFocus={event=>event.currentTarget.select()} onChange={event=>setName(event.target.value)}/>
      <button type="submit" disabled={!name.trim()||working||busy}>Save name</button>
      <button type="button" disabled={working} onClick={()=>{setRenaming(false);setError('');}}>Cancel rename</button>
    </form>:<>
      <button type="button" className="workspace-object-select" disabled={disabled||busy||working}
        aria-label={item.name} aria-pressed={selected} onClick={onOpen}
        title={disabled?'Layer hidden':item.name}>
        <span>{item.name}{item.geometry&&<small className="workspace-object-type">{item.geometry.type}</small>}</span>
        {item.revision!==undefined&&<small title="Revision">r{item.revision}</small>}
      </button>
      {(onRename||onDelete)&&<div className="workspace-object-actions">
        {onRename&&<button type="button" aria-label="Rename object" title={locked?'Unlock layer to rename':'Rename '+item.name}
          disabled={locked||busy||working} onClick={()=>{setName(item.name);setError('');setRenaming(true);}}>Rename</button>}
        {onDelete&&<button type="button" aria-label="Delete object" title={locked?'Unlock layer to delete':'Delete '+item.name}
          disabled={locked||busy||working} onClick={()=>void mutate(onDelete)}>Delete</button>}
      </div>}
    </>}
    {error&&<small role="alert" className="workspace-object-error">{error}</small>}
  </div>;
}
function FeatureGroup({name,features,visible,selectedId,onOpen,search,locked=false,busy=false,onRename,onDelete,total=features.length}:{
  name:string;features:FeatureItem[];visible:boolean;selectedId:string|null;
  onOpen:(id:string)=>void;search:boolean;
  locked?:boolean;busy?:boolean;
  onRename?:(id:string,name:string)=>Promise<void>;onDelete?:(id:string)=>Promise<void>;
  total?:number;
}){
  const [expanded,setExpanded]=useState(true);
  return <details className="workspace-feature-group" open={search||expanded}
    onToggle={event=>{if(!search)setExpanded(event.currentTarget.open);}}>
    <summary><Layers3 size={13}/>{name}<small>{total}</small></summary>
    <div className="project-features">
      {features.map(item=><ObjectRow key={item.id} item={item}
        selected={selectedId===item.id} disabled={!visible} locked={locked} busy={busy}
        onOpen={()=>onOpen(item.id)}
        onRename={onRename?value=>onRename(item.id,value):undefined}
        onDelete={onDelete?()=>onDelete(item.id):undefined}/>)}
    </div>
  </details>;
}

/** Object actions use their owner's revisioned API or local undo history.
 * Renaming never needs to load or replace the object's geometry selection.
 */
export function WorkspaceFeatureTree<T extends FeatureItem>({
  layers,features,selectedId,onOpen,onRename,onDelete,busy=false,additionalGroups=[],pageSize=5,
}:{
  layers:readonly FeatureLayer[];features:readonly T[];
  selectedId:string|null;onOpen:(feature:T)=>void;
  onRename?:(feature:T,name:string)=>Promise<void>;onDelete?:(feature:T)=>Promise<void>;
  busy?:boolean;additionalGroups?:WorkspaceObjectGroup[];
  pageSize?:number;
}){
  const [filter,setFilter]=useState('');
  const [page,setPage]=useState(0);
  const lowered=filter.trim().toLocaleLowerCase();
  const visibleFeatures=features.filter(f=>!lowered||
    [f.name, f.id,layers.find(l=>l.id===f.layer_id)?.name??'']
      .some(s=>s.toLocaleLowerCase().includes(lowered)));
  const groups=[
    ...layers.map(l=>({id:l.id,name:l.name,visible:Boolean(l.visible),locked:Boolean(l.locked),
      items:visibleFeatures.filter(f=>f.layer_id===l.id)})),
    {id:'unassigned',name:'Unassigned / linked',visible:true,locked:false,
      items:visibleFeatures.filter(f=>!layers.some(l=>l.id===f.layer_id))},
  ].filter(g=>g.items.length>0);
  const extras=additionalGroups.map(group=>({...group,items:group.items.filter(item=>
    !lowered||[item.name,item.id,group.name].some(value=>value.toLocaleLowerCase().includes(lowered)))}))
    .filter(group=>group.items.length>0);
  const lookup=new Map(features.map(f=>[f.id,f]));
  // Page the whole object browser, rather than allocating a full page to
  // every layer. Many layers must not push selected objects below the dock.
  const rows=[...groups.flatMap(g=>g.items.map(item=>({key:g.id+':'+item.id,selected:item.id===selectedId}))),
    ...extras.flatMap(g=>g.items.map(item=>({key:g.id+':'+item.id,selected:item.id===g.selectedId})))];
  const selectedKey=rows.find(row=>row.selected)?.key??null;
  const pages:string[][]=[[]];
  for(const group of [...groups,...extras]){
    for(let start=0;start<group.items.length;start+=pageSize){
      const chunk=group.items.slice(start,start+pageSize).map(item=>group.id+':'+item.id);
      // Keep a small layer together: freshly split siblings must be visible
      // side by side, rather than stranded on opposite page boundaries.
      if(pages[pages.length-1].length+chunk.length>pageSize)pages.push(chunk);
      else pages[pages.length-1].push(...chunk);
    }
  }
  const lastPage=pages.length-1,currentPage=Math.min(page,lastPage);
  const offset=pages.slice(0,currentPage).reduce((sum,items)=>sum+items.length,0);
  const paged=new Set(pages[currentPage]);
  const selectedPage=pages.findIndex(items=>selectedKey!==null&&items.includes(selectedKey));
  useEffect(()=>{
    setPage(selectedPage>=0?selectedPage:0);
  },[selectedKey,selectedPage,filter,pageSize]);
  return <div className="workspace-feature-tree" role="region" aria-label="Project feature tree">
    <div className="workspace-tree-header"><strong>Features</strong><span>{features.length+additionalGroups.reduce((sum,g)=>sum+g.items.length,0)}</span></div>
    <label className="workspace-tree-filter"><Search size={13}/>
      <input aria-label="Filter project features" type="search"
        value={filter} placeholder="Filter name or layer"
        onChange={e=>{setFilter(e.target.value);setPage(0);}}/>
    </label>
    {groups.filter(g=>g.items.some(item=>paged.has(g.id+':'+item.id))).map(g=><FeatureGroup key={g.id} name={g.name}
      features={g.items.filter(item=>paged.has(g.id+':'+item.id))} total={g.items.length}
      visible={g.visible} search={Boolean(lowered)}
      selectedId={selectedId} locked={g.locked} busy={busy}
      onRename={onRename?async(id,name)=>{const f=lookup.get(id);if(f)await onRename(f,name);}:undefined}
      onDelete={onDelete?async id=>{const f=lookup.get(id);if(f)await onDelete(f);}:undefined}
      onOpen={id=>{const f=lookup.get(id);if(f)onOpen(f);}}/>)}
    {extras.filter(g=>g.items.some(item=>paged.has(g.id+':'+item.id))).map(g=><FeatureGroup key={g.id} name={g.name}
      features={g.items.filter(item=>paged.has(g.id+':'+item.id))} total={g.items.length} visible
      selectedId={g.selectedId} search={Boolean(lowered)} busy={busy}
      onOpen={g.onOpen} onRename={g.onRename} onDelete={g.onDelete}/>)}
    {pages.length>1&&<div className="workspace-object-pager">
      <button type="button" aria-label="Previous objects" disabled={currentPage===0} onClick={()=>setPage(currentPage-1)}>Previous</button>
      <span>{offset+1}–{offset+paged.size} / {rows.length}</span>
      <button type="button" aria-label="Next objects" disabled={currentPage===lastPage} onClick={()=>setPage(currentPage+1)}>Next</button>
    </div>}
    {!groups.length&&!extras.length&&<small className="workspace-tree-empty">
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
