// Build the actual AgentLive component in a disposable owned pane fixture.
import fs from 'node:fs';
import path from 'node:path';
import { build } from 'vite';
import react from '@vitejs/plugin-react';
const root=path.resolve('.agent_control/C2h/pane-source');fs.mkdirSync(root,{recursive:true});
fs.writeFileSync(path.join(root,'index.html'),'<!doctype html><html><head><title>Neyvia owner handoff proof</title></head><body class="nx" data-theme="forest" style="margin:0"><div id="root" style="height:100vh;display:flex;flex-direction:column"></div><script type="module" src="/main.jsx"></script></body></html>');
fs.writeFileSync(path.join(root,'main.jsx'),`import React,{useEffect,useState} from 'react';import{createRoot}from'react-dom/client';import{AgentLive}from'../../../web/src/neyvia/next/NxBrowserParts.jsx';import'../../../web/src/neyvia/next/nxBrowser.css';import{browserCall}from'../../../web/src/neyvia/next/nxBrowserApi.js';
function Pane(){const[state,setState]=useState(null);useEffect(()=>{let live=true;const tick=async()=>{const s=await browserCall('state');if(live)setState(s)};void tick();const t=setInterval(tick,500);return()=>{live=false;clearInterval(t)}} ,[]);const id=new URLSearchParams(location.search).get('tab');const tab=state?.tabs.find(t=>t.id===id);return tab?<AgentLive tab={tab} sessionId={state.headless.sessionId}/>:<p>Waiting for retained tab</p>}createRoot(document.getElementById('root')).render(<Pane/>);`);
fs.appendFileSync(path.join(root,'main.jsx'),"import '../../../web/src/neyvia/next/nxTokens.css';import '../../../web/src/neyvia/next/nxThemes.css';import '../../../web/src/neyvia/next/nxShell.css';");
await build({configFile:false,root,plugins:[react()],cacheDir:path.resolve('.agent_control/C2h/pane-cache'),build:{outDir:path.resolve('.agent_control/C2h/pane-dist'),emptyOutDir:false},define:{'process.env.NODE_ENV':'"production"'}});
