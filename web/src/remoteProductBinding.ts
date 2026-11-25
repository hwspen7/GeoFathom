import type {RemoteBinding,RemoteQuality,RemoteSource} from './api';

const landsat:Record<string,string>={SR_B2:'blue',SR_B3:'green',SR_B4:'red',SR_B5:'nir',SR_B6:'swir1',SR_B7:'swir2',ST_B10:'temperature',QA_PIXEL:'qa_pixel',QA_RADSAT:'qa_radsat'};
const sentinel:Record<string,string>={B02:'blue',B03:'green',B04:'red',B05:'rededge',B06:'rededge2',B07:'rededge3',B08:'nir',B8A:'nir_narrow',B11:'swir1',B12:'swir2',SCL:'scl'};
export function identifyBand(name:string){
 const file=name.replace(/ \(disk\)$/i,'').split(/[\\/]/).at(-1)??'';
 const l=file.match(/^(LC0[89]_L2(?:SP|SR)_\d{6}_\d{8}_\d{8}_02_(?:T1|T2|RT))_(SR_B[2-7]|ST_B10|QA_PIXEL|QA_RADSAT)\.tiff?$/i);
 if(l){const code=l[2].toUpperCase();return {sensor:'Landsat C2 L2',scene:l[1].toUpperCase(),role:landsat[code],code};}
 const s=file.match(/^(?:L2A_)?(T\d{2}[A-Z]{3}_\d{8}T\d{6})_(B02|B03|B04|B05|B06|B07|B08|B8A|B11|B12|SCL)_(10m|20m|60m)\.tiff?$/i);
 if(s){const code=s[2].toUpperCase();return {sensor:'Sentinel-2 tile',scene:s[1].toUpperCase(),role:sentinel[code],code};}
 return null;
}
export function suggestProductBindings(sources:RemoteSource[],roles:Array<{id:string;quantity:string}>){
 const found=sources.map((s,index)=>({index,product:identifyBand(s.name)})).filter(x=>x.product!==null);
 if(!found.length)throw Error('No recognized official single-band product filenames.');
 const scenes=new Set(found.map(x=>x.product!.sensor+':'+x.product!.scene));
 if(scenes.size!==1)throw Error('Multiple acquisitions detected; bind each acquisition explicitly.');
 const out:Record<string,RemoteBinding>={};
 for(const r of roles){
  const candidates=found.filter(x=>x.product!.role===r.id);
  if(candidates.length!==1)throw Error('Missing or ambiguous product band: '+r.id);
  const {index,product}=candidates[0];
  if(product!.sensor.startsWith('Landsat')&&((product!.code==='ST_B10'&&r.quantity!=='kelvin')||(product!.code.startsWith('SR_')&&r.quantity!=='reflectance')))throw Error('Product quantity mismatch: '+r.id);
  if(product!.sensor.startsWith('Sentinel')&&r.quantity!=='reflectance')throw Error('Sentinel product quantity mismatch: '+r.id);
  if(!product!.code.startsWith('SR_')&&product!.code!=='ST_B10'&&r.quantity!=='reflectance')throw Error('Unsupported automatic band: '+r.id);
  const encoding=product!.code.startsWith('SR_')?'landsat_sr':product!.code==='ST_B10'?'landsat_st':'metadata';
  out[r.id]={source:index,band:1,encoding,scale:1,offset:0,unit:''};
 }
 const quality:RemoteQuality[]=[];
 for(const [role,scheme] of [['qa_pixel','landsat_clear'],['qa_radsat','landsat_unsaturated'],['scl','sentinel_clear']] as const){
  const matches=found.filter(x=>x.product!.role===role);
  if(matches.length>1)throw Error('Ambiguous quality band: '+role);
  if(matches.length===1)quality.push({source:matches[0].index,band:1,scheme,roles:[]});
 }
 return {bindings:out,quality,sensor:found[0].product!.sensor};
}
