import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Download, FolderOpen, Plus, Save } from 'lucide-react';

import {
  exportProject, getProjectFeatures, getProjects, newProject, saveProjectFeature,
  type Project, type StoredFeature,
} from './api';

interface Props {
  geometry: GeoJSON.Geometry | null;
  featureName: string;
  featureSource: string;
  onOpen: (feature: StoredFeature) => void;
}

export default function ProjectsPanel({ geometry, featureName, featureSource, onOpen }: Props) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selected, setSelected] = useState('');
  const [features, setFeatures] = useState<StoredFeature[]>([]);
  const [draftName, setDraftName] = useState('');
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');
  const [working, setWorking] = useState(false);

  const refresh = useCallback(async () => {
    const list = await getProjects();
    setProjects(list);
    setSelected(current => (list.some(project => project.id === current) ? current : list[0]?.id || ''));
  }, []);

  useEffect(() => {
    refresh().catch(() => setError('Could not load projects.'));
  }, [refresh]);

  useEffect(() => {
    if (!selected) {
      setFeatures([]);
      return;
    }
    let active = true;
    getProjectFeatures(selected)
      .then(items => { if (active) setFeatures(items); })
      .catch(() => { if (active) setError('Could not load saved features.'); });
    return () => { active = false; };
  }, [selected]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draftName.trim()) return;
    setWorking(true);
    setError('');
    try {
      const project = await newProject(draftName.trim());
      await refresh();
      setSelected(project.id);
      setDraftName('');
      setInfo('Project created.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not create project.');
    } finally {
      setWorking(false);
    }
  }

  async function save() {
    if (!selected || !geometry) return;
    setWorking(true);
    setError('');
    try {
      await saveProjectFeature(selected, featureName, geometry, featureSource);
      setFeatures(await getProjectFeatures(selected));
      setInfo('Geographic feature saved to this project.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save feature.');
    } finally {
      setWorking(false);
    }
  }

  async function download() {
    if (!selected) return;
    try {
      const collection = await exportProject(selected);
      const blob = new Blob([JSON.stringify(collection, null, 2)], { type: 'application/geo+json' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'geofathom-project.geojson';
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not export project.');
    }
  }

  return (
    <div className="project-panel">
      <form onSubmit={create} className="project-create">
        <input aria-label="New project name" placeholder="New project name" maxLength={150} value={draftName} onChange={event => setDraftName(event.target.value)} />
        <button aria-label="Create project" type="submit" disabled={working || !draftName.trim()}><Plus size={16}/></button>
      </form>
      {projects.length > 0 && (
        <>
          <select aria-label="Active project" value={selected} onChange={event => { setSelected(event.target.value); setInfo(''); }}>
            {projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
          </select>
          <div className="project-actions">
            <button onClick={() => void save()} disabled={working || !geometry}><Save size={14}/> Save selected</button>
            <button onClick={() => void download()} disabled={working}><Download size={14}/> Export</button>
          </div>
          {features.length > 0 && (
            <div className="project-features">
              {features.map(item => <button key={item.id} onClick={() => onOpen(item)}><FolderOpen size={14}/><span>{item.name}</span></button>)}
            </div>
          )}
          {features.length === 0 && <p className="project-hint">No saved features yet.</p>}
        </>
      )}
      {projects.length === 0 && <p className="project-hint">Create a project to keep boundaries between sessions.</p>}
      {info && <p className="project-info">{info}</p>}
      {error && <p className="discovery-error">{error}</p>}
    </div>
  );
}
