#!/usr/bin/env python3
"""Static profile viewer: one self-contained HTML file, no server, works offline.

Built from the envelopes the runner already writes. Desktop and mobile layouts share the
same markup, and every published value keeps its source link and retrieval time so a reader
can check a claim without leaving the page.
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path
from typing import Any

GROUPS = [
    ("overview", "Company", ["legal_name", "organisation_number", "legal_form", "registered_address", "municipality", "postal_code", "industry", "industry_code", "registered_employees", "latest_annual_accounts", "company_status", "incorporation_date", "registry_website", "official_website"]),
    ("financials", "Financials", ["revenue", "operating_result", "profit_before_tax", "annual_result", "assets", "equity", "debt", "annual_account_years"]),
    ("leadership", "Leadership", ["leadership_role"]),
    ("locations", "Locations", ["registered_workplace"]),
    ("footprint", "Public activity", ["careers_page", "job_opening", "news_page", "dated_news_item", "contact_email", "contact_phone", "social_handle_facebook", "social_handle_instagram", "social_handle_x", "social_handle_youtube", "social_handle_linkedin", "wikipedia_article_nb", "wikipedia_article_en", "company_page", "company_description", "company_description_from_site"]),
]


def slim(envelope: dict[str, Any]) -> dict[str, Any]:
    claims = envelope.get("claims") or []
    evidence_by_id = {row.get("id"): row for row in envelope.get("evidence") or []}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for claim in claims:
        field = str(claim.get("field"))
        row = {
            "field": field,
            "value": claim.get("value"),
            "state": claim.get("availability"),
            "note": claim.get("note"),
            "sources": [
                {
                    "url": evidence_by_id.get(eid, {}).get("source_url"),
                    "class": evidence_by_id.get(eid, {}).get("source_class"),
                    "retrieved": evidence_by_id.get(eid, {}).get("retrieved_at"),
                    "period": evidence_by_id.get(eid, {}).get("reporting_period"),
                }
                for eid in claim.get("evidence_ids") or []
            ],
        }
        grouped.setdefault(field, []).append(row)
    summary = envelope.get("summary") or {}
    profile = envelope.get("profile") or {}
    return {
        "org": envelope.get("organisation_number"),
        "name": profile.get("name") or "Unnamed registry record",
        "form": profile.get("legal_form"),
        "municipality": profile.get("municipality"),
        "industry": profile.get("industry_label"),
        "employees": profile.get("employees"),
        "website": profile.get("website") or None,
        "headline": summary.get("headline"),
        "sentences": summary.get("sentences") or [],
        "unknowns": summary.get("unknowns") or [],
        "state": envelope.get("state"),
        "groups": grouped,
        "changes": envelope.get("changes") or [],
        "errors": envelope.get("errors") or [],
        "claims": len(claims),
        "requests": (envelope.get("operations") or {}).get("requests"),
        "runtime_ms": (envelope.get("operations") or {}).get("runtime_ms"),
    }


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Signalpost profiles</title>
<style>
:root { --bg:#0f1115; --panel:#171a21; --line:#272b36; --text:#e8eaf0; --muted:#98a1b3; --ok:#5ad19a; --warn:#f0b429; --bad:#ef6f6c; --accent:#6ea8fe; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
header { position:sticky; top:0; z-index:5; background:var(--bg); border-bottom:1px solid var(--line); padding:12px 16px; }
h1 { font-size:16px; margin:0 0 8px; letter-spacing:.02em; }
input[type=search] { width:100%; padding:10px 12px; border-radius:8px; border:1px solid var(--line); background:var(--panel); color:var(--text); font-size:15px; }
.meta { color:var(--muted); font-size:12px; margin-top:6px; }
main { display:grid; grid-template-columns: minmax(260px, 34%) 1fr; gap:16px; padding:16px; max-width:1200px; margin:0 auto; }
@media (max-width: 860px) { main { grid-template-columns:1fr; padding:12px; } }
#list { max-height:70vh; overflow:auto; border:1px solid var(--line); border-radius:10px; background:var(--panel); }
@media (max-width:860px) { #list { max-height:34vh; } }
.item { padding:10px 12px; border-bottom:1px solid var(--line); cursor:pointer; }
.item:hover, .item.active { background:#1e2430; }
.item .n { font-weight:600; }
.item .s { color:var(--muted); font-size:12px; }
#detail { border:1px solid var(--line); border-radius:10px; background:var(--panel); padding:16px; }
#detail h2 { margin:0 0 4px; font-size:20px; }
.badge { display:inline-block; font-size:11px; padding:2px 8px; border-radius:999px; border:1px solid var(--line); color:var(--muted); margin-right:6px; }
.badge.ok { color:var(--ok); border-color:#2c5c48; }
.badge.warn { color:var(--warn); border-color:#5c4a1d; }
.badge.bad { color:var(--bad); border-color:#5c2b2b; }
section { margin-top:18px; }
section h3 { font-size:13px; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); margin:0 0 8px; }
.row { display:flex; flex-wrap:wrap; gap:6px 14px; padding:7px 0; border-bottom:1px dashed var(--line); }
.row:last-child { border-bottom:none; }
.row .f { min-width:170px; color:var(--muted); font-size:13px; }
.row .v { flex:1; min-width:200px; word-break:break-word; }
.row .v a { color:var(--accent); }
.row .note { color:var(--muted); font-size:12px; }
.state { font-size:11px; padding:1px 7px; border-radius:999px; border:1px solid var(--line); color:var(--muted); }
.state.available { color:var(--ok); border-color:#2c5c48; }
.state.not_available { color:var(--warn); border-color:#5c4a1d; }
.state.blocked, .state.failed { color:var(--bad); border-color:#5c2b2b; }
.sentence { margin:0 0 8px; }
.evidence { font-size:12px; color:var(--muted); }
.evidence a { color:var(--accent); word-break:break-all; }
.unknown { color:var(--warn); font-size:13px; }
.change { font-size:13px; padding:6px 0; border-bottom:1px dashed var(--line); }
footer { padding:16px; color:var(--muted); font-size:12px; text-align:center; }
.empty { color:var(--muted); padding:24px; text-align:center; }
</style>
</head>
<body>
<header>
  <h1>Signalpost &middot; Norwegian company profiles</h1>
  <input id="q" type="search" placeholder="Search by company name, organisation number or municipality" autocomplete="off">
  <div class="meta" id="meta"></div>
</header>
<main>
  <div id="list"></div>
  <div id="detail"><div class="empty">Pick a company from the list.</div></div>
</main>
<footer>Generated by the Signalpost runner. Every value links to its source and retrieval time.</footer>
<script>
const DATA = __DATA__;
const GROUPS = __GROUPS__;
const $ = (s) => document.querySelector(s);
const esc = (v) => String(v).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

function fmt(value) {
  if (value === null || value === undefined) return '';
  if (Array.isArray(value)) return value.map(fmt).filter(Boolean).join(', ');
  if (typeof value === 'object') {
    if (value.name && value.role) return esc(value.name) + ' &mdash; ' + esc(value.role) + (value.last_changed ? ' <span class="evidence">(changed ' + esc(value.last_changed) + ')</span>' : '');
    if (value.address) return esc([value.address, value.municipality, value.postal_code].filter(Boolean).join(', '));
    return esc(JSON.stringify(value));
  }
  if (typeof value === 'number' && value > 1000 && Number.isInteger(value)) return value.toLocaleString('en-US');
  return esc(String(value));
}

function stateBadge(state) {
  const cls = state === 'available' ? 'ok' : (state === 'not_available' ? 'warn' : (state === 'failed' || state === 'blocked' ? 'bad' : ''));
  return '<span class="state ' + cls + '">' + esc(state) + '</span>';
}

function renderRows(field, rows) {
  return rows.map(row => {
    const sources = (row.sources || []).filter(s => s && s.url).map(s =>
      '<a href="' + esc(s.url) + '" target="_blank" rel="noopener">' + esc((s.class || 'source')) + '</a>' +
      (s.retrieved ? ' <span class="evidence">retrieved ' + esc(s.retrieved) + '</span>' : '') +
      (s.period ? ' <span class="evidence">period ' + esc(s.period) + '</span>' : '')
    ).join(' &middot; ');
    return '<div class="row"><div class="f">' + esc(row.field.replace(/_/g, ' ')) + '</div>' +
      '<div class="v">' + fmt(row.value) + ' ' + stateBadge(row.state) +
      (row.note ? '<div class="note">' + esc(row.note) + '</div>' : '') +
      (sources ? '<div class="evidence">' + sources + '</div>' : '') + '</div></div>';
  }).join('');
}

function renderDetail(item) {
  if (!item) return '<div class="empty">Pick a company from the list.</div>';
  let out = '<h2>' + esc(item.name) + '</h2>';
  out += '<div><span class="badge">' + esc(item.org) + '</span>' +
    (item.form ? '<span class="badge">' + esc(item.form) + '</span>' : '') +
    (item.municipality ? '<span class="badge">' + esc(item.municipality) + '</span>' : '') +
    '<span class="badge ' + (item.state === 'complete' ? 'ok' : 'warn') + '">' + esc(item.state || '') + '</span>' +
    '<span class="badge">' + item.claims + ' claims</span>' +
    (item.requests ? '<span class="badge">' + item.requests + ' requests</span>' : '') +
    (item.website ? '<a class="badge" href="' + esc(/^https?:/.test(item.website) ? item.website : 'https://' + item.website) + '" target="_blank" rel="noopener">website</a>' : '') +
    '</div>';

  if (item.sentences && item.sentences.length) {
    out += '<section><h3>What the sources say</h3>' + item.sentences.map(s =>
      '<p class="sentence">' + esc(s.text) + ' <span class="evidence">[' + (s.evidence_ids || []).map(esc).join(', ') + ']</span></p>').join('') + '</section>';
  }

  GROUPS.forEach(group => {
    const rows = [];
    group[2].forEach(field => { if (item.groups[field]) rows.push(...item.groups[field]); });
    if (!rows.length) return;
    out += '<section><h3>' + esc(group[1]) + '</h3>' + renderRows(group[0], rows) + '</section>';
  });

  const other = Object.keys(item.groups).filter(f => GROUPS.some(g => g[2].includes(f)) === false);
  if (other.length) {
    out += '<section><h3>Other claims</h3>' + other.map(f => renderRows(f, item.groups[f])).join('') + '</section>';
  }

  if (item.changes && item.changes.length) {
    out += '<section><h3>Changes since previous run</h3>' + item.changes.map(c =>
      '<div class="change"><strong>' + esc(c.type) + '</strong> ' + esc(c.field) + ': ' + fmt(c.value || c.previous_value) + '</div>').join('') + '</section>';
  }
  if (item.unknowns && item.unknowns.length) {
    out += '<section><h3>Not found</h3>' + item.unknowns.map(u =>
      '<div class="unknown">' + esc(u.field) + ': ' + esc(u.state) + ' (' + esc(u.reason || '') + ')</div>').join('') + '</section>';
  }
  if (item.errors && item.errors.length) {
    out += '<section><h3>Source notes</h3>' + item.errors.map(e => '<div class="unknown">' + esc(e.module) + ': ' + esc(e.error) + '</div>').join('') + '</section>';
  }
  return out;
}

let filtered = DATA;
function renderList() {
  const q = $('#q').value.trim().toLowerCase();
  filtered = !q ? DATA : DATA.filter(d =>
    String(d.org).includes(q) || String(d.name).toLowerCase().includes(q) ||
    String(d.municipality || '').toLowerCase().includes(q) || String(d.industry || '').toLowerCase().includes(q));
  $('#list').innerHTML = filtered.length ? filtered.map((d, i) =>
    '<div class="item" data-i="' + i + '"><div class="n">' + esc(d.name) + '</div>' +
    '<div class="s">' + esc(d.org) + ' &middot; ' + esc(d.municipality || 'no municipality') + ' &middot; ' + d.claims + ' claims</div></div>').join('')
    : '<div class="empty">No company matches that search.</div>';
  $('#meta').textContent = filtered.length + ' of ' + DATA.length + ' companies shown';
}

function select(index) {
  document.querySelectorAll('.item').forEach(el => el.classList.remove('active'));
  const el = document.querySelector('.item[data-i="' + index + '"]');
  if (el) el.classList.add('active');
  $('#detail').innerHTML = renderDetail(filtered[index]);
}

$('#q').addEventListener('input', () => { renderList(); });
$('#list').addEventListener('click', (event) => {
  const item = event.target.closest('.item');
  if (item) select(Number(item.dataset.i));
});
renderList();
if (filtered.length) select(0);
</script>
</body>
</html>
"""


def build_viewer(envelopes: list[dict[str, Any]], output: Path) -> Path:
    data = [slim(envelope) for envelope in envelopes]
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    groups = json.dumps([[g[0], g[1], g[2]] for g in GROUPS], ensure_ascii=False)
    page = PAGE.replace("__DATA__", payload).replace("__GROUPS__", groups)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")
    return output


def main() -> None:
    source = Path(sys.argv[1] if len(sys.argv) > 1 else "out/envelopes.jsonl")
    target = Path(sys.argv[2] if len(sys.argv) > 2 else "out/profiles.html")
    envelopes = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    path = build_viewer(envelopes, target)
    print("wrote %s (%d profiles, %d bytes)" % (path, len(envelopes), path.stat().st_size))


if __name__ == "__main__":
    main()
