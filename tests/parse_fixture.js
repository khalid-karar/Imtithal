// node tests/parse_fixture.js <doc_types.json> <fixture> [defaultBranch] -> JSON {rows, info}
const fs = require('fs'), path = require('path');
const P = require('../static/import-parse.js');
const [dt, file, def] = process.argv.slice(2);
const lookup = P.makeLookup(JSON.parse(fs.readFileSync(dt, 'utf8')));
let table;
if (/\.xlsx$/i.test(file)) {
  let XLSX; try { XLSX = require('xlsx'); } catch (e) { process.stderr.write('xlsx package not installed'); process.exit(3); }
  const wb = XLSX.read(fs.readFileSync(file), { type: 'buffer', cellDates: false });
  table = XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]], { header: 1, raw: true, defval: '' });
} else table = P.parseDelimited(fs.readFileSync(file, 'utf8'));
try { process.stdout.write(JSON.stringify(P.tableToRows(table, lookup, { defaultBranch: def || '' }))); }
catch (e) { process.stdout.write(JSON.stringify({ error: e.message })); process.exit(2); }
