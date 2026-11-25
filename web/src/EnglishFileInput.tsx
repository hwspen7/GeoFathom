import {useState,type ComponentProps} from 'react';

export default function EnglishFileInput({onChange,style,className,...props}:ComponentProps<'input'>){
 const [name,setName]=useState('');
 return <span className="english-file-input">
   <span className="english-file-button" aria-hidden="true">{props.multiple?'Choose files':'Choose file'}</span>
   <span className="english-file-name" aria-hidden="true" title={name}>{name||'No file selected'}</span>
   <input {...props} type="file" lang="en" style={style} className={className} onChange={e=>{
     const files=Array.from(e.currentTarget.files??[]);
     setName(files.map(f=>f.name).join(', '));
     onChange?.(e);
   }}/>
 </span>;
}
