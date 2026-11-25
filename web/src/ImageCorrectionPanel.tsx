import { MousePointerClick, ScanEye, Frame, X } from 'lucide-react';
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
      <div className="section-heading" title="Requires a georeferenced image and optional installed SAM 2 model">SAM 2 refinement</div>
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
          <Frame size={14}/> Box
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
      {enabled&&<small className="compact-notice" title="A segmentation result is not a surveyed boundary.">Review extracted boundary</small>}
    </div>
  );
}
