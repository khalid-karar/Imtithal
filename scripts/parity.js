// node scripts/parity.js <data.json> <requests.json> <out.json> — replays requests through demo-api.js
const fs = require('fs'), path = require('path');
const { createApi } = require(path.join(__dirname, '..', 'static', 'demo-api.js'));
const [data, reqs, out] = process.argv.slice(2);
const api = createApi(JSON.parse(fs.readFileSync(data, 'utf8')), null, {});
const res = JSON.parse(fs.readFileSync(reqs, 'utf8')).map(([m, u, b]) => api.handle(m, u, b));
fs.writeFileSync(out, JSON.stringify(res));
