import { useEffect, useState, type ChangeEvent } from 'react';
import { FileImage, MousePointer2, UploadCloud } from 'lucide-react';

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
}

export default function RasterPanel({
  asset, onSelect, tracing, onTracing, settings, onSettings, viewport,
}: Props) {
  const [assets, setAssets] = useState<RasterAsset[]>([]);
  const [token, setToken] = useState('');
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState('');
  const [catalogItems, setCatalogItems] = useState<StacItem[]>([]);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    listImagery().then(setAssets).catch(() => setError('Imagery library unavailable.'));
  }, []);

  async function importFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    event.target.value = '';
    if (!token) {
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
      <p className="project-hint">Use your own georeferenced GeoTIFF. The preview keeps its original geographic placement. Maximum upload: 64 MB.</p>
      <input type="password" autoComplete="off" aria-label="Image import administration token"
        placeholder="Server administration token" value={token}
        onChange={event => setToken(event.target.value)} />
      <label className="raster-upload">
        <UploadCloud size={15} /> {uploading ? 'Importing…' : 'Import GeoTIFF'}
        <input type="file" accept=".tif,.tiff,image/tiff" disabled={uploading}
          onChange={event => void importFile(event)} />
      </label>
      {assets.length > 0 && (
        <select aria-label="Select georeferenced imagery" value={asset?.id || ''}
          onChange={event => {
            const selected = assets.find(item => item.id === event.target.value);
            if (selected) onSelect(selected);
          }}>
          <option value="">Choose raster layer</option>
          {assets.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      )}
      {asset && (
        <>
          <div className="raster-details"><FileImage size={13}/><span>{asset.width} × {asset.height} px · {asset.crs}</span></div>
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
            <MousePointer2 size={15}/>
            {tracing ? 'Click your target on the map' : 'Start automatic outline'}
          </button>
          <p className="project-hint">The outline is an image-derived estimate, not a surveyed or legally verified boundary. Regions extending past the analysis window are flagged.</p>
        </>
      )}
      <div className="stac-search">
        <button type="button" onClick={() => void searchCatalog()} disabled={!viewport || searching}>
          {searching ? 'Searching catalog…' : 'Find public satellite scenes in map view'}
        </button>
        <p className="project-hint">Public STAC metadata only. Open a scene to inspect source and usage terms. Trace requires a georeferenced GeoTIFF imported above.</p>
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
    </div>
  );
}
