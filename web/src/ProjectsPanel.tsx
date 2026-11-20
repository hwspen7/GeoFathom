import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import {
  Copy, Download, Eye, EyeOff, FolderOpen, History, Layers3, Lock,
  LockOpen, Plus, RotateCcw, Save,
} from 'lucide-react';

import {
  copyProjectFeature, createLayer, exportProject, getFeatureHistory, getProjects,
  getWorkspace, newProject, patchLayer, restoreFeature, saveProjectFeature,
  updateProjectFeature, type GeoLayer, type GeoWorkspace, type Project,
  type WorkspaceFeature, type FeatureHistory,
} from './api';

interface Props {
  geometry: GeoJSON.Geometry | null;
  featureName: string;
  featureSource: string;
  featureProperties: Record<string, unknown>;
  selectedFeatureId: string | null;
  splitParts: GeoJSON.Geometry[];
  refreshToken: number;
  onOpen: (feature: WorkspaceFeature) => void;
  onWorkspace: (workspace: GeoWorkspace | null, projectId: string | null) => void;
}

export default function ProjectsPanel({
  geometry, featureName, featureSource, featureProperties, selectedFeatureId,
  splitParts, refreshToken, onOpen, onWorkspace,
}: Props) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selected, setSelected] = useState('');
  const [workspace, setWorkspace] = useState<GeoWorkspace | null>(null);
  const [layerId, setLayerId] = useState('');
  const [draftName, setDraftName] = useState('');
  const [layerName, setLayerName] = useState('');
  const [history, setHistory] = useState<FeatureHistory | null>(null);
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');
  const [busy, setBusy] = useState(false);
  const notify = useRef(onWorkspace);
  notify.current = onWorkspace;

  useEffect(() => {
    getProjects().then(list => {
      setProjects(list);
      setSelected(current => list.find(p => p.id === current) ? current : (list[0]?.id ?? ''));
    }).catch(() => setError('Cannot load saved projects.'));
  }, []);

  const reload = useCallback(async (projectId: string): Promise<GeoWorkspace> => {
    const result = await getWorkspace(projectId);
    setWorkspace(result);
    setLayerId(id => result.layers.some(l => l.id === id) ? id : (result.layers[0]?.id ?? ''));
    return result;
  }, []);

  useEffect(() => {
    if (!selected) { setWorkspace(null); return; }
    reload(selected).catch(() => setError('Cannot load project layers.'));
  }, [selected, reload, refreshToken]);

  useEffect(() => { notify.current(workspace, selected || null); }, [workspace, selected]);

  useEffect(() => {
    if (!selected || !selectedFeatureId) {
      setHistory(null);
      return;
    }
    getFeatureHistory(selected, selectedFeatureId)
      .then(setHistory).catch(() => setHistory(null));
  }, [selected, selectedFeatureId, refreshToken]);

  const activeLayer = workspace?.layers.find(l => l.id === layerId);
  const current = workspace?.features.find(f => f.id === selectedFeatureId);
  const locked = Boolean(current &&
    workspace?.layers.find(l => l.id === current.layer_id)?.locked);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draftName.trim()) return;
    setBusy(true); setError('');
    try {
      const created = await newProject(draftName.trim());
      setProjects(await getProjects());
      setSelected(created.id);
      setWorkspace(null);
      setDraftName('');
      setInfo('Project created.');
    } catch (cause) { setError(String(cause)); }
    finally { setBusy(false); }
  }

  async function run(action: () => Promise<void>) {
    setBusy(true); setError(''); setInfo('');
    try { await action(); if (selected) await reload(selected); }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Operation failed.'); }
    finally { setBusy(false); }
  }

  async function save() {
    if (!selected || !geometry) return;
    await run(async () => {
      if (current) {
        const saved = await updateProjectFeature(selected, current.id, {
          geometry, properties: featureProperties,
          expected_revision: current.revision,
        });
        onOpen(saved);
        setInfo('Existing feature updated with a new revision.');
      } else {
        if (activeLayer?.locked) throw new Error('Unlock the target layer before saving.');
        const saved = await saveProjectFeature(
          selected, featureName, geometry, featureSource, featureProperties, layerId || undefined,
        );
        const latest = await getWorkspace(selected);
        const opened = latest.features.find(item => item.id === saved.id);
        if (opened) onOpen(opened);
        setInfo('New geometry saved to the chosen layer.');
      }
    });
  }

  async function saveSplit() {
    if (!selected || splitParts.length < 2) return;
    await run(async () => {
      for (const [index, part] of splitParts.entries()) {
        await saveProjectFeature(
          selected, featureName + ' – part ' + (index + 1), part,
          featureSource, { ...featureProperties, operation: 'split' }, layerId || undefined,
        );
      }
      setInfo('Split polygons saved as independent features.');
    });
  }

  async function exportJson() {
    if (!selected) return;
    try {
      const collection = await exportProject(selected);
      const blob = new Blob([JSON.stringify(collection, null, 2)], {
        type: 'application/geo+json',
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = 'geofathom-project.geojson';
      document.body.append(link); link.click(); link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) { setError(String(cause)); }
  }

  async function addNewLayer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || !layerName.trim()) return;
    await run(async () => {
      const created = await createLayer(selected, layerName.trim(), '#2563eb');
      setLayerId(created.id);
      setLayerName('');
      setInfo('New layer added.');
    });
  }

  async function changeLayer(layer: GeoLayer, update: Partial<{
    name: string; color: string; visible: boolean; locked: boolean; z_index: number;
  }>) {
    if (!selected) return;
    await run(async () => { await patchLayer(selected, layer.id, update); });
  }

  async function duplicate() {
    if (!selected || !current || locked) return;
    await run(async () => {
      const created = await copyProjectFeature(selected, current.id);
      const result = await getWorkspace(selected);
      const feature = result.features.find(f => f.id === created.id);
      if (feature) onOpen(feature);
      setInfo('Feature duplicated.');
    });
  }

  async function restore(revision: number) {
    if (!selected || !current || locked) return;
    await run(async () => {
      const restored = await restoreFeature(selected, current.id, revision);
      onOpen(restored);
      setInfo('A new revision was created from the selected version.');
    });
  }

  return (
    <div className="project-panel">
      <form onSubmit={create} className="project-create">
        <input aria-label="New project name" placeholder="New project name" maxLength={150}
          value={draftName} onChange={event => setDraftName(event.target.value)} />
        <button aria-label="Create project" type="submit" disabled={busy || !draftName.trim()}>
          <Plus size={16} />
        </button>
      </form>
      {projects.length > 0 && (
        <>
          <select aria-label="Active project" value={selected}
            onChange={event => { setSelected(event.target.value); setWorkspace(null); }}>
            {projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
          </select>

          <div className="layer-header"><Layers3 size={14} /> Layers</div>
          {workspace?.layers.map(layer => (
            <div key={layer.id} className="layer-row">
              <button aria-label={layer.visible ? 'Hide layer' : 'Show layer'}
                title={layer.visible ? 'Hide layer' : 'Show layer'}
                onClick={() => void changeLayer(layer, { visible: !layer.visible })}>
                {layer.visible ? <Eye size={14} /> : <EyeOff size={14} />}
              </button>
              <input aria-label={'Color of ' + layer.name} type="color" value={layer.color}
                onChange={event => void changeLayer(layer, { color: event.target.value })} />
              <button className={layerId === layer.id ? 'layer-name active' : 'layer-name'}
                onClick={() => setLayerId(layer.id)}>{layer.name}</button>
              <button aria-label={layer.locked ? 'Unlock layer' : 'Lock layer'}
                onClick={() => void changeLayer(layer, { locked: !layer.locked })}>
                {layer.locked ? <Lock size={14} /> : <LockOpen size={14} />}
              </button>
              <button aria-label="Move layer higher"
                onClick={() => void changeLayer(layer, { z_index: layer.z_index + 2 })}>↑</button>
              <button aria-label="Move layer lower"
                onClick={() => void changeLayer(layer, { z_index: layer.z_index - 2 })}>↓</button>
            </div>
          ))}
          <form className="project-create" onSubmit={addNewLayer}>
            <input aria-label="New layer name" placeholder="Add map layer" value={layerName}
              onChange={event => setLayerName(event.target.value)} maxLength={100}/>
            <button type="submit" disabled={busy || !layerName.trim()}><Plus size={14}/></button>
          </form>
          <div className="project-actions">
            <button onClick={() => void save()} disabled={busy || !geometry || locked || Boolean(!current && activeLayer?.locked)}>
              <Save size={14}/> {current ? 'Update feature' : 'Save selected'}
            </button>
            <button onClick={() => void exportJson()} disabled={busy}>
              <Download size={14}/> Export
            </button>
          </div>
          {splitParts.length > 1 && (
            <button className="project-split-save" disabled={busy || Boolean(activeLayer?.locked)}
              onClick={() => void saveSplit()}>Save all {splitParts.length} split pieces</button>
          )}

          <div className="project-features">
            {workspace?.features.map(item => {
              const layer = workspace.layers.find(l => l.id === item.layer_id);
              return (
                <button key={item.id} disabled={!layer?.visible} onClick={() => onOpen(item)}
                  className={selectedFeatureId === item.id ? 'active' : ''}>
                  <FolderOpen size={14}/><span>{item.name}</span><small>r{item.revision}</small>
                </button>
              );
            })}
            {!workspace?.features.length && <p className="project-hint">No saved features yet.</p>}
          </div>

          {current && (
            <>
              <div className="project-actions">
                <button onClick={() => void duplicate()} disabled={busy || locked}>
                  <Copy size={13}/> Duplicate
                </button>
                <button onClick={() => {
                  if (history) setHistory(null);
                  else if (selected) void getFeatureHistory(selected, current.id).then(setHistory);
                }}><History size={13}/> Versions</button>
              </div>
              {history && (
                <div className="version-list">
                  {history.versions.map(item => (
                    <button key={item.revision} onClick={() => void restore(item.revision)}
                      disabled={busy || locked || item.revision === history.current_revision}>
                      <RotateCcw size={12}/>
                      Revision {item.revision} · {new Date(item.created_at).toLocaleString()}
                      {item.measurement?.area_m2 != null ? ' · ' + item.measurement.area_m2.toFixed(2) + ' m²' : ''}
                    </button>
                  ))}
                </div>
              )}
            </>
          )}
        </>
      )}
      {!projects.length && <p className="project-hint">Create a project to keep geometry and layer history.</p>}
      {info && <p className="project-info">{info}</p>}
      {error && <p className="discovery-error">{error}</p>}
    </div>
  );
}
