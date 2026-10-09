import {useEffect, useRef, useState} from 'react';
import {ExternalLink, Maximize2, Minimize2, RotateCw, Smartphone} from 'lucide-react';
import {safeReceiptHref} from './neyviaRunActivity.js';
import './neyviaDevicePreview.css';

export function NeyviaDevicePreview({url = '', appName = 'Your app', running = false, onStart, starting = false, onOpenUrl}) {
  const [landscape, setLandscape] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [revision, setRevision] = useState(0);
  const [loaded, setLoaded] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [address, setAddress] = useState('');
  const [error, setError] = useState('');
  const [scale, setScale] = useState(1);
  const screen = useRef(null);
  useEffect(() => {
    const element=screen.current;
    if (!element) return;
    const observer=new ResizeObserver(() => setScale(element.clientWidth/(landscape?780:390)));
    observer.observe(element);
    return () => observer.disconnect();
  }, [landscape]);
  const href = running ? safeReceiptHref(url) : '';
  useEffect(() => setLoaded(false), [href, revision]);
  useEffect(() => {
    if (!expanded) return;
    const close = event => {if (event.key === 'Escape') setExpanded(false);};
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, [expanded]);
  return <section className="neyvia-device-preview" data-device-preview="true" data-expanded={expanded} aria-label={`${appName} device preview`}>
    <header className="neyvia-device-toolbar">
      <Smartphone aria-hidden="true" size={17}/><div><strong>{appName}</strong><span>{href ? 'Web preview' : 'Device preview'}</span></div>
      <div className="neyvia-device-toolbar-actions">
        {onOpenUrl && <button type="button" className="neyvia-device-connect" aria-label="Connect a running app" aria-expanded={connecting} onClick={() => setConnecting(value => !value)}>Connect app</button>}
        <button type="button" aria-label={landscape ? 'Use portrait orientation' : 'Use landscape orientation'} onClick={() => setLandscape(value => !value)}><RotateCw size={16}/></button>
        <button type="button" aria-label={expanded ? 'Restore device preview' : 'Expand device preview'} aria-pressed={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? <Minimize2 size={16}/> : <Maximize2 size={16}/>}</button>
        {href && <a href={href} target="_blank" rel="noreferrer" aria-label="Open app in a new tab"><ExternalLink size={16}/></a>}
      </div>
    </header>
    {connecting && <form className="neyvia-device-connect-form" onSubmit={event => {event.preventDefault(); const target=safeReceiptHref(address); if (!/^https?:\/\//i.test(target)) {setError('Enter an http or https address.');return;} onOpenUrl?.(target);setConnecting(false);setError('');}}><label>Running app URL<input type="url" placeholder="http://localhost:3000" value={address} onChange={event=>setAddress(event.target.value)} required autoFocus/></label><button type="submit">Open app</button>{error && <span role="alert">{error}</span>}</form>}
    <div className="neyvia-device-stage">
      <div className="neyvia-device-frame" data-orientation={landscape ? 'landscape' : 'portrait'}>
        <div className="neyvia-device-camera" aria-hidden="true"/>
        <div className="neyvia-device-screen" ref={screen}>{href ? <iframe key={`${href}:${revision}`} src={href} title={`${appName} interactive web preview`} onLoad={() => setLoaded(true)} style={{width:landscape?780:390,height:landscape?390:780,transform:`scale(${scale})`}}/> : <div className="neyvia-device-empty"><Smartphone size={32}/><strong>Your app, in hand.</strong><p>{onStart ? 'Start the preview to use your app here.' : 'Open or create a mobile app to start.'}</p>{onStart && <button type="button" disabled={starting} onClick={onStart}>{starting ? 'Starting…' : 'Start preview'}</button>}</div>}</div>
        <span className="neyvia-device-home" aria-hidden="true"/>
      </div>
    </div>
    <footer><span>{href ? loaded ? 'Interact directly with the app.' : 'Loading app…' : 'Portrait and landscape views'}</span>{href && <button type="button" onClick={() => setRevision(value => value + 1)}>Reload app</button>}</footer>
  </section>;
}
