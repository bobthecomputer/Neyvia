export const initial = {count:0};
export const actions = ['increment','decrement','reset'];
export function reducer(state, name, args) {
  switch (name) {
    case 'increment': return {...state,count:state.count+1};
    case 'decrement': return {...state,count:Math.max(0,state.count-1)};
    case 'reset': return {...state,count:0};
    default: throw new Error('Unknown action: '+name);
  }
}
