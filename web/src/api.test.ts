/** Network-boundary contracts: encoding, authentication, errors and binary exports. */
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import * as api from './api';

describe('protected API transport',()=>{
  const data=new Map<string,string>();
  const fetchMock=vi.fn<typeof fetch>();
  beforeEach(()=>{
    data.clear();
    fetchMock.mockReset();
    vi.stubGlobal('fetch',fetchMock);
    vi.stubGlobal('window',{
      sessionStorage:{
        getItem:(key:string)=>data.get(key)??null,
        setItem:(key:string,value:string)=>data.set(key,value),
        removeItem:(key:string)=>data.delete(key),
      },
      setTimeout:(fn:()=>void)=>{fn();return 0;},
    });
    fetchMock.mockImplementation(async()=>new Response(JSON.stringify({}),{
      status:200,headers:{'Content-Type':'application/json'}
    }));
  });
  afterEach(()=>vi.unstubAllGlobals());

  function last(){
    const [url,init]=fetchMock.mock.calls.at(-1)!;
    return {url:String(url),init,headers:new Headers(init?.headers)};
  }

  it('encodes search text and keeps credentials out of URLs',async()=>{
    api.setApiAccessToken('session-key');
    fetchMock.mockResolvedValueOnce(Response.json({results:[{id:'a'}]}));
    expect(await api.searchPlaces('A&B / 北京')).toEqual([{id:'a'}]);
    const req=last();
    expect(new URL(req.url).searchParams.get('q')).toBe('A&B / 北京');
    expect(req.headers.get('X-GeoFathom-API-Key')).toBe('session-key');
    expect(req.url).not.toContain('session-key');
    api.setApiAccessToken('');
    await api.getCapabilities();
    expect(last().headers.has('X-GeoFathom-API-Key')).toBe(false);
  });

  it('preserves JSON body and layer identity when saving geometry',async()=>{
    const geometry:GeoJSON.Point={type:'Point',coordinates:[-83,40]};
    await api.saveProjectFeature('project/one','sample',geometry,'manual',{category:1},'layer-2');
    const {url,init,headers}=last();
    expect(url).toContain('/projects/project%2Fone/features');
    expect(init?.method).toBe('POST');
    expect(headers.get('Content-Type')).toBe('application/json');
    expect(JSON.parse(String(init?.body))).toEqual({
      name:'sample',geometry,source:'manual',properties:{category:1},layer_id:'layer-2'
    });
  });

  it('reports server details and handles non-JSON failures',async()=>{
    fetchMock.mockResolvedValueOnce(Response.json({detail:'Stale revision'},{status:409}));
    await expect(api.getCapabilities()).rejects.toThrow('Stale revision');
    fetchMock.mockResolvedValueOnce(new Response('gateway down',{status:502,statusText:'Bad Gateway'}));
    await expect(api.getCapabilities()).rejects.toThrow('Bad Gateway');
    fetchMock.mockResolvedValueOnce(Response.json({detail:[{msg:'bad input'}]},{status:422}));
    await expect(api.getCapabilities()).rejects.toThrow('Request failed');
  });

  it('authenticates feature and OGC deletions',async()=>{
    api.setApiAccessToken('session-key');
    await api.deleteProjectFeature('a/b','feature?1');
    expect(last().url).toContain('/projects/a%2Fb/features/feature%3F1');
    expect(last().init?.method).toBe('DELETE');
    expect(last().headers.get('X-GeoFathom-API-Key')).toBe('session-key');
    await api.removeOGCSource('p','source','admin-key');
    expect(last().headers.get('X-GeoFathom-API-Key')).toBe('session-key');
    expect(last().headers.get('X-GeoFathom-Admin-Token')).toBe('admin-key');
  });

  it('passes revision fencing and paginated bounds without altering values',async()=>{
    await api.saveProjectCRS('p','EPSG:26917',true,17);
    expect(JSON.parse(String(last().init?.body))).toEqual({
      epsg:'EPSG:26917',grid_visible:true,expected_revision:17
    });
    await api.viewportFeatures('p',[-83,40,-82,41],150,300);
    const query=new URL(last().url).searchParams;
    expect(Object.fromEntries(query.entries())).toEqual({
      west:'-83',south:'40',east:'-82',north:'41',limit:'150',offset:'300'
    });
  });

  it('keeps normal and administrator credentials separate for background jobs',async()=>{
    api.setApiAccessToken('session-key');
    await api.queueGISJob('project','export_geojson',{layer_id:'one'},'admin-key');
    const req=last();
    expect(req.headers.get('X-GeoFathom-API-Key')).toBe('session-key');
    expect(req.headers.get('X-GeoFathom-Admin-Token')).toBe('admin-key');
    expect(JSON.parse(String(req.init?.body))).toEqual({kind:'export_geojson',payload:{layer_id:'one'}});
    await api.getGISJob('project','task',false);
    expect(new URL(last().url).searchParams.get('include_result')).toBe('false');
    await api.cancelGISJob('project','task');
    expect(last().init?.method).toBe('POST');
    expect(last().url).toContain('/jobs/task/cancel');
  });

  it('authenticates binary vector download and releases the object URL',async()=>{
    const link={href:'',download:'',click:vi.fn(),remove:vi.fn()};
    vi.stubGlobal('document',{createElement:()=>link,body:{appendChild:vi.fn()}});
    const create=vi.spyOn(URL,'createObjectURL').mockReturnValue('blob:test');
    const revoke=vi.spyOn(URL,'revokeObjectURL').mockImplementation(()=>{});
    try{
      api.setApiAccessToken('session-key');
      fetchMock.mockResolvedValueOnce(new Response('content',{
        headers:{'Content-Disposition':'attachment; filename="export.gpkg"'}
      }));
      await api.exportVectorFile('p','gpkg');
      expect(last().headers.get('X-GeoFathom-API-Key')).toBe('session-key');
      expect(link.download).toBe('export.gpkg');
      expect(link.click).toHaveBeenCalledOnce();
      expect(link.remove).toHaveBeenCalledOnce();
      expect(revoke).toHaveBeenCalledWith('blob:test');
    }finally{create.mockRestore();revoke.mockRestore();}
  });
});

describe('disk-backed scientific raster bridge',()=>{
 const fetchMock=vi.fn<typeof fetch>();
 beforeEach(()=>{fetchMock.mockReset();vi.stubGlobal('fetch',fetchMock);vi.stubGlobal('window',{sessionStorage:{getItem:()=> 'session-key'}});});
 afterEach(()=>vi.unstubAllGlobals());
 it('keeps existing inline data unchanged without downloading again',async()=>{
  const raster={name:'inline',data:'AQID',unit:'m'};
  expect(await api.materializeScientificRaster(raster)).toBe(raster);
  expect(fetchMock).not.toHaveBeenCalled();
 });
 it('authenticates and preserves the exact bytes across encoding chunk boundaries',async()=>{
  const raw=Uint8Array.from({length:65539},(_,i)=>i%251);
  fetchMock.mockResolvedValueOnce(new Response(raw,{headers:{'Content-Length':String(raw.length)}}));
  const result=await api.materializeScientificRaster({name:'disk',data:'',unit:'m',product_id:'abc/def'},100000);
  expect(Uint8Array.from(atob(result.data),c=>c.charCodeAt(0))).toEqual(raw);
  expect(result.unit).toBe('m');
  const [url,init]=fetchMock.mock.calls[0];expect(String(url)).toContain('/terrain/products/abc%2Fdef');
  expect(new Headers(init?.headers).get('X-GeoFathom-API-Key')).toBe('session-key');
 });
 it('rejects both known-length and streamed oversized rasters without truncating data',async()=>{
  fetchMock.mockResolvedValueOnce(new Response(new Uint8Array(8),{headers:{'Content-Length':'8'}}));
  fetchMock.mockResolvedValueOnce(new Response(new Uint8Array(8)));
  const raster={name:'disk',data:'',product_id:'abc'};
  await expect(api.materializeScientificRaster(raster,4)).rejects.toThrow('inline scientific input limit');
  await expect(api.materializeScientificRaster(raster,4)).rejects.toThrow('inline scientific input limit');
 });
 it('reports deleted disk products and empty responses rather than inventing pixels',async()=>{
  fetchMock.mockResolvedValueOnce(Response.json({detail:'Terrain product is unavailable.'},{status:404}));
  fetchMock.mockResolvedValueOnce(new Response(new Uint8Array(0)));
  const raster={name:'disk',data:'',product_id:'abc'};
  await expect(api.materializeScientificRaster(raster)).rejects.toThrow('Terrain product is unavailable.');
  await expect(api.materializeScientificRaster(raster)).rejects.toThrow('Raster product is empty');
 });
});
