/* Turns whatever HR exports (long or wide, Arabic or English, Hijri or Gregorian dates) into the rows POST /api/import expects.
   Browser and Node (tests/test_import_parse.js) share this file. Nothing here guesses a date: unreadable cells stay as typed and the
   server reports them back with a reason. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.ImtParse = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  const nk = x => String(x ?? '').replace(/ /g, ' ').trim().toLowerCase().replace(/\s+/g, ' ')
    .replace(/[ً-ٰٟـ]/g, '').replace(/[أإآ]/g, 'ا').replace(/ة/g, 'ه').replace(/ى/g, 'ي');

  const HDR = {
    branch: ['فرع', 'الفرع', 'اسم الفرع', 'المنشاة', 'الموقع', 'branch', 'branch name', 'location', 'site', 'establishment'],
    city: ['مدينة', 'المدينة', 'city'],
    employee: ['موظف', 'الموظف', 'اسم الموظف', 'الاسم', 'اسم العامل', 'العامل', 'employee', 'employee name', 'name', 'full name', 'worker'],
    role: ['وظيفة', 'الوظيفة', 'المهنة', 'المسمي الوظيفي', 'المسمى الوظيفي', 'role', 'job title', 'position', 'profession', 'occupation'],
    emp_id: ['رقم الاقامه', 'رقم الهويه', 'رقم الهوية', 'رقم الموظف', 'الرقم الوظيفي', 'رقم الحدود', 'iqama number', 'iqama no', 'iqama no.', 'id number', 'employee id', 'emp id', 'national id', 'id'],
    document: ['وثيقه', 'الوثيقه', 'نوع الوثيقه', 'البند', 'نوع البند', 'document', 'document type', 'doc', 'type', 'item'],
    date: ['تاريخ الانتهاء', 'تاريخ الاستحقاق', 'الانتهاء', 'الاستحقاق', 'تاريخ انتهاء الوثيقه', 'expiry', 'expiry date', 'expires', 'due date', 'due', 'date', 'expiration', 'expiration date'],
  };
  const HDR_N = Object.fromEntries(Object.entries(HDR).map(([k, v]) => [k, v.map(nk)]));
  const NOISE = new Set(['تاريخ', 'انتهاء', 'نهايه', 'صلاحيه', 'الانتهاء', 'تنتهي', 'سريان', 'expiry', 'expiration', 'expires', 'expire', 'exp', 'date', 'end', 'valid', 'validity', 'until', 'of', 'to', 'hijri', 'هجري', 'ميلادي', 'gregorian', '(هجري)', '(ميلادي)', '-', '/']);

  /* ---------- delimited text ---------- */
  function parseDelimited(text) {
    text = String(text).replace(/^﻿/, '');
    const lines = text.split(/\r?\n/).filter(l => l.trim()).slice(0, 8);          // title rows may sit above the header
    const delim = [',', ';', '\t'].map(d => [d, lines.reduce((a, l) => a + l.split(d).length - 1, 0)]).sort((a, b) => b[1] - a[1])[0][0];
    const rows = []; let row = [], cur = '', q = false;
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (q) { if (ch === '"') { if (text[i + 1] === '"') { cur += '"'; i++; } else q = false; } else cur += ch; }
      else if (ch === '"') q = true;
      else if (ch === delim) { row.push(cur); cur = ''; }
      else if (ch === '\n' || ch === '\r') { if (ch === '\r' && text[i + 1] === '\n') i++; row.push(cur); cur = ''; if (row.some(x => x.trim() !== '')) rows.push(row); row = []; }
      else cur += ch;
    }
    row.push(cur); if (row.some(x => x.trim() !== '')) rows.push(row);
    return rows;
  }

  /* ---------- dates ---------- */
  let hijriFmt = null;
  try { hijriFmt = new Intl.DateTimeFormat('en-u-ca-islamic-umalqura-nu-latn', { year: 'numeric', month: 'numeric', day: 'numeric', timeZone: 'UTC' }); } catch (e) { /* unsupported */ }
  const hCache = new Map();
  function hijriToIso(y, m, d) {
    if (!hijriFmt || m < 1 || m > 12 || d < 1 || d > 30) return '';
    const key = y + '-' + m + '-' + d; if (hCache.has(key)) return hCache.get(key);
    const part = t => { const o = {}; hijriFmt.formatToParts(new Date(t)).forEach(p => { if (p.type !== 'literal') o[p.type] = +p.value; }); return o; };
    let t = Date.UTC(622, 6, 16) + ((y - 1) * 354.36707 + (m - 1) * 29.530589 + (d - 1)) * 86400000, res = '';
    for (let k = 0; k < 14; k++) {
      const p = part(t), diff = (y - p.year) * 354.36707 + (m - p.month) * 29.530589 + (d - p.day);
      if (p.year === y && p.month === m && p.day === d) { res = new Date(t).toISOString().slice(0, 10); break; }
      t += (Math.abs(diff) < 1 ? Math.sign(diff) : Math.round(diff)) * 86400000;
    }
    hCache.set(key, res); return res;
  }
  const MONTHS = { jan: 1, january: 1, feb: 2, february: 2, mar: 3, march: 3, apr: 4, april: 4, may: 5, jun: 6, june: 6, jul: 7, july: 7, aug: 8, august: 8, sep: 9, sept: 9, september: 9, oct: 10, october: 10, nov: 11, november: 11, dec: 12, december: 12,
    'يناير': 1, 'فبراير': 2, 'مارس': 3, 'ابريل': 4, 'مايو': 5, 'يونيو': 6, 'يوليو': 7, 'اغسطس': 8, 'سبتمبر': 9, 'اكتوبر': 10, 'نوفمبر': 11, 'ديسمبر': 12 };
  const iso = (y, m, d) => {
    const s = `${String(y).padStart(4, '0')}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
    const t = new Date(s + 'T00:00:00Z');
    return isNaN(t) || t.toISOString().slice(0, 10) !== s ? '' : s;
  };
  /** Returns ISO yyyy-mm-dd, or the original text when it cannot be read (so the server can say why). */
  function toIso(v) {
    if (v instanceof Date) return isNaN(v) ? '' : v.toISOString().slice(0, 10);
    if (typeof v === 'number') return v > 20000 && v < 80000 ? new Date(Math.round((v - 25569) * 86400000)).toISOString().slice(0, 10) : String(v);
    const raw = String(v ?? '').trim();
    if (!raw) return '';
    let s = raw.replace(/[٠-٩]/g, c => '٠١٢٣٤٥٦٧٨٩'.indexOf(c)).replace(/[۰-۹]/g, c => '۰۱۲۳۴۵۶۷۸۹'.indexOf(c)).trim();
    let hij = false;
    const hm = /^(.*?)\s*(هـ|هجري|ah|h)\.?$/i.exec(s); if (hm) { s = hm[1].trim(); hij = true; }
    s = s.replace(/[T ]\d{1,2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$/, '');     // drop a time part
    let m, y, mo, d;
    if ((m = /^(\d{4})[-\/.](\d{1,2})[-\/.](\d{1,2})$/.exec(s))) { y = +m[1]; mo = +m[2]; d = +m[3]; }
    else if ((m = /^(\d{1,2})[-\/.](\d{1,2})[-\/.](\d{4})$/.exec(s))) { d = +m[1]; mo = +m[2]; y = +m[3]; }
    else if ((m = /^(\d{1,2})[-\/.](\d{1,2})[-\/.](\d{2})$/.exec(s))) { d = +m[1]; mo = +m[2]; y = 2000 + +m[3]; }
    else if ((m = /^(\d{1,2})[ -\/.]([^\d\s\-\/.,]+)[ -\/.,]+(\d{4})$/.exec(s)) && MONTHS[nk(m[2])]) { d = +m[1]; mo = MONTHS[nk(m[2])]; y = +m[3]; }
    else if ((m = /^([^\d\s\-\/.,]+)[ .]+(\d{1,2}),?\s+(\d{4})$/.exec(s)) && MONTHS[nk(m[1])]) { mo = MONTHS[nk(m[1])]; d = +m[2]; y = +m[3]; }
    else return raw;
    if (hij || (y >= 1300 && y <= 1600)) return hijriToIso(y, mo, d) || raw;       // Hijri dates (Muqeem / Qiwa exports)
    return iso(y, mo, d) || raw;
  }
  const isDateLike = v => /^\d{4}-\d{2}-\d{2}$/.test(toIso(v));

  /* ---------- document-type lookup (from GET /api/import/doc-types) ---------- */
  function makeLookup(docTypes) {
    const exact = new Map(), scope = {};
    for (const t of docTypes.doc_types.slice().sort((a, b) => a.code < b.code ? -1 : 1)) {
      scope[t.code] = t.scope;
      for (const n of [t.code, ...t.names]) { const k = nk(n); if (!exact.has(k)) exact.set(k, t.code); }
    }
    const titles = Object.fromEntries(docTypes.doc_types.map(t => [t.code, t.names[0]]));
    const find = text => {
      const k = nk(text); if (!k) return null;
      if (exact.has(k)) return exact.get(k);
      let best = null;
      for (const [n, code] of exact) if (n.length >= 4 && k.includes(n) && (!best || n.length > best[0].length)) best = [n, code];
      return best ? best[1] : null;
    };
    return { find, scope, titles };
  }

  /* ---------- table -> rows ---------- */
  function coreFields(cells) {
    const m = {};
    cells.forEach((c, j) => { const k = nk(c); for (const [f, names] of Object.entries(HDR_N)) if (m[f] === undefined && names.includes(k)) m[f] = j; });
    return m;
  }
  function stripNoise(h) { return nk(h).split(' ').filter(w => !NOISE.has(w)).join(' ').replace(/[()]/g, '').trim(); }

  function tableToRows(table, lookup, opts) {
    opts = opts || {};
    if (!table || !table.length) throw new Error('الملف فارغ');
    // header row: the row (among the first 20) that names the most known columns; title rows above it are ignored
    let hi = 0, best = -1;
    for (let i = 0; i < Math.min(20, table.length); i++) {
      const cells = table[i].map(x => String(x ?? ''));
      const core = Object.keys(coreFields(cells)).length;
      const docs = cells.filter(c => stripNoise(c) && lookup.find(stripNoise(c))).length;
      const sc = core * 2 + docs;
      if (sc > best) { best = sc; hi = i; }
    }
    const head = table[hi].map(x => String(x ?? '')), idx = coreFields(head), body = table.slice(hi + 1);
    const cell = (r, f) => idx[f] === undefined ? '' : r[idx[f]];
    const info = { header_row: hi + 1, mapped: {}, doc_columns: [], ignored: [], format: '' };
    for (const [f, j] of Object.entries(idx)) info.mapped[f] = head[j];

    // wide format: a column per document type holding that document's expiry date
    const used = new Set(Object.values(idx));
    const docCols = [];
    head.forEach((h, j) => {
      if (used.has(j) || !String(h).trim()) return;
      const code = lookup.find(stripNoise(h));
      if (!code) { info.ignored.push(h); return; }
      const vals = body.map(r => r[j]).filter(v => String(v ?? '').trim() !== '');
      const ratio = vals.length ? vals.filter(isDateLike).length / vals.length : 0;
      if (ratio >= 0.5) { docCols.push({ j, code }); info.doc_columns.push({ header: h, code, title: lookup.titles[code] }); }
      else info.ignored.push(h);
    });

    const long = idx.document !== undefined && idx.date !== undefined;
    if (!long && !docCols.length) {
      throw new Error('لم نتعرف على أعمدة الوثائق. إما أن يكون في الملف عمودا «الوثيقة» و«تاريخ الانتهاء»، أو عمود لكل وثيقة (مثل «تاريخ انتهاء الإقامة»). الأعمدة الموجودة: ' + head.filter(Boolean).join(' | '));
    }
    if (idx.branch === undefined && !opts.defaultBranch) throw new Error('لا يوجد عمود للفرع — اكتب اسم الفرع الافتراضي في الخانة المخصصة.');
    info.format = long ? 'long' : 'wide';

    const out = []; let lastBranch = '';
    for (const r of body) {
      if (!r || !r.some(x => String(x ?? '').trim() !== '')) continue;
      const g = f => String(cell(r, f) ?? '').trim();
      let branch = g('branch'); if (branch) lastBranch = branch; else branch = (idx.branch !== undefined && g('employee') ? lastBranch : '') || opts.defaultBranch || '';
      const base = { branch, city: g('city'), employee: g('employee'), role: g('role'), emp_id: g('emp_id') };
      if (long) out.push({ ...base, document: g('document'), date: toIso(cell(r, 'date')) });
      for (const c of docCols) {
        const v = r[c.j]; if (String(v ?? '').trim() === '') continue;
        out.push({ ...base, document: c.code, date: toIso(v) });
      }
    }
    info.rows = out.length; info.sample = out.slice(0, 6);
    return { rows: out, info };
  }

  return { nk, parseDelimited, toIso, hijriToIso, makeLookup, tableToRows, isDateLike };
});
