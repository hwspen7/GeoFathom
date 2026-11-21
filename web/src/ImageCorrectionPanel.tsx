import { MousePointerClick, ScanEye, Square, X } from 'lucide-react';
import type { Position } from './editing';

export type PromptMode='positive'|'negative'|'box'|null;

interface Props {
  enabled:boolean;
  mode:PromptMode;
  onMode:(value:PromptMode)=>void;
  positive:Position[];
  negative:Position[];
  box:Position[];
  busy:boolean;
  onClear:()=>void;
  onRefine:()=>void;
}

export default function ImageCorrectionPanel({
  enabled,mode,onMode,positive,negative,box,busy,onClear,onRefine,
}:Props) {
  return (
    <div className="image-review">
      <p className="project-hint">Refine an image-derived outline with SAM 2 positive/negative clicks or a bounding box. This requires optional local CUDA model installation.</p>
      <div className="survey-mode-grid">
        <button disabled={!enabled} className={mode==='positive'?'active':''}
          onClick={()=>onMode(mode==='positive'?null:'positive')}>
          <MousePointerClick size={14}/> Include (+)
        </button>
        <button disabled={!enabled} className={mode==='negative'?'active':''}
          onClick={()=>onMode(mode==='negative'?null:'negative')}>
          <X size={14}/> Exclude (−)
        </button>
        <button disabled={!enabled} className={mode==='box'?'active':''}
          onClick={()=>onMode(mode==='box'?null:'box')}>
          <Square size={14}/> Box
        </button>
      </div>
      <div className="raster-details">
        Positive: {positive.length} · Negative: {negative.length} · Box corners: {box.length}/2
      </div>
      <div className="survey-action-bar">
        <button disabled={!positive.length||busy||!enabled} onClick={onRefine}>
          <ScanEye size={14}/> Refine mask
        </button>
        <button disabled={busy} onClick={onClear}>Clear prompts</button>
      </div>
      <p className="project-hint">After refining, use the vertex editor to inspect and correct the polygon. A segmentation result is not a surveyed boundary.</p>
    </div>
  );
}
