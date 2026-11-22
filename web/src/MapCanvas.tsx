import { useEffect, useRef, useState } from 'react';
import maplibregl, { type GeoJSONSource, type MapMouseEvent, type StyleSpecification } from 'maplibre-gl';

import { rasterPreviewUrl, protectedRasterPreview } from './api';
import { PixelSnapIndex } from './spatialIndex';
import {BASEMAPS,type BasemapId,type CustomBasemap} from './basemaps';
import {OFFLINE_METHOD} from './scratch';
import type {RasterLayerView} from './rasterLayers';
import {areaText,distanceText,mapPalette,type DisplaySettings} from './displaySettings';
import {drawingPreview,measurementAnchor,approximateMeasurement,geodesicDrag as edgeDistance} from './editing';
import { featureLabel } from './labels';
import type { ExternalTile } from './DataServicesPanel';
import type { Measurement,LayerStyle,TerrainRasterLayer } from './api';
import {
  addVertex, moveVertex, removeVertex, translateSpherical, geodesicDrag, pathsOf,
  verticesOf,moveEdge, type GeometryPath, type Position, type ShapeMode,
} from './editing';

export interface FocusPoint {
  longitude: number;
  latitude: number;
  bbox: [number, number, number, number] | null;
  key: number;
}

export interface MapLayerFeature {
  id: string;
  name: string;
  properties: Record<string,unknown>;
  source: string;
  measurement: Measurement;
  style: LayerStyle;
  geometry: GeoJSON.Geometry;
  layer_id: string;
  color: string;
  visible: boolean;
  locked: boolean;
}

interface Props {
  selected: GeoJSON.Geometry | null;
  drawingMode: ShapeMode;
  vertices: Position[];
  focus: FocusPoint | null;
  basemap: BasemapId;
  customBasemap:CustomBasemap|null;
  onBasemapStatus:(status:string)=>void;
  measurement:Measurement|null;
  showMeasurements:boolean;
  display:DisplaySettings;
  selectedFeatureId:string|null;
  rasterLayers:RasterLayerView[];
  onRasterError:(message:string)=>void;
  onMapClick: (position: Position) => void;
  onFinishDrawing:()=>void;
  terrainPicking:boolean;
  terrainMarker:Position|null;
  terrainResults:GeoJSON.Feature[];
  terrainRasters?:TerrainRasterLayer[];
  terrainFetchTarget?:[number,number,number,number]|null;
  onTerrainPick:(point:Position)=>void;
  onContextMenu:(x:number,y:number)=>void;
  onEditingError:(message:string)=>void;
  onViewportChange: (bbox: [number, number, number, number]) => void;
  discovered: GeoJSON.Geometry[];
  traceMode: boolean;
  onTraceClick: (position: Position) => void;
  editing: boolean;
  moving: boolean;
  edgeMoving:boolean;
  snapping: boolean;
  selectedLocked: boolean;
  layerFeatures: MapLayerFeature[];
  promptPositive:Position[];
  promptNegative:Position[];
  promptBox:Position[];
  annotationMode:boolean;
  onAnnotationClick:(position:Position)=>void;
  selectionBoxMode:boolean;
  onSelectionBox:(bbox:[number,number,number,number])=>void;
  labelMoveMode:boolean;
  onLabelMove:(id:string,dx:number,dy:number)=>void;
  selectedIds:string[];
  qualityIssues:GeoJSON.Geometry[];
  projectGrid:GeoJSON.FeatureCollection|null;
  externalTiles:ExternalTile[];
  onGeometryPreview: (geometry: GeoJSON.Geometry) => void;
  onGeometryCommit: (geometry: GeoJSON.Geometry, movement?: {
    original:GeoJSON.Geometry;bearing_deg:number;distance_m:number;
  }) => void;
  onSelectSavedFeature: (id: string) => void;
  onDeselect:()=>void;
}

function mapStyle():StyleSpecification{
  const style:StyleSpecification={version:8,glyphs:import.meta.env.VITE_GLYPHS_URL||
    'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',sources:{},
    layers:[{id:'blank',type:'background',paint:{'background-color':'#e4e7ea'}}]};
  for(const layer of BASEMAPS){
    if(!layer.url)continue;
    style.sources[layer.id]={type:'raster',tiles:[layer.url],tileSize:256,
      attribution:layer.attribution,maxzoom:layer.maxzoom};
    style.layers.push({id:layer.id,type:'raster',source:layer.id,
      layout:{visibility:layer.id==='street'?'visible':'none'},paint:{'raster-fade-duration':0}});
  }
  return style;
}

function featureCollection(
  selected: GeoJSON.Geometry | null,
  vertices: Position[],
  drawingMode: ShapeMode,
  discovered: GeoJSON.Geometry[],
  layerFeatures: MapLayerFeature[],
  editing: boolean,
  promptPositive:Position[],promptNegative:Position[],promptBox:Position[],
  selectedIds:string[],qualityIssues:GeoJSON.Geometry[],
  zoom:number,
  offsetPoint?:(point:Position,dx:number,dy:number)=>Position,
  cursor:Position|null=null,
  selectedFeatureId:string|null=null,
): GeoJSON.FeatureCollection {
  const features: GeoJSON.Feature[] = [];
  for (const saved of layerFeatures) {
    if (!saved.visible || (selected&&saved.id===selectedFeatureId&&saved.id.startsWith('scratch-')) || (selected&&editing&&saved.id===selectedFeatureId)) continue;
    features.push({
      type: 'Feature', geometry: selected&&saved.id===selectedFeatureId?selected:saved.geometry,
      properties: {
        role:'saved',id:saved.id,color:selectedIds.includes(saved.id)?'#f59e0b':saved.color,
        spatialSelected:selectedIds.includes(saved.id),
        locked:saved.locked,layer_id:saved.layer_id,
        name:saved.name,
        label:featureLabel(saved,zoom),
        labelSize:saved.style.labels.font_size,
        labelColor:saved.style.labels.text_color,
        labelHaloColor:saved.style.labels.halo_color,
        labelHaloWidth:saved.style.labels.halo_width,
        labelOverlap:saved.style.labels.allow_overlap,
        labelSortKey:-saved.style.labels.priority,
        labelPlacement:saved.style.labels.placement,
        labelOffset:[
          typeof saved.properties.label_offset_x==='number'?
            saved.properties.label_offset_x:saved.style.labels.offset_x,
          typeof saved.properties.label_offset_y==='number'?
            saved.properties.label_offset_y:saved.style.labels.offset_y,
        ],
        fillOpacity:saved.style.symbol.fill_opacity,
        lineWidth:saved.style.symbol.line_width,
        pointRadius:saved.style.symbol.point_radius,
        strokeColor:saved.style.symbol.stroke_color,
      },
    });
  }
  for(const saved of layerFeatures){
    if(!saved.visible||saved.geometry.type!=='Point'||!saved.style.labels.callout||
       !offsetPoint)continue;
    const font=saved.style.labels.font_size;
    const dx=(typeof saved.properties.label_offset_x==='number'?
      saved.properties.label_offset_x:saved.style.labels.offset_x)*font;
    const dy=(typeof saved.properties.label_offset_y==='number'?
      saved.properties.label_offset_y:saved.style.labels.offset_y)*font;
    if(Math.hypot(dx,dy)<font*.5)continue;
    const origin=saved.geometry.coordinates as Position;
    const end=offsetPoint(origin,dx,dy);
    features.push({type:'Feature',properties:{
      role:'label-callout',color:saved.style.labels.text_color,lineWidth:1.2,
    },geometry:{type:'LineString',coordinates:[origin,end]}});
  }
  for(const geometry of qualityIssues){
    features.push({type:'Feature',properties:{
      role:'qa-issue',color:'#d22b41',fillOpacity:.08,lineWidth:4,
    },geometry});
  }
  for (const geometry of discovered) {
    features.push({
      type: 'Feature', properties: { role: 'candidate', color: '#9d8b4a' }, geometry,
    });
  }
  if (selected) {
    features.push({
      type: 'Feature', properties: { role: 'selected', color: '#168047',fillOpacity:.28,lineWidth:2.5 },
      geometry: selected,
    });
  }

  const draft=drawingPreview(drawingMode,vertices,cursor);
  if(draft)features.push({type:'Feature',properties:{role:'drawing',color:'#168047',fillOpacity:.22,lineWidth:2},geometry:draft});
  for (const position of vertices) {
    features.push({
      type: 'Feature', properties: { role: 'draw-vertex' },
      geometry: { type: 'Point', coordinates: position },
    });
  }

  for(const [role,points] of [['prompt-positive',promptPositive],['prompt-negative',promptNegative]] as const){
    for(const point of points){
      features.push({type:'Feature',
        properties:{role},geometry:{type:'Point',coordinates:point}});
    }
  }
  for(const point of promptBox){
    features.push({type:'Feature',
      properties:{role:'prompt-box-corner'},geometry:{type:'Point',coordinates:point}});
  }
  if(promptBox.length===2){
    const [a,b]=promptBox;
    const west=Math.min(a[0],b[0]),east=Math.max(a[0],b[0]);
    const south=Math.min(a[1],b[1]),north=Math.max(a[1],b[1]);
    features.push({type:'Feature',properties:{role:'prompt-box',color:'#ef9238'},
      geometry:{type:'Polygon',coordinates:[[[west,south],[east,south],
        [east,north],[west,north],[west,south]]]}});
  }
  if (editing && selected) {
    for (const node of verticesOf(selected)) {
      features.push({
        type: 'Feature',
        properties: {
          role: node.midpoint ? 'edit-midpoint' : 'edit-vertex',
          polygon: node.path.polygon,
          ring: node.path.ring,
          vertex: node.path.vertex,
        },
        geometry: { type: 'Point', coordinates: node.point },
      });
    }
  }
  return { type: 'FeatureCollection', features };
}

type Drag = {
  start: Position;
  end: Position;
  original: GeoJSON.Geometry;
  last: GeoJSON.Geometry;
  path: GeometryPath | null;
  kind: 'vertex' | 'feature' | 'edge';
};

export default function MapCanvas({
  selected,drawingMode,vertices,focus,basemap,customBasemap,onBasemapStatus,measurement,showMeasurements,display,selectedFeatureId,rasterLayers,onRasterError,onMapClick,onFinishDrawing,
  terrainPicking,terrainMarker,terrainResults,terrainRasters,terrainFetchTarget,onTerrainPick,onContextMenu,onEditingError,
  onViewportChange, discovered, traceMode, onTraceClick,
  editing, moving,edgeMoving, snapping, selectedLocked, layerFeatures,
  promptPositive,promptNegative,promptBox,annotationMode,onAnnotationClick,
  selectionBoxMode,onSelectionBox,selectedIds,qualityIssues,projectGrid,externalTiles,
  labelMoveMode,onLabelMove,
  onGeometryPreview, onGeometryCommit, onSelectSavedFeature,onDeselect,
}: Props) {
  const container = useRef<HTMLDivElement>(null);
  const coordinateRef = useRef<HTMLDivElement>(null);
  const dimensionRef=useRef<HTMLDivElement>(null);
  const [cursor,setCursor]=useState<Position|null>(null);
  const cursorTick=useRef(0);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const eventRef = useRef({
    selected,selectedFeatureId,drawingMode, traceMode, annotationMode,selectionBoxMode,labelMoveMode,editing, moving,edgeMoving, snapping, selectedLocked,
    layerFeatures, onMapClick,onFinishDrawing,terrainPicking,onTerrainPick,onContextMenu,onEditingError, onTraceClick,onAnnotationClick,onSelectionBox,onLabelMove,onViewportChange,
    onGeometryPreview, onGeometryCommit, onSelectSavedFeature,onDeselect,
  });
  const renderRef = useRef({
    selected,vertices,drawingMode,discovered,layerFeatures,editing,
    promptPositive,promptNegative,promptBox,selectedIds,qualityIssues,cursor,selectedFeatureId,
  });
  renderRef.current={
    selected,vertices,drawingMode,discovered,layerFeatures,editing,
    promptPositive,promptNegative,promptBox,selectedIds,qualityIssues,cursor,selectedFeatureId,
  };
  const drag = useRef<Drag | null>(null);
  const selectionDrag=useRef<{start:Position;end:Position}|null>(null);
  const labelPointer=useRef<[number,number]|null>(null);
  const labelDrag=useRef<{id:string;text:string;start:[number,number];
    base:[number,number];font:number}|null>(null);
  const spatialSnap = useRef<PixelSnapIndex|null>(null);
  const [ready, setReady] = useState(false);
  eventRef.current = {
    selected,selectedFeatureId,drawingMode, traceMode, annotationMode,selectionBoxMode,labelMoveMode,editing, moving,edgeMoving, snapping, selectedLocked,
    layerFeatures, onMapClick,onFinishDrawing,terrainPicking,onTerrainPick,onContextMenu,onEditingError, onTraceClick,onAnnotationClick,onSelectionBox,onLabelMove,onViewportChange,
    onGeometryPreview, onGeometryCommit, onSelectSavedFeature,onDeselect,
  };

  useEffect(() => {
    if (!container.current) return;
    const map = new maplibregl.Map({
      container: container.current, style: mapStyle(), center: [0, 22],
      zoom: 2.1, attributionControl: false,
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: true }), 'bottom-right');
    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-left');
    map.addControl(new maplibregl.ScaleControl({ maxWidth:140,unit:'metric' }), 'bottom-left');
    const refreshZoomLabels=()=>{
      const view=renderRef.current;
      const source=map.getSource('workspace') as GeoJSONSource | undefined;
      if(!source)return;
      source.setData(featureCollection(
        view.selected,view.vertices,view.drawingMode,view.discovered,view.layerFeatures,
        view.editing,view.promptPositive,view.promptNegative,view.promptBox,
        view.selectedIds,view.qualityIssues,map.getZoom(),
        (point,dx,dy)=>{
          const p=map.project(point as maplibregl.LngLatLike);
          const shifted=map.unproject([p.x+dx,p.y+dy]);
          return [shifted.lng,shifted.lat];
        },view.cursor,view.selectedFeatureId,
      ));
    };
    map.on('zoomend',refreshZoomLabels);

    function bounds() {
      spatialSnap.current=null;
      const extent = map.getBounds();
      eventRef.current.onViewportChange([
        extent.getWest(), extent.getSouth(), extent.getEast(), extent.getNorth(),
      ]);
    }
    let lastCoordinateUpdate=0;
    function displayCoordinates(event:MapMouseEvent){
      const now=Date.now();
      if(now-lastCoordinateUpdate<80)return;
      lastCoordinateUpdate=now;
      if(coordinateRef.current){
        coordinateRef.current.textContent='Lon '+event.lngLat.lng.toFixed(6)+
          '° · Lat '+event.lngLat.lat.toFixed(6)+'°';
      }
    }
    function coordinates(event: MapMouseEvent): Position {
      return [event.lngLat.lng, event.lngLat.lat];
    }
    function hits(event: MapMouseEvent) {
      if (!map.getLayer('workspace-points')) return [];
      return map.queryRenderedFeatures(event.point, {
        layers: ['workspace-labels','workspace-points','workspace-lines','workspace-fill'],
      });
    }
    function nodePath(props: GeoJSON.GeoJsonProperties): GeometryPath {
      return {
        polygon: Number(props?.polygon || 0),
        ring: Number(props?.ring || 0),
        vertex: Number(props?.vertex || 0),
      };
    }
    function beginDrag(event: MapMouseEvent) {
      spatialSnap.current=null;
      if(eventRef.current.terrainPicking||event.originalEvent.button!==0)return;
      if(eventRef.current.labelMoveMode){
        const state=eventRef.current;
        const found=hits(event).find(item=>
          item.properties?.role==='saved'&&
          state.layerFeatures.some(feature=>feature.id===String(item.properties?.id)));
        let target=found?.properties?.id?state.layerFeatures.find(
          item=>item.id===String(found.properties.id)):undefined;
        // A point annotation must remain draggable even when the remote
        // glyph font has not loaded and MapLibre cannot hit its symbol.
        if(!target){
          let nearest=18;
          for(const item of state.layerFeatures){
            if(!item.visible||item.locked||item.geometry.type!=='Point')continue;
            if(!item.style.labels.enabled&&item.properties.annotation!==true)continue;
            const projected=map.project(item.geometry.coordinates as maplibregl.LngLatLike);
            const distance=Math.hypot(event.point.x-projected.x,
              event.point.y-projected.y);
            if(distance<nearest){nearest=distance;target=item;}
          }
        }
        if(target&&!target.locked){
          const base:[number,number]=[
            typeof target.properties.label_offset_x==='number'?
              target.properties.label_offset_x:target.style.labels.offset_x,
            typeof target.properties.label_offset_y==='number'?
              target.properties.label_offset_y:target.style.labels.offset_y,
          ];
          labelPointer.current=[event.point.x,event.point.y];
          labelDrag.current={
            id:target.id,text:target.name,start:[event.point.x,event.point.y],
            base,font:target.style.labels.font_size,
          };
          map.dragPan.disable();event.preventDefault();
          map.getCanvas().style.cursor='grabbing';
          return;
        }
      }
      if(eventRef.current.selectionBoxMode){
        selectionDrag.current={start:coordinates(event),end:coordinates(event)};
        map.dragPan.disable();event.preventDefault();
        return;
      }
      const state = eventRef.current;
      if (!state.editing || state.selectedLocked || !state.selected) return;
      const features = hits(event);
      const handle = features.find(f => f.properties?.role === 'edit-vertex'
                                   || f.properties?.role === 'edit-midpoint');
      // MapLibre's asynchronous GeoJSON hit test can briefly miss a visible
      // handle. Prefer the rendered feature, but fall back to a small
      // screen-pixel radius around the actual projected geometric vertex.
      let fallback:ReturnType<typeof verticesOf>[number]|null=null;
      if(!handle){
        let best=9;
        for(const node of verticesOf(state.selected)){
          const p=map.project(node.point as maplibregl.LngLatLike);
          const distance=Math.hypot(event.point.x-p.x,event.point.y-p.y);
          if(distance<best){
            best=distance;fallback=node;
          }
        }
      }
      if(import.meta.env.DEV&&container.current){
        container.current.setAttribute('data-dev-hit-role',
          String(handle?.properties?.role??(fallback?'fallback-'+
            (fallback.midpoint?'edit-midpoint':'edit-vertex'):
            features.map(f=>f.properties?.role).join(','))));
        container.current.setAttribute('data-dev-pointer-pixel',
          JSON.stringify([event.point.x,event.point.y]));
      }
      let first = state.selected;
      let path: GeometryPath | null = null;
      let kind: Drag['kind'] | null = null;
      if(state.moving&&(handle||fallback||features.some(f=>f.properties?.role==='selected'))){
        kind='feature';
      }else if (handle || fallback) {
        path = handle ? nodePath(handle.properties) : fallback!.path;
        const midpoint=handle?.properties?.role==='edit-midpoint'||fallback?.midpoint;
        if(state.edgeMoving){
          if(!midpoint)return;
          kind='edge';
        }else{
          if(midpoint){
            first=addVertex(first,path,coordinates(event));
            path={...path,vertex:path.vertex+1};
            state.onGeometryPreview(first);
          }
          kind='vertex';
        }
      } else if (
        state.moving && features.some(f => f.properties?.role === 'selected')
      ) {
        kind = 'feature';
      }
      if (!kind) return;
      if(import.meta.env.DEV&&container.current)
        container.current.setAttribute('data-dev-drag-began',kind);
      drag.current = { original: first, last: first, path, kind,
        start: coordinates(event),end:coordinates(event) };
      map.dragPan.disable();
      map.getCanvas().style.cursor = 'grabbing';
      event.preventDefault();
    }
    function snapAt(point:Position,movingPath:GeometryPath|null):Position {
      const state=eventRef.current;
      if(!state.snapping)return point;
      if(!spatialSnap.current) {
        const paths:Position[][]=[];
        for(const feature of state.layerFeatures) {
          if(!feature.visible)continue;
          // Do not snap a selected saved polygon onto the geometry that is
          // currently being dragged; keep neighboring polygons available.
          if(feature.id===state.selectedFeatureId||(state.selected && JSON.stringify(feature.geometry)===JSON.stringify(state.selected)))
            continue;
          paths.push(...pathsOf(feature.geometry));
        }
        if(!movingPath && state.selected)paths.push(...pathsOf(state.selected));
        spatialSnap.current=new PixelSnapIndex(paths,position=>{
          const p=map.project(position as maplibregl.LngLatLike);
          return [p.x,p.y];
        });
      }
      const pixel=map.project(point as maplibregl.LngLatLike);
      const old=movingPath&&state.selected?
        verticesOf(state.selected).find(item=>!item.midpoint&&
          item.path.polygon===movingPath.polygon&&
          item.path.ring===movingPath.ring&&
          item.path.vertex===movingPath.vertex)?.point :undefined;
      const hit=spatialSnap.current.snap([pixel.x,pixel.y],12,old);
      return hit.kind==='none'?point:hit.point;
    }
    function dragging(event: MapMouseEvent) {
      if(labelDrag.current){
        const drag=labelDrag.current;
        labelPointer.current=[event.point.x,event.point.y];
        const source=map.getSource('label-drag-preview') as GeoJSONSource|undefined;
        if(source){
          const geo=map.unproject([event.point.x,event.point.y]);
          source.setData({type:'FeatureCollection',features:[{
            type:'Feature',properties:{label:drag.text},
            geometry:{type:'Point',coordinates:[geo.lng,geo.lat]},
          }]});
        }
        return;
      }
      if(selectionDrag.current){
        selectionDrag.current.end=coordinates(event);
        const a=selectionDrag.current.start,b=selectionDrag.current.end;
        const west=Math.min(a[0],b[0]),east=Math.max(a[0],b[0]);
        const south=Math.min(a[1],b[1]),north=Math.max(a[1],b[1]);
        const source=map.getSource('selection-preview') as GeoJSONSource|undefined;
        if(source&&west<east&&south<north)
          source.setData({type:'FeatureCollection',features:[{
            type:'Feature',properties:{},geometry:{
              type:'Polygon',coordinates:[[[west,south],[east,south],
                [east,north],[west,north],[west,south]]],
            },
          }]});
        return;
      }
      const current = drag.current;
      if (!current) {
        if(eventRef.current.drawingMode&&Date.now()-cursorTick.current>=33){cursorTick.current=Date.now();setCursor(snapAt(coordinates(event),null));}
        return;
      }
      const coordinate = coordinates(event);
      current.end=coordinate;
      let changed: GeoJSON.Geometry;
      if (current.kind === 'feature') {
        const delta=geodesicDrag(current.start,coordinate);
        changed=translateSpherical(current.original,delta.bearing_deg,delta.distance_m);
      } else if(current.kind==='edge'){
        const delta=geodesicDrag(current.start,coordinate);
        changed=moveEdge(current.original,current.path!,delta.bearing_deg,delta.distance_m);
      }else{
        changed = moveVertex(current.original, current.path!, snapAt(coordinate, current.path));
      }
      current.last = changed;
      if(import.meta.env.DEV&&container.current)
        container.current.setAttribute('data-dev-drag-updated','true');
      eventRef.current.onGeometryPreview(changed);
    }
    function finishDrag() {
      if(labelDrag.current){
        const drag=labelDrag.current;
        labelDrag.current=null;map.dragPan.enable();
        map.getCanvas().style.cursor='crosshair';
        const source=map.getSource('label-drag-preview') as GeoJSONSource|undefined;
        source?.setData({type:'FeatureCollection',features:[]});
        // A drag is still a user-initiated feature revision, never a
        // direct unversioned browser-only style mutation.
        const current=labelPointer.current??drag.start;
        labelPointer.current=null;
        const offsetX=Math.max(-10,Math.min(10,
          drag.base[0]+(current[0]-drag.start[0])/drag.font));
        const offsetY=Math.max(-10,Math.min(10,
          drag.base[1]+(current[1]-drag.start[1])/drag.font));
        if(Math.hypot(offsetX-drag.base[0],offsetY-drag.base[1])>.05){
          eventRef.current.onLabelMove(drag.id,offsetX,offsetY);
        }
        return;
      }
      if(selectionDrag.current){
        const {start,end}=selectionDrag.current;
        selectionDrag.current=null;map.dragPan.enable();
        const source=map.getSource('selection-preview') as GeoJSONSource|undefined;
        if(source)source.setData({type:'FeatureCollection',features:[]});
        const west=Math.min(start[0],end[0]),east=Math.max(start[0],end[0]);
        const south=Math.min(start[1],end[1]),north=Math.max(start[1],end[1]);
        if(east-west>1e-8&&north-south>1e-8)
          eventRef.current.onSelectionBox([west,south,east,north]);
        return;
      }
      const current = drag.current;
      if (!current) return;
      drag.current = null;
      map.dragPan.enable();
      map.getCanvas().style.cursor = 'crosshair';
      if(import.meta.env.DEV&&container.current)
        container.current.setAttribute('data-dev-drag-ended',current.kind);
      if(current.kind==='feature'){
        const delta=geodesicDrag(current.start,current.end);
        if(delta.distance_m>0.001){
          eventRef.current.onGeometryCommit(current.last,{
            original:current.original,...delta,
          });
        }
      }else{
        eventRef.current.onGeometryCommit(current.last);
      }
    }
    function click(event: MapMouseEvent) {
      const state = eventRef.current;
      if (drag.current) return;
      if(state.terrainPicking){state.onTerrainPick(coordinates(event));return;}
      if (state.selectionBoxMode||state.labelMoveMode) return;
      if (state.annotationMode) state.onAnnotationClick(coordinates(event));
      else if (state.traceMode) state.onTraceClick(coordinates(event));
      else if (state.drawingMode) state.onMapClick(snapAt(coordinates(event), null));
      else if (!state.editing) {
        const feature = hits(event).find(f => f.properties?.role === 'saved');
        if (feature?.properties?.id) state.onSelectSavedFeature(String(feature.properties.id));
        else if(!hits(event).some(f=>f.properties?.role==='selected'))state.onDeselect();
      }
    }
    function removeByRightClick(event: MapMouseEvent) {
      const state=eventRef.current;
      event.preventDefault();event.originalEvent.preventDefault();
      if(state.drawingMode){state.onFinishDrawing();return;}
      if(state.editing&&!state.edgeMoving&&!state.moving&&!state.selectedLocked&&state.selected){
        const feature=hits(event).find(f=>f.properties?.role==='edit-vertex');
        let path=feature?nodePath(feature.properties):null;
        if(!path){
          let distance=9;
          for(const v of verticesOf(state.selected)){
            if(v.midpoint)continue;
            const xy=map.project(v.point as maplibregl.LngLatLike);
            const d=Math.hypot(xy.x-event.point.x,xy.y-event.point.y);
            if(d<distance){distance=d;path=v.path;}
          }
        }
        if(path){
          try{
            const next=removeVertex(state.selected,path);
            if(JSON.stringify(next)===JSON.stringify(state.selected))state.onEditingError('Minimum vertex count reached.');
            else state.onGeometryCommit(next);
          }catch(error){state.onEditingError(error instanceof Error?error.message:'Cannot delete vertex.');}
          return;
        }
      }
      if(!state.editing){
        const feature=hits(event).find(f=>f.properties?.role==='saved');
        if(feature?.properties?.id)state.onSelectSavedFeature(String(feature.properties.id));
      }
      state.onContextMenu(event.originalEvent.clientX,event.originalEvent.clientY);
    }
    function insertByDoubleClick(event: MapMouseEvent) {
      const state = eventRef.current;
      if(state.drawingMode){event.preventDefault();state.onFinishDrawing();return;}
      if (!state.editing || state.edgeMoving || state.selectedLocked || !state.selected) return;
      const edges = verticesOf(state.selected).filter(p => p.midpoint);
      if (!edges.length) return;
      const pixel = event.point;
      let distance = 10;
      let selectedPath: GeometryPath | null = null;
      let snapped: Position | null = null;
      const geoms = pathsOf(state.selected);
      for (const node of edges) {
        const index = state.selected?.type === 'MultiPolygon'
          ? state.selected.coordinates.slice(0,node.path.polygon).reduce((sum,group) => sum+group.length,0) + node.path.ring
          : state.selected?.type==='MultiLineString'?node.path.polygon:node.path.ring;
        const path = geoms[index];
        if (!path) continue;
        const first = path[node.path.vertex];
        const next = path[node.path.vertex + 1];
        if (!first || !next) continue;
        const a = map.project(first as maplibregl.LngLatLike);
        const b = map.project(next as maplibregl.LngLatLike);
        const dx = b.x - a.x, dy = b.y - a.y;
        const length = dx * dx + dy * dy;
        if (!length) continue;
        const t = Math.max(0, Math.min(1,
          ((pixel.x - a.x) * dx + (pixel.y - a.y) * dy) / length));
        const close = Math.hypot(pixel.x - a.x - dx * t,pixel.y - a.y - dy * t);
        if (close < distance) {
          distance = close;
          selectedPath = node.path;
          snapped = [first[0] + (next[0] - first[0]) * t,
                     first[1] + (next[1] - first[1]) * t];
        }
      }
      if (selectedPath && snapped) {
        event.preventDefault();
        state.onGeometryCommit(addVertex(state.selected, selectedPath, snapped));
      }
    }

    // Browser acceptance tests must wait for the asynchronous GeoJSON worker
    // to render vertex handles, not merely for React to schedule setData.
    function inspectRenderedHandles() {
      if(!import.meta.env.DEV || !map.getLayer('workspace-points') || !container.current)return;
      const view=renderRef.current;
      if(!view.editing||!view.selected){
        container.current.setAttribute('data-rendered-handle-pixels','[]');
        return;
      }
      const pixels:Position[]=[];
      for(const handle of verticesOf(view.selected).filter(node=>!node.midpoint)){
        const point=map.project(handle.point as maplibregl.LngLatLike);
        const matched=map.queryRenderedFeatures(point,{
          layers:['workspace-points'],
        }).some(item=>item.properties?.role==='edit-vertex');
        if(matched)pixels.push([point.x,point.y]);
      }
      container.current.setAttribute('data-rendered-handle-pixels',JSON.stringify(pixels));
    }
    map.on('idle',inspectRenderedHandles);
    map.on('moveend', bounds);
    const onEscape=(event:KeyboardEvent)=>{
      if(event.key==='Escape'){
        drag.current=null;selectionDrag.current=null;labelDrag.current=null;labelPointer.current=null;spatialSnap.current=null;
        for(const name of ['selection-preview','label-drag-preview']){
          (map.getSource(name) as GeoJSONSource|undefined)?.setData({type:'FeatureCollection',features:[]});
        }
        map.dragPan.enable();
      }
    };
    window.addEventListener('keydown',onEscape);
    map.on('click', click);
    map.on('mousedown', beginDrag);
    map.on('mousemove', dragging);
    map.on('mousemove',displayCoordinates);
    map.on('mouseup', finishDrag);
    window.addEventListener('mouseup',finishDrag);
    map.on('contextmenu', removeByRightClick);
    map.on('dblclick', insertByDoubleClick);
    // Install local workspace layers as soon as the style is parsed. Waiting
    // for the full "load" event would block editing when a remote raster tile
    // server is slow, unavailable, or rate limited.
    map.on('style.load', () => {
      if(map.getSource('workspace'))return;
      map.addSource('workspace', {
        type: 'geojson', data: { type: 'FeatureCollection', features: [] },
      });
      map.addSource('label-drag-preview',{
        type:'geojson',data:{type:'FeatureCollection',features:[]},
      });
      map.addLayer({
        id:'label-drag-preview-text',type:'symbol',source:'label-drag-preview',
        layout:{'text-field':['get','label'],'text-font':['Open Sans Regular'],
          'text-size':14,'text-allow-overlap':true},
        paint:{'text-color':'#cf4e18','text-halo-color':'#fff','text-halo-width':2},
      });
      map.addSource('project-grid',{type:'geojson',
        data:{type:'FeatureCollection',features:[]}});
      map.addLayer({id:'project-grid-lines',type:'line',source:'project-grid',
        paint:{'line-color':'#4b9dc3','line-opacity':.45,'line-width':1,
          'line-dasharray':[4,4]}});
      map.addLayer({id:'project-grid-labels',type:'symbol',source:'project-grid',
        layout:{'symbol-placement':'line','text-field':['get','label'],
          'text-size':10,'text-font':['Open Sans Regular'],
          'text-rotation-alignment':'map','text-allow-overlap':false},
        paint:{'text-color':'#367a9c','text-halo-color':'#ffffff',
          'text-halo-width':1}});
      map.addSource('selection-preview',{
        type:'geojson',data:{type:'FeatureCollection',features:[]},
      });
      map.addLayer({id:'selection-preview-fill',source:'selection-preview',type:'fill',
        paint:{'fill-color':'#20a9cf','fill-opacity':.15}});
      map.addLayer({id:'selection-preview-line',source:'selection-preview',type:'line',
        paint:{'line-color':'#20a9cf','line-width':2,'line-dasharray':[2,2]}});
      map.addSource('terrain-fetch-target',{type:'geojson',data:{type:'FeatureCollection',features:[]}});
      map.addLayer({id:'terrain-fetch-target-fill',source:'terrain-fetch-target',type:'fill',paint:{'fill-color':'#d47b19','fill-opacity':.055}});
      map.addLayer({id:'terrain-fetch-target-outline',source:'terrain-fetch-target',type:'line',paint:{'line-color':'#d47b19','line-width':2,'line-dasharray':[3,2]}});
      map.addSource('terrain-result',{type:'geojson',data:{type:'FeatureCollection',features:[]}});
      map.addLayer({id:'terrain-result-fill',source:'terrain-result',type:'fill',
        filter:['==',['geometry-type'],'Polygon'],
        paint:{'fill-color':['case',['==',['get','name'],'Visible terrain'],'#1bba66','#2ca9df'],'fill-opacity':.42}});
      map.addLayer({id:'terrain-result-lines',source:'terrain-result',type:'line',
        paint:{'line-color':['case',['has','elevation_m'],['case',['==',['get','major'],true],'#ffde8b','#f2bd68'],['==',['get','name'],'Visible terrain'],'#137842','#126caa'],
          'line-width':['case',['has','elevation_m'],['case',['==',['get','major'],true],2.4,1.25],2],'line-opacity':.95}});
      map.addLayer({id:'terrain-result-labels',source:'terrain-result',type:'symbol',
        filter:['all',['==',['geometry-type'],'LineString'],['has','elevation_m']],
        layout:{'symbol-placement':'line','text-field':['concat',['to-string',['get','elevation_m']],' m'],
          'text-font':['Open Sans Regular'],'text-size':11,'symbol-spacing':180},
        paint:{'text-color':'#70401a','text-halo-color':'#fff','text-halo-width':1.3}});
      map.addLayer({
        id: 'workspace-fill', type: 'fill', source: 'workspace',
        filter: ['==', ['geometry-type'], 'Polygon'],
        paint: {
          'fill-color': ['coalesce', ['get', 'color'], '#2563eb'],
          'fill-opacity': ['coalesce',['get','fillOpacity'],0.17],
        },
      });
      map.addLayer({
        id: 'workspace-lines', type: 'line', source: 'workspace',
        filter: ['any', ['==', ['geometry-type'], 'Polygon'],
                        ['==', ['geometry-type'], 'LineString']],
        paint: {
          'line-color': ['coalesce', ['get', 'color'], '#2563eb'],
          'line-width': ['coalesce',['get','lineWidth'],3], 'line-opacity': 0.95,
        },
      });
      map.addLayer({
        id: 'workspace-points', type: 'circle', source: 'workspace',
        filter: ['==', ['geometry-type'], 'Point'],
        paint: {
          'circle-color': [
            'match',['get','role'],
            'prompt-positive','#39b779','prompt-negative','#ed4a4a',
            'prompt-box-corner','#f2a138','edit-midpoint','#c9e5ff',
            'saved',['coalesce',['get','color'],'#2563eb'],'#ffffff',
          ],
          'circle-radius': [
            'case',['==',['get','role'],'edit-midpoint'],4,
            ['coalesce',['get','pointRadius'],6],
          ],
          'circle-stroke-color': ['coalesce',['get','strokeColor'],'#2563eb'],
          'circle-stroke-width': 2,
        },
      });
      map.addLayer({
        id:'workspace-labels',type:'symbol',source:'workspace',
        filter:['all',['==',['get','role'],'saved'],
          ['any',['!=',['geometry-type'],'LineString'],
                 ['!=',['get','labelPlacement'],'line']],
          ['!=',['get','label'],'']],
        layout:{
          'text-field':['get','label'],
          'text-font':['Open Sans Regular'],
          'symbol-sort-key':['get','labelSortKey'],
          'text-offset':['get','labelOffset'],
          'text-size':['coalesce',['get','labelSize'],12],
          'text-max-width':15,
          'text-allow-overlap':['coalesce',['get','labelOverlap'],false],
          'text-padding':4,
          'text-optional':true,
        },
        paint:{
          'text-color':['coalesce',['get','labelColor'],'#183954'],
          'text-halo-color':['coalesce',['get','labelHaloColor'],'#ffffff'],
          'text-halo-width':['coalesce',['get','labelHaloWidth'],1.5],
        },
      });
      map.addLayer({
        id:'workspace-line-labels',type:'symbol',source:'workspace',
        filter:['all',['==',['get','role'],'saved'],
          ['==',['geometry-type'],'LineString'],
          ['==',['get','labelPlacement'],'line'],
          ['!=',['get','label'],'']],
        layout:{'symbol-placement':'line','text-field':['get','label'],
          'text-font':['Open Sans Regular'],'text-size':['get','labelSize'],
          'text-allow-overlap':['get','labelOverlap'],
          'symbol-sort-key':['get','labelSortKey'],
          'text-max-angle':30,
        },
        paint:{'text-color':['get','labelColor'],
          'text-halo-color':['get','labelHaloColor'],
          'text-halo-width':['get','labelHaloWidth']},
      });
      setReady(true);
      bounds();
    });
    mapRef.current = map;
    const resize=new ResizeObserver(()=>map.resize());resize.observe(container.current);
    return () => {
      resize.disconnect();
      map.off('zoomend',refreshZoomLabels);
      map.off('idle',inspectRenderedHandles);
      map.off('mousemove', dragging);
      map.off('mousemove',displayCoordinates);
      map.off('mouseup', finishDrag);
      window.removeEventListener('mouseup',finishDrag);
      window.removeEventListener('keydown',onEscape);
      map.dragPan.enable();
      mapRef.current = null;
      map.remove();
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const collection=featureCollection(selected,vertices,drawingMode,discovered,layerFeatures,
      editing,promptPositive,promptNegative,promptBox,selectedIds,qualityIssues,
      map.getZoom(),(point,dx,dy)=>{
        const p=map.project(point as maplibregl.LngLatLike);
        const shifted=map.unproject([p.x+dx,p.y+dy]);
        return [shifted.lng,shifted.lat];
      },cursor,selectedFeatureId);
    (map.getSource('workspace') as GeoJSONSource).setData(collection);
    if(container.current && import.meta.env.DEV){
      container.current.setAttribute('data-label-feature-count',
        String(collection.features.filter(item=>Boolean(item.properties?.label)).length));
      const handles=editing&&selected?verticesOf(selected).filter(item=>!item.midpoint).map(item=>{
        const p=map.project(item.point as maplibregl.LngLatLike);
        return [p.x,p.y];
      }):[];
      container.current.setAttribute('data-edit-handle-pixels',JSON.stringify(handles));
    }
    if (!drag.current) spatialSnap.current=null;
  }, [selected, vertices, drawingMode, discovered, layerFeatures, editing,
      promptPositive,promptNegative,promptBox,selectedIds,qualityIssues,ready,cursor,selectedFeatureId]);

  useEffect(()=>{
    const map=mapRef.current;
    if(!ready||!map)return;
    const current=map.getStyle().layers
      .filter(layer=>layer.id.startsWith('remote-ogc-'))
      .map(layer=>layer.id);
    const wanted=new Set(externalTiles.map(tile=>'remote-ogc-'+tile.id));
    for(const id of current){
      if(wanted.has(id))continue;
      if(map.getLayer(id))map.removeLayer(id);
      const sourceId=id.replace('remote-ogc-','remote-ogc-source-');
      if(map.getSource(sourceId))map.removeSource(sourceId);
    }
    for(const tile of externalTiles){
      const sourceId='remote-ogc-source-'+tile.id;
      const id='remote-ogc-'+tile.id;
      if(map.getLayer(id))continue;
      map.addSource(sourceId,{
        type:'raster',tiles:[tile.template],tileSize:256,
        attribution:tile.attribution||tile.title,maxzoom:19,
      });
      map.addLayer({id,source:sourceId,type:'raster',
        paint:{'raster-opacity':.82,'raster-fade-duration':0}},'terrain-result-fill');
    }
  },[externalTiles,ready]);

  useEffect(()=>{
    const map=mapRef.current;
    if(!ready||!map)return;
    const source=map.getSource('terrain-result') as GeoJSONSource|undefined;
    source?.setData({type:'FeatureCollection',features:terrainResults});
    container.current?.setAttribute('data-terrain-feature-count',String(terrainResults.length));
  },[terrainResults,ready]);
  useEffect(()=>{
    const map=mapRef.current;if(!ready||!map)return;
    const source=map.getSource('terrain-fetch-target') as GeoJSONSource|undefined;
    const box=terrainFetchTarget;
    source?.setData({type:'FeatureCollection',features:box?[{
      type:'Feature',properties:{name:'DEM download target'},
      geometry:{type:'Polygon',coordinates:[[[box[0],box[1]],[box[2],box[1]],
        [box[2],box[3]],[box[0],box[3]],[box[0],box[1]]]]}
    }]:[]});
    // The requested footprint must stay legible above imported and derived raster layers.
    if(map.getLayer('terrain-fetch-target-fill'))map.moveLayer('terrain-fetch-target-fill');
    if(map.getLayer('terrain-fetch-target-outline'))map.moveLayer('terrain-fetch-target-outline');
    container.current?.setAttribute('data-dem-target-visible',box?'true':'false');
  },[terrainFetchTarget,ready]);
  // Keep derived raster image sources stable when layer visibility changes.
  // Recreating dozens of map images on each result checkbox causes flicker and GPU churn.
  const derivedRasters=useRef(new Set<string>());
  useEffect(()=>{
    const map=mapRef.current;if(!ready||!map)return;
    const desired=new Set((terrainRasters??[]).map(item=>item.id));
    for(const id of derivedRasters.current){
      if(desired.has(id))continue;
      const name='terrain-raster-'+id;
      if(map.getLayer(name))map.removeLayer(name);
      if(map.getSource(name))map.removeSource(name);
      derivedRasters.current.delete(id);
    }
    for(const item of terrainRasters??[]){
      if(derivedRasters.current.has(item.id))continue;
      const name='terrain-raster-'+item.id;
      try{
        map.addSource(name,{type:'image',url:item.raster.png,coordinates:item.raster.corners});
        map.addLayer({id:name,source:name,type:'raster',
          paint:{'raster-opacity':.72,'raster-fade-duration':0}},'terrain-result-lines');
        derivedRasters.current.add(item.id);
      }catch(e){
        if(map.getLayer(name))map.removeLayer(name);
        if(map.getSource(name))map.removeSource(name);
        rasterErrors.current('Derived terrain '+item.title+': '+String(e));
      }
    }
    container.current?.setAttribute('data-terrain-raster-count',String(derivedRasters.current.size));
  },[terrainRasters,ready]);
  useEffect(()=>{
    const map=mapRef.current;
    if(!ready||!map)return;
    const source=map.getSource('project-grid') as GeoJSONSource|undefined;
    source?.setData(projectGrid??{type:'FeatureCollection',features:[]});
  },[projectGrid,ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !focus) return;
    if (focus.bbox && focus.bbox[0] < focus.bbox[2] && focus.bbox[1] < focus.bbox[3]) {
      map.fitBounds([[focus.bbox[0], focus.bbox[1]], [focus.bbox[2], focus.bbox[3]]], {
        padding: 60, maxZoom: 20, duration: 650,
      });
    } else {
      map.flyTo({ center: [focus.longitude, focus.latitude], zoom: 15, duration: 950 });
    }
  }, [focus, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if(!ready||!map)return;
    if(map.getLayer('custom'))map.removeLayer('custom');
    if(map.getSource('custom'))map.removeSource('custom');
    if(customBasemap){
      const attribution=customBasemap.attribution.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
      map.addSource('custom',{type:'raster',tiles:[customBasemap.url],tileSize:256,maxzoom:customBasemap.maxzoom,attribution});
      map.addLayer({id:'custom',type:'raster',source:'custom',layout:{visibility:'none'}},'street');
    }
  },[customBasemap,ready]);
  useEffect(()=>{
    const map=mapRef.current;if(!ready||!map)return;
    const title=BASEMAPS.find(item=>item.id===basemap)?.name??basemap;
    const error=(event:unknown)=>{
      const id=(event as {sourceId?:string}).sourceId;
      if(id===basemap)onBasemapStatus('Imagery unavailable: '+title+'. Check network or provider coverage.');
    };
    const data=(event:unknown)=>{
      const value=event as {sourceId?:string;tile?:{state?:string}};
      if(value.sourceId===basemap&&value.tile?.state==='loaded')onBasemapStatus(title+' · tile loaded');
    };
    map.on('error',error);map.on('sourcedata',data);
    onBasemapStatus(basemap==='blank'?'Blank canvas':'Loading '+title+'…');
    for(const layer of BASEMAPS)if(map.getLayer(layer.id)&&layer.id!=='blank')
      map.setLayoutProperty(layer.id,'visibility',layer.id===basemap?'visible':'none');
    return()=>{map.off('error',error);map.off('sourcedata',data);};
  },[basemap,customBasemap,ready,onBasemapStatus]);

  // Maintain independent image sources. Updating opacity or visibility never
  // recreates tiles, and removing a source invalidates its pending fetch.
  const attachedRasters=useRef(new Map<string,{cancelled:boolean;url?:string}>());
  const rasterErrors=useRef(onRasterError);rasterErrors.current=onRasterError;
  useEffect(()=>{
    const map=mapRef.current;if(!ready||!map)return;
    const attached=attachedRasters.current;
    const remove=(id:string,entry:{cancelled:boolean;url?:string})=>{
      entry.cancelled=true;
      const name='imported-'+id;
      if(map.getLayer(name))map.removeLayer(name);
      if(map.getSource(name))map.removeSource(name);
      if(entry.url)URL.revokeObjectURL(entry.url);
    };
    for(const [id,entry] of attached)if(!rasterLayers.some(l=>l.asset.id===id)){remove(id,entry);attached.delete(id);}
    for(const layer of rasterLayers){
      const asset=layer.asset,name='imported-'+asset.id;
      const current=attached.get(asset.id);
      if(current){
        if(map.getLayer(name)){map.setPaintProperty(name,'raster-opacity',layer.opacity);map.setLayoutProperty(name,'visibility',layer.visible?'visible':'none');}
        continue;
      }
      const entry:{cancelled:boolean;url?:string}={cancelled:false};attached.set(asset.id,entry);
      const add=(url:string)=>{
        if(entry.cancelled)return;
        try{
          map.addSource(name,{type:'image',url,coordinates:asset.corners});
          map.addLayer({id:name,type:'raster',source:name,layout:{visibility:layer.visible?'visible':'none'},paint:{'raster-opacity':layer.opacity,'raster-fade-duration':0}},'terrain-result-fill');
        }catch(e){rasterErrors.current('Raster '+asset.name+': '+String(e));}
      };
      if(window.sessionStorage.getItem('geofathom-api-token')){
        protectedRasterPreview(asset).then(url=>{if(entry.cancelled){URL.revokeObjectURL(url);return;}entry.url=url;add(url);}).catch(e=>{
          if(!entry.cancelled)rasterErrors.current('Raster '+asset.name+': '+String(e));
        });
      }else add(rasterPreviewUrl(asset));
    }
    // Layer order is the layer panel order, irrespective of request completion.
    for(const layer of rasterLayers){const name='imported-'+layer.asset.id;if(map.getLayer(name))map.moveLayer(name,'terrain-result-fill');}
  },[rasterLayers,ready]);
  useEffect(()=>{
    const map=mapRef.current;if(!map||!ready)return;
    const handler=(event:unknown)=>{
      const e=event as {sourceId?:string;error?:Error};if(e.sourceId?.startsWith('imported-'))rasterErrors.current('Raster preview failed: '+(e.error?.message??e.sourceId));
    };
    map.on('error',handler);
    return()=>{map.off('error',handler);for(const entry of attachedRasters.current.values()){entry.cancelled=true;if(entry.url)URL.revokeObjectURL(entry.url);}attachedRasters.current.clear();};
  },[ready]);
  useEffect(()=>{
    const map=mapRef.current;if(!ready||!map)return;
    const palette=mapPalette(basemap,display.contrast);
    const color:maplibregl.ExpressionSpecification=['match',['get','role'],'selected',palette.selected,'drawing',palette.draw,['coalesce',['get','color'],'#2563eb']];
    map.setPaintProperty('workspace-lines','line-color',color);
    map.setPaintProperty('workspace-fill','fill-color',color);
    map.setPaintProperty('workspace-fill','fill-opacity',['match',['get','role'],'selected',display.fill,'drawing',display.fill,['coalesce',['get','fillOpacity'],.17]]);
    map.setPaintProperty('terrain-result-lines','line-color',['case',['has','elevation_m'],['case',['==',['get','major'],true],palette.major,palette.contour],['==',['get','name'],'Visible terrain'],'#21bb72',['coalesce',['get','color'],'#1ea8df']]);
    map.setPaintProperty('terrain-result-labels','text-color',palette.text);
    map.setPaintProperty('terrain-result-labels','text-halo-color',palette.halo);
  },[ready,basemap,display]);
  useEffect(()=>{setCursor(null);},[drawingMode]);
  useEffect(()=>{
    const map=mapRef.current;
    drag.current=null;selectionDrag.current=null;labelDrag.current=null;labelPointer.current=null;
    spatialSnap.current=null;map?.dragPan.enable();
    for(const name of ['selection-preview','label-drag-preview']){
      (map?.getSource(name) as GeoJSONSource|undefined)?.setData({type:'FeatureCollection',features:[]});
    }
  },[selectedFeatureId,editing,moving,edgeMoving,drawingMode,terrainPicking,selectionBoxMode,labelMoveMode]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.doubleClickZoom[editing||drawingMode ? 'disable' : 'enable']();
    map.getCanvas().style.cursor = drawingMode || traceMode || editing || annotationMode || selectionBoxMode || labelMoveMode || terrainPicking ? 'crosshair' : '';
  }, [editing, drawingMode, traceMode, annotationMode, selectionBoxMode,labelMoveMode,terrainPicking,ready]);

  useEffect(()=>{
    const map=mapRef.current;if(!ready||!map||!terrainMarker)return;
    const node=document.createElement('div');node.className='terrain-map-marker';node.setAttribute('aria-label','Terrain sample location');
    const marker=new maplibregl.Marker({element:node}).setLngLat(terrainMarker).addTo(map);
    return()=>{marker.remove();};
  },[terrainMarker,ready]);


  // HTML dimension labels do not depend on a remote glyph server.
  // Reproject on every map movement; never intercept editing gestures.
  useEffect(()=>{
    const map=mapRef.current,overlay=dimensionRef.current;
    if(!map||!overlay||!ready)return;
    overlay.replaceChildren();
    const draft=drawingPreview(drawingMode,vertices,cursor);
    const g=draft??selected;
    if(!showMeasurements||!g)return;
    const exact=!draft&&measurement?.method!==OFFLINE_METHOD?measurement:null;
    const totals=exact??approximateMeasurement(g);
    const prefix=exact?'':'~ ';
    const palette=mapPalette(basemap,display.contrast);
    overlay.style.setProperty('--dimension-text',palette.text);overlay.style.setProperty('--dimension-halo',palette.halo);
    const labels:Array<{a:Position;b?:Position;node:HTMLDivElement}>=[];
    function label(text:string,a:Position,b?:Position){
      const node=document.createElement('div');
      node.className=b?'map-edge-value':'map-dimension-total';
      node.textContent=text;overlay!.appendChild(node);labels.push({a,b,node});
    }
    const anchor=measurementAnchor(g);
    if(anchor){
      if(totals.area_m2!==null)label(prefix+areaText(totals.area_m2,display.area)+'\n'+prefix+distanceText(totals.perimeter_m??0,display.distance)+' perimeter',anchor);
      else if(totals.length_m!==null)label(prefix+distanceText(totals.length_m,display.distance)+' total',anchor);
      else if(g.type==='Point')label(anchor[0].toFixed(6)+'°, '+anchor[1].toFixed(6)+'°',anchor);
    }
    let index=0;
    for(const path of pathsOf(g)){
      for(let i=1;i<path.length&&index<48;i++,index++){
        const a=path[i-1],b=path[i];
        const value=exact?.edge_lengths_m?.[index];
        label((value===undefined?'~ ':'')+distanceText(value??edgeDistance(a,b).distance_m,display.distance),a,b);
      }
      if(index>=48)break;
    }
    const layout=()=>{
      const placed:Array<{left:number;right:number;top:number;bottom:number}>=[];
      const width=map.getContainer().clientWidth,height=map.getContainer().clientHeight;
      // Use actual measured text dimensions, including the two-line total.
      // Keep hidden elements measurable without covering the map.
      const sizes=labels.map(({node})=>({w:node.offsetWidth+8,h:node.offsetHeight+6}));
      for(const [index,item] of labels.entries()){
        const a=map.project(item.a),b=item.b?map.project(item.b):null;
        const x=b?(a.x+b.x)/2:a.x,y=b?(a.y+b.y)/2:a.y;
        const {w,h}=sizes[index];
        const rect={left:x-w/2,right:x+w/2,top:y-h/2,bottom:y+h/2};
        const collision=placed.some(p=>rect.left<p.right&&rect.right>p.left&&rect.top<p.bottom&&rect.bottom>p.top);
        const hidden=rect.left<3||rect.top<3||rect.right>width-3||rect.bottom>height-3||
          !!(b&&(Math.hypot(a.x-b.x,a.y-b.y)<Math.min(w,42)||collision));
        item.node.style.visibility=hidden?'hidden':'visible';
        if(!hidden){item.node.style.transform='translate('+x+'px,'+y+'px) translate(-50%,-50%)';placed.push(rect);}
      }
    };
    layout();map.on('render',layout);
    return ()=>{map.off('render',layout);overlay.replaceChildren();};
  },[ready,selected,drawingMode,vertices,cursor,measurement,showMeasurements,display,basemap]);

  return <>
    <div aria-label="Interactive geospatial map" data-label-layer-ready={ready ? "true" : "false"} className="map-canvas" ref={container}/>
    <div className="map-dimension-overlay" aria-label="Live map dimensions" ref={dimensionRef}/>
    <div aria-label="Cursor coordinates" className="map-coordinate-readout" ref={coordinateRef}>
      Move cursor to inspect WGS84 coordinates
    </div>
  </>;
}
