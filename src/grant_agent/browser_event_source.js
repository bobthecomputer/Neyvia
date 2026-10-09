/* Normal anonymous EventSource transport, using the engine's routed fetch stream. */
globalThis.EventSource = class EventSource extends EventTarget {
  static CONNECTING=0;static OPEN=1;static CLOSED=2;
  CONNECTING=0;OPEN=1;CLOSED=2;
  constructor(url, options={}){
    super();this.url=new URL(String(url),location.href).href;this.withCredentials=!!options.withCredentials;
    this.readyState=0;this.onopen=null;this.onerror=null;this.onmessage=null;this._lastId='';this._retry=3000;
    this._connect();
  }
  _emit(type,init={}){const event=type==='open'||type==='error'?new Event(type):new MessageEvent(type,init);this.dispatchEvent(event);const handler=this['on'+type];if(typeof handler==='function')handler.call(this,event);}
  async _connect(){
    if(this.readyState===2)return;
    this._abort=new AbortController();
    try{
      const headers={Accept:'text/event-stream'};if(this._lastId)headers['Last-Event-ID']=this._lastId;
      const response=await fetch(this.url,{headers,credentials:this.withCredentials?'include':'same-origin',signal:this._abort.signal});
      if(response.status===204){this.close();return;}
      if(response.status!==200||!/^text\/event-stream(?:;|$)/i.test(response.headers.get('content-type')||''))throw Error('Invalid event stream response');
      this.readyState=1;this._emit('open');
      const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='',data=[],type='message';
      const line=value=>{
        if(value===''){if(data.length)this._emit(type,{data:data.join('\n'),lastEventId:this._lastId,origin:new URL(this.url).origin});data=[];type='message';return;}
        if(value.startsWith(':'))return;
        const colon=value.indexOf(':'),field=colon<0?value:value.slice(0,colon);let text=colon<0?'':value.slice(colon+1);if(text.startsWith(' '))text=text.slice(1);
        if(field==='data')data.push(text);else if(field==='event')type=text||'message';else if(field==='id'&&!text.includes('\0'))this._lastId=text;else if(field==='retry'&&/^\d+$/.test(text))this._retry=Math.max(1000,Number(text));
      };
      while(this.readyState!==2){const chunk=await reader.read();if(chunk.done)break;buffer+=decoder.decode(chunk.value,{stream:true});let match;while((match=/\r\n|\r|\n/.exec(buffer))){if(match[0]==='\r'&&match.index===buffer.length-1)break;line(buffer.slice(0,match.index));buffer=buffer.slice(match.index+match[0].length);}if(buffer.length>1048576)throw Error('Event line exceeds limit');}
      reader.releaseLock();
    }catch(error){if(this.readyState===2)return;}
    if(this.readyState!==2){this.readyState=0;this._emit('error');this._timer=setTimeout(()=>this._connect(),this._retry);}
  }
  close(){this.readyState=2;clearTimeout(this._timer);this._abort?.abort();}
};
