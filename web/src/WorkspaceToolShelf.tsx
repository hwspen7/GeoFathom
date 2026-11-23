/** Reusable operation picker with searchable commands; algorithm parameters
 * remain in their owning workbench, keeping one source of state.
 */
import {useState} from 'react';
import {Search} from 'lucide-react';
export interface WorkbenchTool<T extends string> {id:T;title:string}
export default function WorkspaceToolShelf<T extends string>({
  category,categories,tools,selected,onCategory,onSelect,
}:{
  category:string;categories:Record<string,T[]>;tools:WorkbenchTool<T>[];
  selected:T|null;onCategory:(group:string)=>void;onSelect:(tool:T|null)=>void;
}){
  const [query,setQuery]=useState('');
  const term=query.trim().toLocaleLowerCase();
  const matches=tools.filter(t=>
    (term?([t.title,t.id,...Object.keys(categories).filter(c=>categories[c].includes(t.id))]
      .join(' ').toLocaleLowerCase().includes(term)):categories[category]?.includes(t.id)));
  return <div className="workspace-tool-shelf">
    <div className="workspace-tool-controls">
      <label className="terrain-category">Tool group
        <select aria-label="Terrain tool group" value={category}
          onChange={e=>{setQuery('');onCategory(e.target.value);}}>
          {Object.keys(categories).map(name=><option key={name}>{name}</option>)}
        </select>
      </label>
      <label className="workspace-tool-search"><Search size={13}/>
        <input aria-label="Find terrain tool" type="search" value={query}
          placeholder="Find tool"
          onChange={event=>setQuery(event.target.value)}/>
      </label>
    </div>
    <div className="terrain-command-grid" aria-label="Terrain tools">
      {matches.map(tool=><button key={tool.id} type="button"
        aria-pressed={selected===tool.id}
        title={tool.id.replaceAll('_',' ')}
        onClick={()=>onSelect(selected===tool.id?null:tool.id)}>{tool.title}</button>)}
    </div>
    {!matches.length&&<small className="workspace-tree-empty">No matching terrain tools</small>}
    <select aria-label="Advanced terrain operation" className="visually-hidden"
      tabIndex={-1} value={selected??''}
      onChange={e=>{const tool=e.target.value as T;
        if(tool&&!categories[category].includes(tool)){
          onCategory(Object.keys(categories).find(c=>categories[c].includes(tool))??category);
        }
        onSelect(tool||null);
      }}>
      <option value="">Select operation</option>
      {tools.map(tool=><option key={tool.id} value={tool.id}>{tool.title}</option>)}
    </select>
  </div>;
}
