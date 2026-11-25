import {ChevronRight} from 'lucide-react';

interface Props{
 label:string;
 disabled?:boolean;
 onOpen:()=>void;
}

// Shared entry for scientific workbenches. Detailed controls live in the
// existing dialogs; the Operations dock has a single primary launch action.
export default function ScienceLaunch({label,disabled=false,onOpen}:Props){
 return <div className="science-launch">
  <button type="button" className="science-launch-button" disabled={disabled}
   aria-haspopup="dialog" onClick={onOpen} title={disabled?'Connect to the API':label}>
   <span>{label}</span><ChevronRight size={15} aria-hidden="true"/>
  </button>
 </div>;
}
