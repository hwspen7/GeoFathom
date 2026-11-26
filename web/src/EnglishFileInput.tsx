import {useState,type ComponentProps} from 'react';

export default function EnglishFileInput({onChange,style,className,...props}:ComponentProps<'input'>){
 const [name,setName]=useState('');
 const displayName=props.value===''?'':name;
 return <span className="english-file-input">
   <span className="english-file-button" aria-hidden="true" data-caption={props.multiple?'Choose files':'Choose file'}/>
   <span className="english-file-name" aria-hidden="true" title={displayName} data-caption={displayName||'No file selected'}/>
   <input {...props} type="file" lang="en" style={style} className={className} onChange={e=>{
     const files=Array.from(e.currentTarget.files??[]);
     onChange?.(e);
     setName(e.currentTarget.files?.length?files.map(f=>f.name).join(', '):'');
   }}/>
 </span>;
}
