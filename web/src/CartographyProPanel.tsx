import {SectionIcon} from './SectionIcon';
import {useEffect,useState} from 'react';
import {getProjectCRS,getProjectGrid,patchLayerStyle,saveGraduatedStyle,
  saveProjectCRS,transformProjectCoordinates,
  type GeoLayer,type GeoWorkspace,type ProjectCRS} from './api';

type BBox=[number,number,number,number];
interface Props {
  projectId:string|null;
  workspace:GeoWorkspace|null;
  viewport:BBox|null;
  selectedGeometry:GeoJSON.Geometry|null;
  onChanged:()=>void;
  onGrid:(grid:GeoJSON.FeatureCollection|null)=>void;
  labelMoveMode:boolean;
  onLabelMoveMode:(active:boolean)=>void;
}
const palette=['#f7fbff','#c6dbef','#9ecae1','#6baed6','#4292c6',
  '#2171b5','#08519c','#08306b','#041e42'];
export default function CartographyProPanel(p:Props){
  const [layerId,setLayerId]=useState('');
  const [field,setField]=useState('population');
  const [method,setMethod]=useState<'quantile'|'equal_interval'|'jenks'>('quantile');
  const [classes,setClasses]=useState(5);
  const [crs,setCRS]=useState<ProjectCRS|null>(null);
  const [epsg,setEPSG]=useState('EPSG:4326');
  const [projected,setProjected]=useState<string>('');
  const [classification,setClassification]=useState<string>('');
  const [busy,setBusy]=useState(false);
  const [localStyle,setLocalStyle]=useState<GeoLayer|null>(null);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const workspaceLayer=p.workspace?.layers.find(x=>x.id===layerId)??p.workspace?.layers[0]??null;
  const layer=localStyle&&workspaceLayer&&
    localStyle.id===workspaceLayer.id&&
    localStyle.style_revision>=workspaceLayer.style_revision?
    localStyle:workspaceLayer;

  useEffect(()=>{
    if(!p.projectId){setCRS(null);setLocalStyle(null);p.onGrid(null);return;}
    let cancelled=false;
    getProjectCRS(p.projectId).then(info=>{
      if(!cancelled){setCRS(info);setEPSG(info.epsg);}
    }).catch(()=>{if(!cancelled)setCRS(null);});
    return ()=>{cancelled=true;};
  },[p.projectId]);
  useEffect(()=>{
    if(!p.projectId||!p.viewport||!crs?.grid_visible){
      p.onGrid(null);return;
    }
    let cancelled=false;
    const timer=setTimeout(()=>{
      getProjectGrid(p.projectId!,p.viewport!).then(data=>{
        if(!cancelled)p.onGrid(data);
      }).catch(()=>{if(!cancelled)p.onGrid(null);});
    },300);
    return ()=>{cancelled=true;clearTimeout(timer);};
  },[p.projectId,p.viewport,crs?.epsg,crs?.grid_visible]);
  async function run(action:()=>Promise<void>){
    setError('');setNotice('');setBusy(true);
    try{await action();}
    catch(cause){setError(cause instanceof Error?cause.message:'Cartography action failed.');}
    finally{setBusy(false);}
  }
  async function saveLabels(change:Partial<GeoLayer['style']['labels']>){
    if(!layer||!p.projectId)return;
    await run(async()=>{
      const saved=await patchLayerStyle(p.projectId!,layer.id,{
        labels:change,expected_revision:layer.style_revision,
      });
      setLocalStyle(saved);
      p.onChanged();setNotice('Advanced label placement saved.');
    });
  }
  async function classify(){
    if(!layer||!p.projectId||!field.trim())return;
    await run(async()=>{
      const result=await saveGraduatedStyle(p.projectId!,{
        layer_id:layer.id,field:field.trim(),classes,method,
        colors:palette,expected_revision:layer.style_revision,
      });
      setClassification(result.classification.classes+' graduated classes using '+
        result.classification.samples+' values; breaks: '+
        result.classification.breaks.map(x=>x.toFixed(2)).join(', '));
      setLocalStyle(result.layer);
      p.onChanged();setNotice('Layer graduated colors updated.');
    });
  }
  async function storeCRS(nextVisible:boolean){
    if(!p.projectId||!crs)return;
    await run(async()=>{
      const current=await saveProjectCRS(p.projectId!,epsg,nextVisible,crs.revision);
      setCRS(current);setEPSG(current.epsg);
      if(!nextVisible)p.onGrid(null);
      setNotice('Project EPSG and coordinate grid settings saved.');
    });
  }
  async function projectCoords(){
    if(!p.projectId||!crs)return;
    await run(async()=>{
      let point:[number,number]|null=null;
      const geometry=p.selectedGeometry;
      if(geometry?.type==='Point')point=[geometry.coordinates[0],geometry.coordinates[1]];
      else if(p.viewport)point=[(p.viewport[0]+p.viewport[2])/2,
        (p.viewport[1]+p.viewport[3])/2];
      if(!point)throw new Error('Select a point or open the map to transform coordinates.');
      const transformed=await transformProjectCoordinates(p.projectId!,[point],crs.epsg);
      const values=transformed.coordinates[0];
      setProjected(values.map(v=>v.toFixed(3)).join(', ')+' '+transformed.units);
      setNotice('Coordinate conversion completed using PyProj.');
    });
  }

  return <div className="professional-panel">
    <details>
      <summary><SectionIcon role="choropleth" size={14}/> Graduated numeric choropleth</summary>
      <div className="professional-form">
        <label>Map layer
          <select aria-label="Graduated map layer" value={layer?.id||''}
            onChange={event=>setLayerId(event.target.value)}>
            {(p.workspace?.layers??[]).map(item=><option key={item.id}
              value={item.id}>{item.name}</option>)}
          </select>
        </label>
        <label>Numeric attribute field
          <input aria-label="Graduated numeric field" maxLength={64} value={field}
            onChange={event=>setField(event.target.value)}/>
        </label>
        <div className="area-fields">
          <label>Classification
            <select aria-label="Graduated method" value={method}
              onChange={event=>setMethod(event.target.value as typeof method)}>
              <option value="quantile">Quantile (equal count)</option>
              <option value="equal_interval">Equal intervals</option>
              <option value="jenks">Fisher-Jenks natural breaks</option>
            </select>
          </label>
          <label>Classes
            <select aria-label="Graduated class count" value={classes}
              onChange={event=>setClasses(Number(event.target.value))}>
              {Array.from({length:8},(_,i)=>i+2).map(n=>
                <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
        </div>
        <div className="graduated-preview">{palette.slice(0,classes).map((color,index)=>
          <span key={index} style={{background:color}}/>)}</div>
        <button onClick={()=>void classify()} disabled={busy||!layer||!p.projectId}>
          Calculate & save color classes
        </button>
        {classification&&<p className="project-hint">{classification}</p>}
        <p className="project-hint">Uses all numeric values from the target project
          layer (up to 10,000). Server computes real class thresholds and
          persists the legend with revision checks.</p>
      </div>
    </details>
    <details>
      <summary><SectionIcon role="labelPlacement" size={14}/> Advanced label placement & callouts</summary>
      <div className="professional-form">
        <label>Map layer
          <select aria-label="Advanced label layer" value={layer?.id||''}
            onChange={event=>setLayerId(event.target.value)}>
            {(p.workspace?.layers??[]).map(item=>
              <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </label>
        {layer&&<>
          <label>Placement
            <select aria-label="Label placement" value={layer.style.labels.placement}
              disabled={busy} onChange={event=>void saveLabels({
                placement:event.target.value as GeoLayer['style']['labels']['placement']})}>
              <option value="auto">Automatic</option>
              <option value="point">At feature anchor</option>
              <option value="line">Along line</option>
            </select>
          </label>
          <div className="area-fields">
            <label>Priority (0–100)
              <input aria-label="Label priority" type="number" min={0} max={100}
                key={layer.style_revision+'priority'}
                defaultValue={layer.style.labels.priority} disabled={busy}
                onBlur={event=>{const v=Number(event.target.value);
                  if(v!==layer.style.labels.priority)void saveLabels({priority:v});}}/>
            </label>
            <label>Horizontal offset (em)
              <input aria-label="Label horizontal offset" type="number" min={-10} max={10}
                step=".5" disabled={busy} key={layer.style_revision+'offsetX'}
                defaultValue={layer.style.labels.offset_x}
                onBlur={event=>{const v=Number(event.target.value);
                  if(v!==layer.style.labels.offset_x)void saveLabels({offset_x:v});}}/>
            </label>
            <label>Vertical offset (em)
              <input aria-label="Label vertical offset" type="number" min={-10} max={10}
                step=".5" disabled={busy} key={layer.style_revision+'offsetY'}
                defaultValue={layer.style.labels.offset_y}
                onBlur={event=>{const v=Number(event.target.value);
                  if(v!==layer.style.labels.offset_y)void saveLabels({offset_y:v});}}/>
            </label>
          </div>
          <div className="professional-form">
            <strong>Conditional labeling rule</strong>
            <label>Label only when attribute matches
              <input aria-label="Label rule field" maxLength={64}
                key={layer.style_revision+'rulefield'}
                defaultValue={layer.style.labels.rule_field}
                placeholder="Blank = show every feature"
                onBlur={event=>{
                  if(event.currentTarget.value!==layer.style.labels.rule_field)
                    void saveLabels({rule_field:event.currentTarget.value});
                }}/>
            </label>
            <div className="area-fields">
              <label>Comparison
                <select aria-label="Label rule operator" disabled={busy}
                  value={layer.style.labels.rule_operator}
                  onChange={event=>void saveLabels({
                    rule_operator:event.target.value as GeoLayer['style']['labels']['rule_operator'],
                  })}>
                  <option value="equals">Equals</option>
                  <option value="contains">Contains</option>
                  <option value="gte">Numeric ≥</option>
                  <option value="lte">Numeric ≤</option>
                  <option value="exists">Has a value</option>
                </select>
              </label>
              <label>Compared value
                <input aria-label="Label rule value" maxLength={120}
                  key={layer.style_revision+'rulevalue'}
                  defaultValue={layer.style.labels.rule_value}
                  disabled={busy||layer.style.labels.rule_operator==='exists'}
                  onBlur={event=>{
                    if(event.currentTarget.value!==layer.style.labels.rule_value)
                      void saveLabels({rule_value:event.currentTarget.value});
                  }}/>
              </label>
            </div>
            <button aria-label="Move map labels" disabled={busy||!p.projectId}
              className={p.labelMoveMode?'active':''}
              onClick={()=>p.onLabelMoveMode(!p.labelMoveMode)}>
              {p.labelMoveMode?'Stop moving labels':'Move labels by dragging on map'}
            </button>
            <p className="project-hint">Drag a saved label and release to store a
              feature-specific X/Y offset in its revision history.
              Field rules use plain comparisons, never code expressions.</p>
          </div>
          <label>Label prefix
            <input aria-label="Label prefix" maxLength={24}
              key={layer.style_revision+'prefix'}
              defaultValue={layer.style.labels.prefix}
              onBlur={event=>{
                if(event.currentTarget.value!==layer.style.labels.prefix)
                  void saveLabels({prefix:event.currentTarget.value});
              }}/>
          </label>
          <label>Label suffix
            <input aria-label="Label suffix" maxLength={24}
              key={layer.style_revision+'suffix'}
              defaultValue={layer.style.labels.suffix}
              onBlur={event=>{
                if(event.currentTarget.value!==layer.style.labels.suffix)
                  void saveLabels({suffix:event.currentTarget.value});
              }}/>
          </label>
          <label className="linked-vertex-toggle">
            <input aria-label="Label callout lines" type="checkbox" disabled={busy}
              checked={layer.style.labels.callout}
              onChange={event=>void saveLabels({callout:event.target.checked})}/>
            Draw connector lines to displaced point annotations
          </label>
        </>}
      </div>
    </details>
    <details>
      <summary><SectionIcon role="projection" size={14}/> Project EPSG coordinates & grid</summary>
      <div className="professional-form">
        <label>Project CRS (EPSG)
          <input aria-label="Project EPSG code" value={epsg}
            onChange={event=>setEPSG(event.target.value)}
            placeholder="EPSG:4326"/>
        </label>
        <label className="linked-vertex-toggle">
          <input type="checkbox" aria-label="Show project CRS grid"
            checked={Boolean(crs?.grid_visible)} disabled={busy||!crs}
            onChange={event=>void storeCRS(event.target.checked)}/>
          Overlay a projected coordinate grid
        </label>
        <button disabled={busy||!p.projectId||!crs}
          onClick={()=>void storeCRS(Boolean(crs?.grid_visible))}>Save project CRS</button>
        <button disabled={busy||!p.projectId||!crs}
          onClick={()=>void projectCoords()}>Transform map/point coordinates</button>
        {projected&&<p aria-label="Projected coordinates" className="project-info">
          {projected}</p>}
        <p className="project-hint">All saved geometry remains WGS84 GeoJSON.
          The project CRS controls grid and coordinate transformations;
          the MapLibre raster basemap remains Web Mercator.</p>
      </div>
    </details>
    {notice&&<p className="project-info">{notice}</p>}
    {error&&<p className="discovery-error">{error}</p>}
  </div>;
}
