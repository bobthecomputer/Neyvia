// Shared user/agent store. Both surfaces execute the same checked reducer.
export async function createApp({initial, reducer, actions, render, storage}) {
  // Opaque preview frames can deny storage before the first method call.
  // The shared host remains authoritative; a device export still needs storage.
  if (storage === undefined) {
    try { storage = globalThis.localStorage; } catch { storage = null; }
  }
  let saved;
  try { saved = JSON.parse(storage.getItem('neyvia-app-state')); } catch { saved = null; }
  let state = saved && Number.isInteger(saved.count) && saved.count >= 0 ? saved : {...initial, revision: 0};
  let transport = 'shared-host';
  const request = async (path, body) => {
    if (window.__neyviaPreviewRequest) {
      const response = await window.__neyviaPreviewRequest(path, body);
      if (response.status !== 200 || response.value?.ok === false) throw new Error(response.value?.error || 'Preview state transport failed');
      return response.value;
    }
    const response = await fetch('./__neyvia/'+path, body === undefined ? {cache:'no-store'} : {method:'POST',headers:{'Content-Type':'application/json','X-Neyvia-App':'1'},body:JSON.stringify(body)});
    if(response.status===404){const error=new Error('Static device export');error.deviceExport=true;throw error;}
    const value = await response.json();
    if (!response.ok || value.ok === false) throw new Error(value.error || 'State transport failed');
    return value;
  };
  try {state = await request('state');}
  catch(error) {
    // Static native exports and offline PWA launches have no Python host.
    // This mode is visible to the user and in every agent observation/receipt.
    if(!(error instanceof TypeError) && !error.deviceExport)throw error;
    transport='device-local';
  }
  const identityResponse=window.__neyviaPreviewRequest ? await window.__neyviaPreviewRequest('identity') : await fetch('./identity.json',{cache:'no-store'});
  if(identityResponse.status!==200)throw new Error('App identity is missing');
  const identity=window.__neyviaPreviewRequest ? identityResponse.value : await identityResponse.json();
  let wakeFollow=()=>{};
  const copy = () => structuredClone(state);
  const api = {
    state: copy,
    describe: () => ({version: '1.1', instance:identity.instance, transport, actions, state: copy()}),
    async act(name, args = {}, options = {}) {
      if (!actions.includes(name)) throw new Error('Unknown action: ' + name);
      const fingerprint = JSON.stringify([name,args]);
      if(transport==='shared-host')state = await request('state');
      if (options.expectedRevision !== undefined && options.expectedRevision !== state.revision) throw new Error('State changed; observe again');
      const before = copy(), candidate = reducer(before, name, args);
      if (!Number.isInteger(candidate.count) || candidate.count < 0) throw new Error('Count invariant failed');
      const receipt = transport==='shared-host' ? await request('commit',{state:candidate,expectedRevision:state.revision,actionId:options.actionId,fingerprint}) : {ok:true,before,after:{...candidate,revision:before.revision+1},checks:['nonnegative','device-persisted'],transport};
      state = receipt.after;
      try { storage.setItem('neyvia-app-state', JSON.stringify(state)); }
      catch (error) {
        if(transport==='device-local'){state=before;throw new Error('Persistence failed: '+error.message);}
        receipt.cacheStored=false; // The host commit remains authoritative.
      }
      render(copy());
      wakeFollow();
      return receipt;
    }
  };
  render(copy());
  window.neyviaApp = Object.freeze(api);
  if(transport==='shared-host'){
    // Follow the shared host: 500 ms while it changes, backing off to 5 s when it is quiet, nothing while hidden.
    let gap=500,timer=null,busy=false;
    const follow=async()=>{timer=null;if(document.hidden||busy)return;busy=true;
      try{const next=await request('state');if(next.revision!==state.revision){state=next;render(copy());gap=500;}else gap=Math.min(5000,Math.round(gap*1.5));}catch{gap=Math.min(5000,Math.round(gap*1.5));}
      finally{busy=false;timer=setTimeout(follow,gap);}};
    document.addEventListener('visibilitychange',()=>{if(!document.hidden&&!busy){clearTimeout(timer);gap=500;follow();}});
    wakeFollow=()=>{clearTimeout(timer);gap=500;follow();};
    timer=setTimeout(follow,gap);
  }
  window.dispatchEvent(new Event('neyvia-app-ready'));
  return api;
}
