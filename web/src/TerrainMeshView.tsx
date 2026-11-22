import {useEffect,useRef,useState,type ReactNode} from 'react';
import type {TerrainMesh} from './api';

export function meshData(mesh:TerrainMesh){
 const valid=mesh.heights.filter((h):h is number=>h!==null&&Number.isFinite(h));
 const lo=valid.length?Math.min(...valid):0,hi=valid.length?Math.max(...valid):0;
 const scale=Math.max((mesh.cols-1)*mesh.dx_m,(mesh.rows-1)*mesh.dy_m,hi-lo,1);
 const vertices:number[]=[],triangles:number[]=[],edges:number[]=[];
 for(let r=0;r<mesh.rows;r++)for(let c=0;c<mesh.cols;c++){
   const h=mesh.heights[r*mesh.cols+c]??lo;
   vertices.push((c-(mesh.cols-1)/2)*mesh.dx_m/scale,
     ((mesh.rows-1)/2-r)*mesh.dy_m/scale,(h-(lo+hi)/2)/scale,
     c/Math.max(1,mesh.cols-1),r/Math.max(1,mesh.rows-1),(h-lo)/(hi-lo||1));
 }
 function face(a:number,b:number,c:number){
   if([a,b,c].some(i=>mesh.heights[i]===null||!Number.isFinite(mesh.heights[i])))return;
   triangles.push(a,b,c);edges.push(a,b,b,c,c,a);
 }
 for(let r=0;r+1<mesh.rows;r++)for(let c=0;c+1<mesh.cols;c++){
   const a=r*mesh.cols+c,b=a+1,d=a+mesh.cols,e=d+1;
   face(a,d,b);face(b,d,e);
 }
 return {vertices:new Float32Array(vertices),triangles:new Uint32Array(triangles),edges:new Uint32Array(edges),scale};
}
export function meshOBJ(mesh:TerrainMesh){
 const d=meshData(mesh),rows=['# GeoFathom local DEM mesh; coordinates in meters, local origin'];
 for(let r=0;r<mesh.rows;r++)for(let c=0;c<mesh.cols;c++)rows.push('v '+(c*mesh.dx_m)+' '+(-r*mesh.dy_m)+' '+(mesh.heights[r*mesh.cols+c]??0));
 for(let i=0;i<d.triangles.length;i+=3)rows.push('f '+[d.triangles[i]+1,d.triangles[i+1]+1,d.triangles[i+2]+1].join(' '));
 return rows.join('\n')+'\n';
}
type Camera={angle:number;tilt:number;exaggeration:number;zoom:number;clip:number;wire:boolean;drape:boolean;panX:number;panY:number};
function renderer(gl:WebGL2RenderingContext,mesh:TerrainMesh,redraw:()=>void){
 const data=meshData(mesh);
 function shader(type:number,source:string){
   const s=gl.createShader(type);if(!s)throw Error('Shader allocation failed');
   gl.shaderSource(s,source);gl.compileShader(s);
   if(!gl.getShaderParameter(s,gl.COMPILE_STATUS)){const error=gl.getShaderInfoLog(s);gl.deleteShader(s);throw Error(error??'Shader failed');}
   return s;
 }
 const v=shader(gl.VERTEX_SHADER,`#version 300 es
 in vec3 p;in vec2 uv;in float h;out vec2 tex;out float elevation;
 uniform float angle,tilt,exaggeration,zoom,aspect;uniform vec2 pan;
 void main(){
  float x=p.x*cos(angle)-p.y*sin(angle),y=p.x*sin(angle)+p.y*cos(angle),z=p.z*exaggeration;
  vec3 q=vec3(x,y*cos(tilt)+z*sin(tilt),y*sin(tilt)-z*cos(tilt));
  gl_Position=vec4(q.x*zoom/aspect+pan.x,q.y*zoom+pan.y,q.z*.15,1.);
  tex=uv;elevation=h;
 }`);
 const f=shader(gl.FRAGMENT_SHADER,`#version 300 es
 precision highp float;in vec2 tex;in float elevation;out vec4 color;
 uniform sampler2D imagery;uniform bool drape,wire;uniform float clip;
 void main(){
  if(tex.x>clip)discard;
  vec3 ground=mix(vec3(.22,.44,.30),vec3(.86,.73,.49),elevation);
  vec4 img=texture(imagery,tex);
  if(drape&&img.a>.5)ground=img.rgb;
  color=vec4(wire?vec3(.15,.27,.33):ground,1.);
 }`);
 const program=gl.createProgram();if(!program)throw Error('Program allocation failed');
 gl.attachShader(program,v);gl.attachShader(program,f);gl.linkProgram(program);gl.deleteShader(v);gl.deleteShader(f);
 if(!gl.getProgramParameter(program,gl.LINK_STATUS)){gl.deleteProgram(program);throw Error('Terrain shader link failed');}
 gl.useProgram(program);
 const vertex=gl.createBuffer(),index=gl.createBuffer(),wireIndex=gl.createBuffer(),texture=gl.createTexture();
 gl.bindBuffer(gl.ARRAY_BUFFER,vertex);gl.bufferData(gl.ARRAY_BUFFER,data.vertices,gl.STATIC_DRAW);
 for(const [name,count,offset] of [['p',3,0],['uv',2,12],['h',1,20]] as const){
   const loc=gl.getAttribLocation(program,name);gl.enableVertexAttribArray(loc);gl.vertexAttribPointer(loc,count,gl.FLOAT,false,24,offset);
 }
 gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,index);gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,data.triangles,gl.STATIC_DRAW);
 gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,wireIndex);gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,data.edges,gl.STATIC_DRAW);
 gl.bindTexture(gl.TEXTURE_2D,texture);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,1,1,0,gl.RGBA,gl.UNSIGNED_BYTE,new Uint8Array([0,0,0,0]));
 gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
 gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
 let disposed=false;
 if(mesh.texture){const img=new Image();img.onload=()=>{if(disposed)return;gl.bindTexture(gl.TEXTURE_2D,texture);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,img);redraw();};img.src=mesh.texture.png;}
 function draw(camera:Camera){
   if(disposed||gl.isContextLost())return;
   gl.viewport(0,0,gl.drawingBufferWidth,gl.drawingBufferHeight);gl.clearColor(.93,.95,.96,1);gl.clearDepth(1);gl.enable(gl.DEPTH_TEST);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
   gl.useProgram(program);
   for(const [name,value] of Object.entries({angle:camera.angle,tilt:camera.tilt,exaggeration:camera.exaggeration,zoom:camera.zoom,clip:camera.clip,aspect:gl.drawingBufferWidth/Math.max(1,gl.drawingBufferHeight)}))
     gl.uniform1f(gl.getUniformLocation(program,name),value);
   gl.uniform2f(gl.getUniformLocation(program,'pan'),camera.panX,camera.panY);
   gl.uniform1i(gl.getUniformLocation(program,'drape'),Number(camera.drape));
   gl.uniform1i(gl.getUniformLocation(program,'wire'),Number(camera.wire));
   gl.uniform1i(gl.getUniformLocation(program,'imagery'),0);
   gl.bindTexture(gl.TEXTURE_2D,texture);gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,camera.wire?wireIndex:index);
   gl.drawElements(camera.wire?gl.LINES:gl.TRIANGLES,camera.wire?data.edges.length:data.triangles.length,gl.UNSIGNED_INT,0);
 }
 return {draw,dispose(){disposed=true;gl.deleteBuffer(vertex);gl.deleteBuffer(index);gl.deleteBuffer(wireIndex);gl.deleteTexture(texture);gl.deleteProgram(program);}};
}
const initial:Camera={angle:-.6,tilt:.7,exaggeration:1,zoom:1.6,clip:1,wire:false,drape:true,panX:0,panY:0};
export function GPUView({mesh,fallback}:{mesh:TerrainMesh;fallback:ReactNode}){
 const canvas=useRef<HTMLCanvasElement>(null),render=useRef<ReturnType<typeof renderer>|null>(null),drag=useRef<{x:number;y:number;pan:boolean}|null>(null);
 const [camera,setCamera]=useState(initial),[available,setAvailable]=useState(true);
 const latest=useRef(camera);latest.current=camera;
 useEffect(()=>{
   const node=canvas.current;if(!node)return;
   try{
     const gl=node.getContext('webgl2',{antialias:true,preserveDrawingBuffer:true});if(!gl)throw Error('WebGL2 unavailable');
     const engine=renderer(gl,mesh,()=>render.current?.draw(latest.current));render.current=engine;engine.draw(latest.current);
     const lost=(e:Event)=>{e.preventDefault();setAvailable(false);};
     node.addEventListener('webglcontextlost',lost);
     return()=>{node.removeEventListener('webglcontextlost',lost);engine.dispose();render.current=null;};
   }catch{setAvailable(false);}
 },[mesh]);
 useEffect(()=>{render.current?.draw(camera);},[camera]);
 if(!available)return <><small>WebGL2 unavailable · CPU preview</small>{fallback}</>;
 const update=(values:Partial<Camera>)=>setCamera(old=>({...old,...values}));
 function save(){const a=document.createElement('a'),url=URL.createObjectURL(new Blob([meshOBJ(mesh)],{type:'text/plain'}));a.href=url;a.download='terrain.obj';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
 return <div className="dem-mesh">
   <canvas width={768} height={480} ref={canvas} aria-label="Interactive 3D terrain preview" data-renderer="webgl2"
     onPointerDown={e=>{e.currentTarget.setPointerCapture(e.pointerId);drag.current={x:e.clientX,y:e.clientY,pan:e.shiftKey};}}
     onPointerMove={e=>{const d=drag.current;if(!d)return;const dx=e.clientX-d.x,dy=e.clientY-d.y;setCamera(c=>d.pan?{...c,panX:c.panX+dx/150,panY:c.panY-dy/150}:{...c,angle:c.angle+dx*.01,tilt:Math.max(.05,Math.min(1.5,c.tilt+dy*.01))});drag.current={x:e.clientX,y:e.clientY,pan:d.pan};}}
     onPointerUp={()=>{drag.current=null;}} onPointerCancel={()=>{drag.current=null;}}/>
   <label>Vertical exaggeration <input aria-label="Terrain vertical exaggeration" type="range" min="1" max="10" step=".5" value={camera.exaggeration} onChange={e=>update({exaggeration:Number(e.target.value)})}/></label>
   <label>Zoom <input type="range" min=".5" max="4" step=".1" value={camera.zoom} onChange={e=>update({zoom:Number(e.target.value)})}/></label>
   <label>Clip surface <input type="range" min=".05" max="1" step=".01" value={camera.clip} onChange={e=>update({clip:Number(e.target.value)})}/></label>
   <div className="survey-action-bar"><label><input type="checkbox" checked={camera.wire} onChange={e=>update({wire:e.target.checked})}/>Wireframe</label>
    {mesh.texture&&<label><input type="checkbox" checked={camera.drape} onChange={e=>update({drape:e.target.checked})}/>Imagery</label>}
    <button onClick={()=>setCamera(initial)}>Reset view</button><button onClick={save}>OBJ</button></div>
   {mesh.texture&&<small>RGB image coverage {mesh.texture.coverage_pct.toFixed(1)}%</small>}
 </div>;
}
