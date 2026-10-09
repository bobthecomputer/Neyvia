import React, {useState} from 'react';
import {View, Text, Pressable, StyleSheet} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {initial,reducer,actions} from './www/model.js';
import identity from './www/identity.json';
// One reducer across the device UI and agent bridge. Explicitly observable.
export default function App() {
  const [state,setState]=useState({...initial,revision:0});
  const [ready,setReady]=useState(false),[error,setError]=useState('');
  const current=React.useRef(state);
  const queue=React.useRef(Promise.resolve());
  React.useEffect(()=>{ AsyncStorage.getItem('neyvia-app-state').then(raw=>{
    const saved=raw&&JSON.parse(raw); if(saved&&Number.isInteger(saved.count)&&saved.count>=0){current.current=saved;setState(saved);}
    setReady(true);
  }).catch(error=>setError(error.message)); },[]);
  const commit=async(name,args={},options={})=>{
    if(!actions.includes(name)) throw new Error('Unknown action');
    const before=current.current;
    if(options.expectedRevision!==undefined&&options.expectedRevision!==before.revision)throw new Error('Observe the current state before acting');
    const after={...reducer(before,name,args),revision:before.revision+1};
    if(!Number.isInteger(after.count)||after.count<0)throw new Error('Count invariant failed');
    await AsyncStorage.setItem('neyvia-app-state',JSON.stringify(after));
    current.current=after;setState(after);return {ok:true,before,after};
  };
  const act=(name,args={},options={})=>queue.current=queue.current.catch(()=>{}).then(()=>commit(name,args,options));
  if(ready)globalThis.neyviaApp={state:()=>({...current.current}),act,describe:()=>({version:'1.1',instance:identity.instance,transport:'device-local',actions})};
  return <View style={styles.screen}><Text style={styles.title}>__NAME__</Text><Text accessibilityLiveRegion="polite" style={styles.title}>Count: {state.count}</Text>{actions.map(name=><Pressable key={name} disabled={!ready} accessibilityRole="button" accessibilityLabel={name} onPress={()=>act(name).catch(error=>setError(error.message))} style={styles.button}><Text>{name}</Text></Pressable>)}<Text accessibilityLiveRegion="polite">{error||(!ready?'Loading saved state':'Saved on this device')}</Text><Text>Made with Neyvia</Text></View>;
}
const styles=StyleSheet.create({screen:{flex:1,justifyContent:'center',padding:32,backgroundColor:'#ecf3ed'},title:{fontSize:32,marginBottom:24},button:{backgroundColor:'white',padding:18,marginBottom:12,borderRadius:12}});
