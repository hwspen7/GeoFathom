import EnglishFileInput from './EnglishFileInput';
import { useEffect, useState, type ChangeEvent } from 'react';
import { Crosshair, UploadCloud } from 'lucide-react';
import {createPortal} from 'react-dom';
import {SectionIcon} from './SectionIcon';

import {
  listImagery, searchPublicImagery, uploadImagery, type RasterAsset, type StacItem,
} from './api';

export interface TraceSettings {
  method: 'color' | 'sam2';
  tolerance: number;
  window_size: number;
}

interface Props {
  asset: RasterAsset | null;
  onSelect: (asset: RasterAsset) => void;
  tracing: boolean;
  onTracing: (value: boolean) => void;
  settings: TraceSettings;
  onSettings: (value: TraceSettings) => void;
  viewport: [number, number, number, number] | null;
  localImport?:boolean;
  refreshToken?:number;
  resultsTarget?:HTMLElement|null;
}

export default function RasterPanel({
  asset, onSelect, tracing, onTracing, settings, onSettings, viewport,localImport=false,refreshToken=0,resultsTarget,
}: Props) {
  const [assets, setAssets] = useState<RasterAsset[]>([]);
  const [token, setToken] = useState('');
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [catalogItems, setCatalogItems] = useState<StacItem[]>([]);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    let active=true;
    listImagery().then(value=>{if(active){setAssets(value);setError('');}}).catch(cause=>{if(active)setError(cause instanceof Error?cause.message:'Imagery library unavailable.');});
    return()=>{active=false;};
  }, [refreshToken]);

  async function importFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    event.target.value = '';
    if (!token && !localImport) {
      setError('Enter the server administration token to import a GeoTIFF.');
      return;
    }
    setUploading(true);
    setError('');
    try {
      const imported = await uploadImagery(file, token);
      setAssets(current => [imported, ...current]);
      onSelect(imported);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Raster import failed.');
    } finally {
      setUploading(false);
    }
  }

  async function searchCatalog() {
    if (!viewport) return;
    setError('');
    setSearching(true);
    try {
      const result = await searchPublicImagery(viewport);
      setCatalogItems(result.items);
      if (result.items.length === 0) setError('No catalog scenes found. Adjust map bounds or date.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Public catalog search failed.');
    } finally {
      setSearching(false);
    }
  }

  return (
    <div className="raster-panel">
      {!localImport&&<details open={!localImport} className="access-settings"><summary>Import access</summary>
      <input type="password" autoComplete="off" aria-label="Image import administration token"
        placeholder="Server administration token" value={token}
        onChange={event => setToken(event.target.value)} /></details>}
      <label className="raster-file-control" title="Import a georeferenced GeoTIFF, up to 64 MB">
        <span><UploadCloud size={14} /> {uploading ? 'Importing…' : 'Import GeoTIFF'}</span>
        <EnglishFileInput type="file" accept=".tif,.tiff,image/tiff" disabled={uploading}
          onChange={event => void importFile(event)} />
      </label>
      {(
        <select disabled={!assets.length} aria-label="Select georeferenced imagery" value={asset?.id || ''}
          onChange={event => {
            const selected = assets.find(item => item.id === event.target.value);
            if (selected) onSelect(selected);
          }}>
          <option value="">{assets.length?'Choose raster layer':'No raster layers'}</option>
          {[...assets,...(asset&&!assets.some(a=>a.id===asset.id)?[asset]:[])].map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      )}
      {asset && (
        <>
          <h4 className="unified-tool-heading"><SectionIcon role="geometry" size={13}/> Outline</h4>
          <div className="area-fields">
            <div>
              <label htmlFor="trace-provider">Outline method</label>
              <select id="trace-provider" value={settings.method}
                onChange={event => onSettings({ ...settings, method: event.target.value as 'color' | 'sam2' })}>
                <option value="color">C++ color region</option>
                <option value="sam2">SAM 2 (if installed)</option>
              </select>
            </div>
            <div>
              <label htmlFor="trace-window">Window size</label>
              <select id="trace-window" value={settings.window_size}
                onChange={event => onSettings({ ...settings, window_size: Number(event.target.value) })}>
                <option value={256}>256 px</option>
                <option value={512}>512 px</option>
                <option value={1024}>1024 px</option>
              </select>
            </div>
          </div>
          {settings.method === 'color' && (
            <label className="trace-tolerance" htmlFor="trace-tolerance">
              RGB tolerance: {settings.tolerance}
              <input id="trace-tolerance" type="range" min="0" max="80" step="2"
                value={settings.tolerance}
                onChange={event => onSettings({ ...settings, tolerance: Number(event.target.value) })} />
            </label>
          )}
          <button className={tracing ? 'trace-toggle active' : 'trace-toggle'}
            onClick={() => onTracing(!tracing)}>
            <Crosshair size={15}/>
            {tracing ? 'Click your target on the map' : 'Start automatic outline'}
          </button>
          {tracing&&<small className="compact-notice">Review the extracted outline before saving.</small>}
        </>
      )}
      <div className="stac-search"><h4 className="unified-tool-heading"><SectionIcon role="imagerySources" size={13}/> Catalog</h4>
        <button title="Find public STAC scene metadata; not an imported raster" type="button" onClick={() => void searchCatalog()} disabled={!viewport || searching}>
          {searching ? 'Searching catalog…' : 'Find public satellite scenes in map view'}
        </button>
         {catalogItems.length > 0 && (
          <div className="stac-results">
            {catalogItems.map(item => (
              <div key={item.id} className="stac-item">
                <span>{item.datetime ? new Date(item.datetime).toLocaleDateString() : 'Date unknown'} · Cloud {item.cloud_cover ?? '—'}%</span>
                {item.catalog_url && <a href={item.catalog_url} target="_blank" rel="noopener noreferrer">Catalog item</a>}
              </div>
            ))}
          </div>
        )}
      </div>
      {error && <p className="discovery-error">{error}</p>}
      {asset&&resultsTarget&&createPortal(<section className="panel-section unified-result-summary" aria-label="Raster results"><div className="section-heading"><SectionIcon role="imagery" size={14}/> Raster</div><strong className="unified-result-name">{asset.name}</strong><div className="data-metric-band"><div><small>Width</small><strong>{asset.width.toLocaleString('en-US')} px</strong></div><div><small>Height</small><strong>{asset.height.toLocaleString('en-US')} px</strong></div><div><small>CRS</small><strong>{asset.crs}</strong></div><div><small>Pixels</small><strong>{(asset.width*asset.height).toLocaleString('en-US')}</strong></div></div></section>,resultsTarget)}
    </div>
  );
}
