import {useState, type FormEvent} from 'react';
import {setApiAccessToken} from './api';

/** Session-only operator credential; never embeds server tokens in bundles. */
export default function ApiAccessPanel(){
  const [token,setToken]=useState('');
  const [saved,setSaved]=useState(()=>{
    try{return Boolean(window.sessionStorage.getItem('geofathom-api-token'));}
    catch{return false;}
  });
  function apply(event:FormEvent<HTMLFormElement>){
    event.preventDefault();
    setApiAccessToken(token.trim());
    setSaved(Boolean(token.trim()));
    setToken('');
    window.location.reload();
  }
  function clear(){
    setApiAccessToken('');
    setToken('');
    setSaved(false);
    window.location.reload();
  }
  return <details className="panel-section">
    <summary>Server access {saved?'· session unlocked':'· local mode'}</summary>
    <p className="project-hint">Only needed when your server requires an API
      key. Credentials remain in this browser tab's session storage.</p>
    <form onSubmit={apply}>
      <label>API access key
        <input type="password" autoComplete="off"
          aria-label="Server API access key"
          value={token} onChange={e=>setToken(e.target.value)}/>
      </label>
      <button type="submit" disabled={!token.trim()}>Use key</button>
      {saved&&<button type="button" onClick={clear}>Clear key</button>}
    </form>
  </details>;
}
