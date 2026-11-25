import {SectionIcon} from './SectionIcon';
/** Shared research workspace chrome. Module navigation and command discovery
 * are independent of GIS/Terrain internals so future workbenches can reuse them.
 */
import {useEffect,useMemo,useRef,useState,type ReactNode} from 'react';
import {Search,ListFilter,SquarePen,Trash2,MapPin,Minus,Shapes,Pentagon,ChevronLeft,ChevronRight,Check,X} from 'lucide-react';

export interface WorkspaceModule {id:string;label:string;description:string;hint:string}
export const WORKSPACE_MODULES:readonly WorkspaceModule[]=[
  {id:'tools-survey',label:'Survey',description:'Sketch and edit geometry',hint:'Draw and edit geometry'},
  {id:'tools-gis',label:'GIS',description:'Geospatial operations',hint:'Geospatial operations'},
  {id:'tools-spatial',label:'Analysis',description:'Spatial processing',hint:'Spatial processing'},
  {id:'tools-terrain',label:'Terrain',description:'Elevation and hydrology',hint:'Elevation and hydrology'},
  {id:'tools-spatial-science',label:'Spatial',description:'Spatial scientific computing and research figures',hint:'Spatial research and figures'},
  {id:'tools-network-science',label:'Network',description:'Network analysis, accessibility and raster exposure research',hint:'Networks and accessibility'},
  {id:'tools-spacetime',label:'Temporal',description:'Spatiotemporal analysis of raster cubes, trends, dependence and prediction',hint:'Space-time trends and prediction'},
  {id:'tools-lidar',label:'LiDAR',description:'3D and LiDAR point-cloud research',hint:'3D point-cloud research'},
  {id:'tools-remote-sensing',label:'Sensing',description:'Remote sensing: calibrated spectral, thermal, radar and temporal research',hint:'Spectral, thermal and radar'},
  {id:'tools-raster',label:'Raster',description:'Imagery, raster analysis and AI extraction',hint:'Raster and AI extraction'},
  {id:'tools-style',label:'Mapping',description:'Cartography: map layout and labels',hint:'Map layout and labels'},
  {id:'tools-services',label:'Data',description:'Import, manage, polygonize and connect GIS datasets',hint:'Import and manage datasets'},
  {id:'tools-export',label:'Export',description:'Vector files, map PDFs, GeoTIFFs and research reports',hint:'Export files and reports'},
  {id:'tools-ai',label:'Assistant',description:'Local assistant',hint:'Local AI assistant'},
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
          title={module.hint}
          onClick={()=>onActivate(module.id)}>{module.label}</button>)}
    </div>
    <select className="workspace-module-compact" aria-label="Workspace module"
      title={WORKSPACE_MODULES.find(module=>module.id===active)?.hint??'Choose workspace module'}
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
          placeholder="Search tools, actions and modules"
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
function ObjectRow({item,selected,disabled,locked,busy,onOpen,onRename,onDelete,compact=false,layerName}:{
  item:FeatureItem;selected:boolean;disabled:boolean;locked:boolean;busy:boolean;
  onOpen:()=>void;onRename?:(name:string)=>Promise<void>;onDelete?:()=>Promise<void>;compact?:boolean;layerName?:string;
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
  const GeometryIcon=item.geometry?.type.includes('Point')?MapPin:item.geometry?.type.includes('Line')?Minus:item.geometry?.type==='Polygon'?Pentagon:Shapes;
  return <div className={'workspace-object-row'+(selected?' is-selected':'')+(compact?' compact-object-row':'')}
    role="group" aria-label={'Object '+item.name} data-object-id={item.id} data-geometry-type={item.geometry?.type??'unknown'} data-object-locked={locked}>
    {renaming?<form className="workspace-object-rename" onSubmit={event=>{
      event.preventDefault();if(name.trim()&&onRename)void mutate(()=>onRename(name.trim()));
    }} onKeyDown={event=>{
      if(event.key==='Escape'){event.preventDefault();event.stopPropagation();setRenaming(false);setError('');}
    }}>
      <input autoFocus aria-label="Object name" value={name} maxLength={200} disabled={working||busy}
        onFocus={event=>event.currentTarget.select()} onChange={event=>setName(event.target.value)}/>
      <button type="submit" className="object-rename-confirm" aria-label="Save name" title="Save name (Enter)" disabled={!name.trim()||working||busy}><Check size={13} aria-hidden="true"/></button>
      <button type="button" className="object-rename-cancel" aria-label="Cancel rename" title="Cancel rename (Esc)" disabled={working} onClick={()=>{setRenaming(false);setError('');}}><X size={13} aria-hidden="true"/></button>
    </form>:<>
      <button type="button" className="workspace-object-select" disabled={disabled||busy||working}
        aria-label={item.name} aria-pressed={selected} onClick={onOpen}
        title={disabled?'Layer hidden':[item.name,item.geometry?.type,layerName].filter(Boolean).join(' · ')}>
        {compact&&<span className="workspace-object-symbol"><GeometryIcon size={13} aria-hidden="true"/></span>}
        <span>{item.name}{!compact&&item.geometry&&<small className="workspace-object-type">{item.geometry.type}</small>}</span>
        {item.revision!==undefined&&<small title="Revision">r{item.revision}</small>}
      </button>
      {(onRename||onDelete)&&<div className="workspace-object-actions">
        {onRename&&<button type="button" aria-label="Rename object" title={locked?'Unlock layer to rename':'Rename '+item.name}
          disabled={locked||busy||working} onClick={()=>{setName(item.name);setError('');setRenaming(true);}}>{compact?<SquarePen size={12} aria-hidden="true"/>:'Rename'}</button>}
        {onDelete&&<button type="button" aria-label="Delete object" title={locked?'Unlock layer to delete':'Delete '+item.name}
          disabled={locked||busy||working} onClick={()=>void mutate(onDelete)}>{compact?<Trash2 size={12} aria-hidden="true"/>:'Delete'}</button>}
      </div>}
    </>}
    {error&&<small role="alert" className="workspace-object-error">{error}</small>}
  </div>;
}
function FeatureGroup({name,features,visible,selectedId,onOpen,search,locked=false,busy=false,onRename,onDelete,total=features.length,alwaysOpen=false}:{
  name:string;features:FeatureItem[];visible:boolean;selectedId:string|null;
  onOpen:(id:string)=>void;search:boolean;
  locked?:boolean;busy?:boolean;
  onRename?:(id:string,name:string)=>Promise<void>;onDelete?:(id:string)=>Promise<void>;
  total?:number;alwaysOpen?:boolean;
}){
  const [expanded,setExpanded]=useState(true);
  const Group=alwaysOpen?'section':'details';
  return <Group className="workspace-feature-group" {...(alwaysOpen?{}:{open:search||expanded,onToggle:(event:React.SyntheticEvent<HTMLElement>)=>{if(!search)setExpanded((event.currentTarget as HTMLDetailsElement).open);}})}>
    {alwaysOpen?<h4 className="gis-static-layer-heading"><SectionIcon role="layerGroup"/>{name}<small>{total}</small></h4>:<summary><SectionIcon role="layerGroup"/>{name}<small>{total}</small></summary>}
    <div className="project-features">
      {features.map(item=><ObjectRow key={item.id} item={item}
        selected={selectedId===item.id} disabled={!visible} locked={locked} busy={busy}
        onOpen={()=>onOpen(item.id)}
        onRename={onRename?value=>onRename(item.id,value):undefined}
        onDelete={onDelete?()=>onDelete(item.id):undefined}/>)}
    </div>
  </Group>;
}

/** Object actions use their owner's revisioned API or local undo history.
 * Renaming never needs to load or replace the object's geometry selection.
 */
export function WorkspaceFeatureTree<T extends FeatureItem>({
  layers,features,selectedId,onOpen,onRename,onDelete,busy=false,additionalGroups=[],pageSize=5,alwaysOpen=false,
}:{
  layers:readonly FeatureLayer[];features:readonly T[];
  selectedId:string|null;onOpen:(feature:T)=>void;
  onRename?:(feature:T,name:string)=>Promise<void>;onDelete?:(feature:T)=>Promise<void>;
  busy?:boolean;additionalGroups?:WorkspaceObjectGroup[];
  pageSize?:number;alwaysOpen?:boolean;
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
  const pages:string[][]=alwaysOpen?Array.from({length:Math.max(1,Math.ceil(rows.length/pageSize))},(_,i)=>rows.slice(i*pageSize,(i+1)*pageSize).map(r=>r.key)):[[]];
  if(!alwaysOpen)for(const group of [...groups,...extras]){
    for(let start=0;start<group.items.length;start+=pageSize){
      const chunk=group.items.slice(start,start+pageSize).map(item=>group.id+':'+item.id);
      // Keep a small layer together: freshly split siblings must be visible
      // side by side, rather than stranded on opposite page boundaries.
      if(pages[pages.length-1].length+chunk.length>pageSize)pages.push(chunk);
      else pages[pages.length-1].push(...chunk);
    }
  }
  const lastPage=pages.length-1,currentPage=Math.min(page,lastPage);
  const paged=new Set(pages[currentPage]);
  const selectedPage=pages.findIndex(items=>selectedKey!==null&&items.includes(selectedKey));
  const previousSelection=useRef<string|null|undefined>(undefined);
  useEffect(()=>{
    if(previousSelection.current!==selectedKey&&selectedPage>=0)setPage(selectedPage);
    previousSelection.current=selectedKey;
  },[selectedKey,selectedPage]);
  // Reserve the same number of slots on every page, even on the short last page.
  const objectCount=features.length+additionalGroups.reduce((sum,g)=>sum+g.items.length,0);
  const reservedRows=Math.min(pageSize,objectCount);
  return <div className={'workspace-feature-tree'+(alwaysOpen?' compact-object-tree':'')} role="region" aria-label="Project feature tree">
    <div className="workspace-tree-header"><strong>Features</strong><span>{features.length+additionalGroups.reduce((sum,g)=>sum+g.items.length,0)}</span></div>
    <label className="workspace-tree-filter"><ListFilter size={13}/>
      <input aria-label="Filter project features" type="search"
        value={filter} placeholder="Search objects"
        onChange={e=>{setFilter(e.target.value);setPage(0);}}/>
      {alwaysOpen&&<span className="workspace-object-count" aria-label="Object count" title={lowered?rows.length+' matching objects':objectCount+' objects'}>{lowered?rows.length+'/'+objectCount:objectCount}</span>}
    </label>
    {alwaysOpen?<div className="compact-object-list" style={{minHeight:reservedRows?reservedRows*28-2:0}}>
      {groups.flatMap(g=>g.items.filter(item=>paged.has(g.id+':'+item.id)).map(item=><ObjectRow key={g.id+':'+item.id} item={item} compact layerName={g.name} selected={selectedId===item.id} disabled={!g.visible} locked={g.locked} busy={busy} onOpen={()=>onOpen(item)} onRename={onRename?name=>onRename(item,name):undefined} onDelete={onDelete?()=>onDelete(item):undefined}/>))}
      {extras.flatMap(g=>g.items.filter(item=>paged.has(g.id+':'+item.id)).map(item=><ObjectRow key={g.id+':'+item.id} item={item} compact layerName={g.name} selected={g.selectedId===item.id} disabled={false} locked={false} busy={busy} onOpen={()=>g.onOpen(item.id)} onRename={g.onRename?name=>g.onRename!(item.id,name):undefined} onDelete={g.onDelete?()=>g.onDelete!(item.id):undefined}/>))}
      {!rows.length&&<small className="workspace-tree-empty" role="status">{lowered?'No matching objects':'No objects'}</small>}
    </div>:<>{groups.filter(g=>g.items.some(item=>paged.has(g.id+':'+item.id))).map(g=><FeatureGroup key={g.id} name={g.name} alwaysOpen={alwaysOpen}
      features={g.items.filter(item=>paged.has(g.id+':'+item.id))} total={g.items.length}
      visible={g.visible} search={Boolean(lowered)}
      selectedId={selectedId} locked={g.locked} busy={busy}
      onRename={onRename?async(id,name)=>{const f=lookup.get(id);if(f)await onRename(f,name);}:undefined}
      onDelete={onDelete?async id=>{const f=lookup.get(id);if(f)await onDelete(f);}:undefined}
      onOpen={id=>{const f=lookup.get(id);if(f)onOpen(f);}}/>)}
    {extras.filter(g=>g.items.some(item=>paged.has(g.id+':'+item.id))).map(g=><FeatureGroup key={g.id} name={g.name} alwaysOpen={alwaysOpen}
      features={g.items.filter(item=>paged.has(g.id+':'+item.id))} total={g.items.length} visible
      selectedId={g.selectedId} search={Boolean(lowered)} busy={busy}
      onOpen={g.onOpen} onRename={g.onRename} onDelete={g.onDelete}/>)}</>}
    {(pages.length>1||(alwaysOpen&&objectCount>pageSize))&&<div className="workspace-object-pager">
      <button type="button" aria-label="Previous objects" title="Previous page" disabled={currentPage===0} onClick={()=>setPage(currentPage-1)}><ChevronLeft size={14}/></button>
      <span aria-label="Object page">{currentPage+1} / {pages.length}</span>
      <button type="button" aria-label="Next objects" title="Next page" disabled={currentPage===lastPage} onClick={()=>setPage(currentPage+1)}><ChevronRight size={14}/></button>
    </div>}
    {!alwaysOpen&&!groups.length&&!extras.length&&<small className="workspace-tree-empty">
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
