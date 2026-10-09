import {createApp} from './sdk.js';
import {initial, reducer, actions} from './model.js';
import {rollingNumber, confirmInPlace, copyButton, haptic} from './details/details.js';
let app;
async function act(name) {
  try { await app.act(name); document.querySelector('#message').textContent=''; haptic(); }
  catch (error) { document.querySelector('#message').textContent=error.message; }
}
const controls = document.querySelector('#controls');
for (const name of actions) {
  const button = document.createElement('button');
  button.textContent = name[0].toUpperCase()+name.slice(1);
  button.dataset.action = name;
  button.classList.add('nxd-press');
  controls.append(button);
  if (name === 'reset') confirmInPlace(button, {question:'Reset the count?', confirmLabel:'Reset count', keepLabel:'Keep count', onConfirm:() => act(name)});
  else button.addEventListener('click',() => act(name));
}
app = await createApp({initial,reducer,actions,render(state) {
  rollingNumber(document.querySelector('#count-value'), state.count);
}});
copyButton(document.querySelector('#copy'), () => 'Count: '+app.state().count, {label:'Copy count', showLabel:true});
if(app.describe().transport==='device-local')document.querySelector('#message').textContent='Saved on this device';
try {
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('./sw.js').catch(() => {});
} catch (error) {
  // Sandboxed previews use an opaque origin and prohibit service workers.
  // The shared app remains usable there; offline caching is optional.
  if (error.name !== 'SecurityError') throw error;
}
