// Test-only proof boundary: bind ephemeral test listeners to an assigned port.
const net = require('node:net');
const {syncBuiltinESMExports} = require('node:module');
const listen = net.Server.prototype.listen;
net.Server.prototype.listen = function (...args) {
  if (process.env.INT3_STRICT_PORTS === '1' && (args[0] === 0 || args[0]?.port === 0)) throw new Error('INT3: explicit listener port required');
  if (args[0] === 0) args[0] = 48659;
  else if (args[0] && typeof args[0] === 'object' && args[0].port === 0) args[0] = {...args[0], port:48659};
  const port = typeof args[0] === 'object' ? args[0].port : args[0];
  if (port != null && /^\d+$/.test(String(port)) && (+port < 48651 || +port > 48659)) throw new Error('INT3: unassigned listener port');
  return listen.apply(this,args);
};
const connect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function (...args) {
  const opts = Array.isArray(args[0]) ? args[0][0] : args[0];
  const port = typeof opts === 'object' ? opts.port : opts;
  const host = typeof opts === 'object' ? opts.host || 'localhost' : args[1] || 'localhost';
  if (port != null && (!['localhost','127.0.0.1','::1'].includes(host) || +port < 48651 || +port > 48659)) throw new Error('INT3: connection outside assigned loopback ports');
  return connect.apply(this,args);
};
syncBuiltinESMExports();
