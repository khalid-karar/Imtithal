/* امتثال — static demo API.
 * A browser-side port of engine.py + the customer endpoints of main.py, so the customer UI can be hosted on a
 * static host (Netlify) with no server. State changes live in localStorage only. Parity with the Python server is
 * enforced by scripts/parity_check.py — change engine.py or main.py and that check must still pass.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.ImtithalDemo = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const SOON_WEIGHT = 0.35, EMP_SHARE = 0.4, HORIZON_DAYS = 30;

  // ---------- dates (ISO strings, UTC arithmetic) ----------
  const parse = s => { const [y, m, d] = s.split('-').map(Number); return Date.UTC(y, m - 1, d); };
  const iso = ms => new Date(ms).toISOString().slice(0, 10);
  const daysBetween = (a, b) => Math.round((parse(a) - parse(b)) / 86400000);
  function addMonths(s, months) {
    const [y, m, d] = s.split('-').map(Number);
    const idx = (m - 1) + months;
    const ny = y + Math.floor(idx / 12), nm = ((idx % 12) + 12) % 12 + 1;
    const last = new Date(Date.UTC(ny, nm, 0)).getUTCDate();
    return iso(Date.UTC(ny, nm - 1, Math.min(d, last)));
  }
  const validDate = s => typeof s === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(s) && iso(parse(s)) === s;
  function pyRound(x) {                       // Python's round(): halves go to the even neighbour
    const f = Math.floor(x);
    if (x - f === 0.5) return f % 2 === 0 ? f : f + 1;
    return Math.round(x);
  }

  function createApi(snapshot, store, opts) {
    opts = opts || {};
    const nowTs = opts.now || (() => new Date().toISOString().slice(0, 19) + '+00:00');
    const TODAY = snapshot.as_of;

    // ---------- state (mutable parts) ----------
    const fresh = () => ({
      instances: JSON.parse(JSON.stringify(snapshot.instances)),
      emp_docs: JSON.parse(JSON.stringify(snapshot.emp_docs)),
      acks: {}, vip_requests: [], audit: [], next_vip: 1, next_audit: 1,
    });
    let S = (store && store.get()) || fresh();
    const save = () => { if (store) store.set(S); };

    // ---------- static lookups ----------
    const tpl = Object.fromEntries(snapshot.templates.map(t => [t.code, t]));
    const orgs = snapshot.orgs, branchesAll = snapshot.branches;
    const branchById = Object.fromEntries(branchesAll.map(b => [b.id, b]));
    const vipName = Object.fromEntries(snapshot.vip_services.map(v => [v.code, v.name]));
    const orgById = id => orgs.find(o => o.id === id);

    class HttpError extends Error { constructor(status, detail) { super(detail); this.status = status; this.detail = detail; } }
    const log = (org_id, action, detail) => { S.audit.push({ id: S.next_audit++, org_id, ts: nowTs(), action, detail }); };

    // ---------- engine (mirror of engine.py) ----------
    const status = (left, lead) => left < 0 ? 'overdue' : left <= lead ? 'soon' : 'ok';
    const pub = t => ({
      code: t.code, title: t.title, authority: t.authority, category: t.category, severity: t.severity,
      penalty_sar: t.penalty_sar, penalty_note: t.penalty_note, fix_steps: t.fix_steps, evidence: t.evidence,
      vip_code: t.vip_code, source_url: t.source_url, verified: !!t.verified, lead_days: t.lead_days,
      recurrence_months: t.recurrence_months,
    });

    function loadItems(orgId, branchId) {
      const items = [];
      for (const r of S.instances) {
        if (r.org_id !== orgId || (branchId && r.branch_id !== branchId)) continue;
        const t = tpl[r.template_code], left = daysBetween(r.due_date, TODAY);
        items.push(Object.assign({
          id: 'o-' + r.id, kind: 'obligation', branch_id: r.branch_id, branch_name: branchById[r.branch_id].name,
          due_date: r.due_date, last_done: r.last_done, days_left: left, status: status(left, t.lead_days),
          evidence_note: r.evidence_note, vip_name: vipName[t.vip_code] ?? null, employee: null,
        }, pub(t)));
      }
      for (const r of S.emp_docs) {
        if (r.org_id !== orgId || (branchId && r.branch_id !== branchId)) continue;
        const t = tpl[r.template_code], left = daysBetween(r.expiry, TODAY);
        items.push(Object.assign({
          id: 'e-' + r.id, kind: 'employee_doc', branch_id: r.branch_id, branch_name: branchById[r.branch_id].name,
          due_date: r.expiry, last_done: null, days_left: left, status: status(left, t.lead_days),
          evidence_note: '', vip_name: vipName[t.vip_code] ?? null,
          employee: { id: r.eid, name: r.name, role: r.role },
        }, pub(t)));
      }
      return items;
    }

    function loss(items) {
      let total = 0, l = 0;
      for (const i of items) { total += i.severity; l += i.severity * (i.status === 'overdue' ? 1.0 : i.status === 'soon' ? SOON_WEIGHT : 0.0); }
      return [l, total];
    }
    function score(items) {
      const obl = items.filter(i => i.kind === 'obligation'), emp = items.filter(i => i.kind === 'employee_doc');
      const parts = [];
      for (const [group, share] of [[obl, 1 - EMP_SHARE], [emp, EMP_SHARE]]) {
        if (group.length) { const [l, total] = loss(group); parts.push([100 * (1 - l / total), share]); }
      }
      if (!parts.length) return 100;
      const w = parts.reduce((a, [, s]) => a + s, 0);
      return pyRound(parts.reduce((a, [v, s]) => a + v * s, 0) / w);
    }
    const band = s => s >= 85 ? 'good' : s >= 65 ? 'watch' : 'risk';
    const moneyAtRisk = items => items.filter(i => i.status === 'overdue').reduce((a, i) => a + i.penalty_sar, 0);
    const exposure30 = items => items.filter(i => i.days_left >= 0 && i.days_left <= HORIZON_DAYS).reduce((a, i) => a + i.penalty_sar, 0);
    const counts = items => ({
      overdue: items.filter(i => i.status === 'overdue').length, soon: items.filter(i => i.status === 'soon').length,
      ok: items.filter(i => i.status === 'ok').length, total: items.length,
    });
    const ORDER = { overdue: 0, soon: 1, ok: 2 };
    const prioCmp = (a, b) => (ORDER[a.status] - ORDER[b.status]) || (b.severity - a.severity) || (a.days_left - b.days_left);

    function urgent(items, limit) {
      const out = [], groups = new Map();
      for (const i of items) {
        if (i.status === 'ok') continue;
        if (i.kind === 'obligation') out.push(i);
        else { const k = i.branch_id + '|' + i.code + '|' + i.status; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(i); }
      }
      for (const g of groups.values()) {
        let first = g[0];
        for (const x of g) if (x.days_left < first.days_left) first = x;
        out.push(Object.assign({}, first, {
          id: `g-${first.branch_id}-${first.code}-${first.status}`, kind: 'group', count: g.length, employee: null,
          penalty_sar: g.reduce((a, x) => a + x.penalty_sar, 0), days_left: first.days_left,
        }));
      }
      out.sort(prioCmp);
      return out.slice(0, limit);
    }
    function byAuthority(items) {
      const agg = new Map();
      for (const i of items) {
        if (!agg.has(i.authority)) agg.set(i.authority, { authority: i.authority, overdue: 0, soon: 0, ok: 0 });
        agg.get(i.authority)[i.status]++;
      }
      const rows = [...agg.values()];
      rows.sort((a, b) => (b.overdue - a.overdue) || (b.soon - a.soon) || (a.authority < b.authority ? -1 : a.authority > b.authority ? 1 : 0));
      return rows;
    }
    const nextDue = (oldDue, done, rec) => addMonths(done <= oldDue ? oldDue : done, rec);

    // ---------- endpoints ----------
    const needOrg = id => { const o = orgById(id); if (!o) throw new HttpError(404, 'المنشأة غير موجودة'); return o; };

    function overview(orgId) {
      const org = needOrg(orgId), items = loadItems(orgId);
      const branches = branchesAll.filter(b => b.org_id === orgId).map(b => {
        const bi = items.filter(i => i.branch_id === b.id), s = score(bi);
        return {
          id: b.id, name: b.name, city: b.city, headcount: b.headcount, score: s, band: band(s), counts: counts(bi),
          money_at_risk: moneyAtRisk(bi),
          top_issues: urgent(bi, 3).map(t => ({ title: t.kind === 'group' ? `${t.count} × ${t.title}` : t.title, status: t.status, days_left: t.days_left })),
        };
      });
      const s = score(items);
      return {
        org: { id: org.id, name: org.name, pack: org.pack, city: org.city }, as_of: TODAY, score: s, band: band(s), counts: counts(items),
        money_at_risk: moneyAtRisk(items), exposure_30: exposure30(items), branches, urgent: urgent(items, 10), by_authority: byAuthority(items),
      };
    }

    function branchItems(branchId, q) {
      const b = branchById[branchId];
      if (!b) throw new HttpError(404, 'الفرع غير موجود');
      let items = loadItems(b.org_id, branchId);
      const all = items;
      if (q.status) items = items.filter(i => i.status === q.status);
      if (q.kind) items = items.filter(i => i.kind === q.kind);
      items = items.slice().sort(prioCmp);
      const s = score(all);
      return { branch: { id: b.id, org_id: b.org_id, name: b.name, city: b.city, pack: b.pack, headcount: b.headcount }, score: s, band: band(s), items };
    }

    function employeeDocs(orgId, q) {
      needOrg(orgId);
      let items = loadItems(orgId, q.branch_id ? Number(q.branch_id) : null).filter(i => i.kind === 'employee_doc');
      if (q.status) items = items.filter(i => i.status === q.status);
      if (q.code) items = items.filter(i => i.code === q.code);
      items = items.slice().sort(prioCmp);
      return { total: items.length, items: items.slice(0, 300) };
    }

    function complete(itemId, body) {
      const m = /^([oe])-(\d+)$/.exec(itemId);
      if (!m) throw new HttpError(400, 'معرّف غير صالح');
      const id = Number(m[2]);
      for (const f of ['done_date', 'new_expiry']) if (body[f] && !validDate(body[f])) throw new HttpError(422, 'التاريخ يجب أن يكون بصيغة YYYY-MM-DD');
      if (m[1] === 'o') {
        const r = S.instances.find(x => x.id === id);
        if (!r) throw new HttpError(404, 'البند غير موجود');
        const t = tpl[r.template_code], done = body.done_date || TODAY, nd = nextDue(r.due_date, done, t.recurrence_months);
        r.due_date = nd; r.last_done = done; r.evidence_note = body.note || '';
        log(r.org_id, 'complete', `${t.title} — الاستحقاق التالي ${nd}`);
        save(); return { ok: true, next_due: nd };
      }
      const r = S.emp_docs.find(x => x.id === id);
      if (!r) throw new HttpError(404, 'الوثيقة غير موجودة');
      const t = tpl[r.template_code], ne = body.new_expiry || addMonths(TODAY, t.recurrence_months);
      r.expiry = ne;
      log(r.org_id, 'renew', `${t.title} — ${r.name} — ينتهي ${ne}`);
      save(); return { ok: true, next_due: ne };
    }

    function changes(orgId) {
      needOrg(orgId);
      const items = loadItems(orgId);
      const packOf = Object.fromEntries(branchesAll.filter(b => b.org_id === orgId).map(b => [b.id, b.pack]));
      const acked = S.acks[orgId] || {};
      const out = [];
      for (const ch of snapshot.changes) {
        const hit = items.filter(i => ch.affects.includes(i.code) && ch.packs.includes(packOf[i.branch_id]));
        if (!hit.length) continue;
        const per = new Map();
        for (const i of hit) {
          if (!per.has(i.branch_id)) per.set(i.branch_id, { branch_id: i.branch_id, branch_name: i.branch_name, items: 0, attention: 0 });
          const b = per.get(i.branch_id); b.items++; b.attention += i.status !== 'ok' ? 1 : 0;
        }
        out.push({
          id: ch.id, title: ch.title, authority: ch.authority, published: ch.published, effective: ch.effective,
          days_to_effective: daysBetween(ch.effective, TODAY), summary: ch.summary, action_required: ch.action_required,
          affects: ch.affects, source_url: ch.source_url, source_quality: ch.source_quality, is_demo: !!ch.is_demo,
          provenance: ch.provenance, reviewed: !!ch.reviewed_by, acknowledged_at: acked[ch.id] ?? null,
          impact: [...per.values()].sort((a, b) => b.attention - a.attention),
        });
      }
      return { changes: out };
    }

    function acknowledge(orgId, changeId) {
      needOrg(orgId);
      const ch = snapshot.changes.find(c => c.id === changeId);
      if (!ch) throw new HttpError(404, 'التحديث غير موجود');
      const ts = nowTs();
      (S.acks[orgId] = S.acks[orgId] || {})[changeId] = ts;
      log(orgId, 'ack_change', ch.title);
      save(); return { ok: true, acknowledged_at: ts };
    }

    function vip(orgId) {
      const org = needOrg(orgId);
      const catalog = snapshot.vip_services.filter(v => v.packs.includes(org.pack)).slice().sort((a, b) => b.price_from - a.price_from)
        .map(v => ({ code: v.code, name: v.name, description: v.description, price_from: v.price_from, price_unit: v.price_unit, sla_days: v.sla_days, packs: v.packs }));
      const requests = S.vip_requests.filter(r => r.org_id === orgId).slice().sort((a, b) => b.id - a.id).map(r => Object.assign({}, r, {
        service_name: vipName[r.service_code], branch_name: r.branch_id != null ? branchById[r.branch_id].name : null,
      }));
      return { catalog, requests };
    }

    function vipRequest(orgId, body) {
      needOrg(orgId);
      const s = snapshot.vip_services.find(v => v.code === body.service_code);
      if (!s) throw new HttpError(404, 'الخدمة غير موجودة');
      const now = nowTs(), id = S.next_vip++;
      S.vip_requests.push({ id, org_id: orgId, branch_id: body.branch_id ?? null, service_code: body.service_code, item_ref: body.item_ref || '', note: body.note || '', status: 'new', created_at: now, updated_at: now });
      log(orgId, 'vip_request', s.name);
      save(); return { ok: true, id };
    }

    function vipAdvance(reqId) {
      const r = S.vip_requests.find(x => x.id === reqId);
      if (!r) throw new HttpError(404, 'الطلب غير موجود');
      const nxt = { new: 'in_progress', in_progress: 'done' }[r.status] || r.status;
      if (nxt !== r.status) { r.status = nxt; r.updated_at = nowTs(); log(r.org_id, 'vip_status', `طلب #${reqId} → ${nxt}`); save(); }
      return { ok: true, status: nxt };
    }

    function audit(orgId) {
      return { entries: S.audit.filter(e => e.org_id === orgId).slice().sort((a, b) => b.id - a.id).slice(0, 50) };
    }

    // ---------- router ----------
    function handle(method, url, body) {
      const u = new URL(url, 'http://demo.local');
      const path = u.pathname, q = Object.fromEntries(u.searchParams.entries()), b = body || {};
      let m;
      try {
        if (method === 'GET') {
          if (path === '/api/health') return ok({ ok: true, as_of: TODAY });
          if (path === '/api/orgs') return ok({ as_of: TODAY, orgs: orgs.map(o => ({ id: o.id, name: o.name, pack: o.pack, city: o.city })) });
          if ((m = /^\/api\/orgs\/(\d+)\/overview$/.exec(path))) return ok(overview(+m[1]));
          if ((m = /^\/api\/branches\/(\d+)\/items$/.exec(path))) return ok(branchItems(+m[1], q));
          if ((m = /^\/api\/orgs\/(\d+)\/employee-docs$/.exec(path))) return ok(employeeDocs(+m[1], q));
          if ((m = /^\/api\/orgs\/(\d+)\/changes$/.exec(path))) return ok(changes(+m[1]));
          if ((m = /^\/api\/orgs\/(\d+)\/vip$/.exec(path))) return ok(vip(+m[1]));
          if ((m = /^\/api\/orgs\/(\d+)\/audit$/.exec(path))) return ok(audit(+m[1]));
        } else if (method === 'POST') {
          if ((m = /^\/api\/items\/([^/]+)\/complete$/.exec(path))) return ok(complete(decodeURIComponent(m[1]), b));
          if ((m = /^\/api\/orgs\/(\d+)\/changes\/(\d+)\/acknowledge$/.exec(path))) return ok(acknowledge(+m[1], +m[2]));
          if ((m = /^\/api\/orgs\/(\d+)\/vip\/requests$/.exec(path))) return ok(vipRequest(+m[1], b));
          if ((m = /^\/api\/vip\/requests\/(\d+)\/advance$/.exec(path))) return ok(vipAdvance(+m[1]));
        }
        return { status: 404, body: { detail: 'Not Found' } };
      } catch (e) {
        if (e instanceof HttpError) return { status: e.status, body: { detail: e.detail } };
        throw e;
      }
    }
    const ok = body => ({ status: 200, body });

    return { handle, reset: () => { S = fresh(); save(); } };
  }

  // ---------- browser glue ----------
  if (typeof window !== 'undefined' && typeof document !== 'undefined' && window.fetch) {
    const realFetch = window.fetch.bind(window);
    let api = null;
    const memory = {};
    const localStore = key => ({
      get() { try { const v = window.localStorage.getItem(key); return v ? JSON.parse(v) : (memory[key] || null); } catch (e) { return memory[key] || null; } },
      set(obj) { memory[key] = obj; try { window.localStorage.setItem(key, JSON.stringify(obj)); } catch (e) { /* private mode: keep in memory */ } },
    });
    const ready = realFetch('demo-data.json', { cache: 'no-cache' }).then(r => r.json()).then(snap => {
      const key = 'imtithal-demo:' + snap.build_id;
      api = createApi(snap, localStore(key));
      const bar = document.createElement('div');
      bar.style.cssText = 'background:#EFE9DC;color:#2B3B5C;font-size:12.5px;text-align:center;padding:7px 12px;border-bottom:1px solid #D8D0BE';
      bar.innerHTML = 'نسخة عرض ثابتة: تُحفظ تغييراتك في متصفحك فقط ولا تُرسل إلى أي خادم، والتاريخ المعروض مثبّت على <bdi dir="ltr">' + snap.as_of + '</bdi>. ';
      const btn = document.createElement('button');
      btn.textContent = 'إعادة ضبط العرض';
      btn.style.cssText = 'margin-inline-start:8px;border:1px solid #16233F;background:#fff;color:#16233F;border-radius:4px;padding:2px 10px;cursor:pointer;font:inherit';
      btn.onclick = () => { try { window.localStorage.removeItem(key); } catch (e) {} delete memory[key]; location.reload(); };
      bar.appendChild(btn);
      document.body.insertBefore(bar, document.body.firstChild.nextSibling || null);
    });
    window.fetch = async function (input, init) {
      const url = typeof input === 'string' ? input : input.url;
      if (!url.startsWith('/api/')) return realFetch(input, init);
      await ready;
      let body = null;
      if (init && init.body) { try { body = JSON.parse(init.body); } catch (e) { body = null; } }
      const res = api.handle((init && init.method) || 'GET', url, body);
      return new Response(JSON.stringify(res.body), { status: res.status, headers: { 'Content-Type': 'application/json' } });
    };
  }

  return { createApi };
}));
