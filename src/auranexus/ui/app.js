"use strict";
/* AuraNexus demo UI: vanilla JS, no dependencies. All text is inserted with textContent (no innerHTML). */

const PHASES = {
  1: { name: "Prepare", color: "#7c3aed" }, 2: { name: "Design", color: "#2563eb" }, 3: { name: "Build", color: "#0ea5a4" },
  4: { name: "Test", color: "#d97706" }, 5: { name: "Run", color: "#dc2626" },
};
const HIDE_REPORTS = new Set(["dashboard", "nudge", "open_questions", "weekly_summary"]);
const S = { script: null, view: null, cur: 0, persona: null, busy: false };

// ---------------------------------------------------------------------------------------------- helpers
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "style") el.setAttribute("style", v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const $ = (id) => document.getElementById(id);
const pct = (x) => Math.round(Number(x) * 100);
const persona = () => S.script.personas.find((p) => p.key === S.persona);
const stepDef = () => S.script.steps[S.cur];

function authHeaders() {
  const p = persona();
  return { "X-Tenant-Id": S.script.project.tenant, "X-Dev-User": p.email, "X-Dev-Roles": p.roles.join(","), "content-type": "application/json" };
}
async function api(path, opts = {}) {
  const r = await fetch(path, { ...opts, headers: { ...(opts.auth ? authHeaders() : {}), ...(opts.body ? { "content-type": "application/json" } : {}) } });
  const text = await r.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
  if (!r.ok) throw new Error((data && (data.detail || data.message)) || `HTTP ${r.status}`);
  return data;
}
function toast(msg, bad) {
  const t = h("div", { class: "toast" + (bad ? " bad" : ""), style: `position:fixed;bottom:1.2rem;left:50%;transform:translateX(-50%);background:${bad ? "#c62f3e" : "#0f1b3d"};color:#fff;padding:.7rem 1.2rem;border-radius:10px;z-index:99;box-shadow:0 8px 30px rgba(0,0,0,.3);max-width:80vw` }, msg);
  document.body.append(t);
  setTimeout(() => t.remove(), bad ? 6000 : 3200);
}
function setBusy(b) { S.busy = b; document.body.classList.toggle("busy", b); }

function fmtVal(v) {
  if (v === null || v === undefined || v === "") return h("span", { class: "muted" }, "(empty)");
  if (Array.isArray(v)) return v.every((x) => typeof x !== "object") ? v.join(", ") : h("code", {}, JSON.stringify(v));
  if (typeof v === "object") return h("code", {}, JSON.stringify(v));
  if (typeof v === "boolean") return v ? "yes" : "no";
  return String(v);
}
function kv(obj, skip = []) {
  const dl = h("dl", { class: "kv" });
  for (const [k, v] of Object.entries(obj || {})) {
    if (skip.includes(k) || k.endsWith("_inferred")) continue;
    dl.append(h("dt", {}, k.replace(/_/g, " ")), h("dd", {}, fmtVal(v)));
  }
  return dl;
}
function pill(txt, cls) { return h("span", { class: "pill " + (cls || txt) }, txt); }
function bar(value, color) { return h("div", { class: "bar" }, h("i", { style: `width:${Math.max(0, Math.min(100, value))}%;background:${color}` })); }
function scoreColor(v) { return v >= 85 ? "#138a4a" : v >= 70 ? "#b7791f" : "#c62f3e"; }

// ---------------------------------------------------------------------------------------------- renderers
function renderBody(kind, p, ctx = {}) {
  switch (kind) {
    case "gate_decision": return gateBody(p);
    case "scorecard": return scoreBody(p);
    case "phase_assessment": return assessBody(p);
    case "dod_verdict": return dodBody(p);
    case "fs_gap_report": return fsBody(p);
    case "execution_status": return execBody(p);
    case "workshop_quality": return qualityBody(p);
    case "test_sequence": return seqBody(p);
    case "test_tracker": return trackerBody(p);
    case "weekly_summary": return weeklyBody(p);
    default: return kv(p, ["id", "tier", "workshop_id"]);
  }
}
function gateBody(p) {
  const go = p.recommendation === "go";
  return h("div", {}, h("div", { class: "big-verdict " + (go ? "go" : "nogo") }, go ? "GO" : "NO-GO"),
    p.checks.map((c) => h("div", { class: "check" }, h("span", { class: c.passed ? "v" : "x" }, c.passed ? "✓" : "✗"),
      h("div", {}, c.name, !c.passed && c.blockers.length ? h("div", { class: "muted" }, "Blocking: " + c.blockers.join(", ")) : null))),
    go ? h("p", { class: "muted" }, "Every check is green for what is in the register.") : null);
}
function scoreBody(p) {
  const rows = Object.entries(p.dimension_scores || {}).map(([k, v]) => h("div", { class: "score-row" }, k.replace(/_/g, " "), bar(v, scoreColor(v)), Math.round(v)));
  return h("div", {}, h("div", { class: "big-verdict " + p.rating }, `${p.rating}  ${p.total}`), p.trend_vs_previous != null ? h("small", {}, ` ${p.trend_vs_previous >= 0 ? "+" : ""}${p.trend_vs_previous} vs previous`) : null,
    h("p", { class: "muted" }, `Rubric ${p.rubric_version} (${p.profile} weights), hash ${String(p.rubric_hash || "").slice(0, 8)}: frozen at the first scored rehearsal.`), rows,
    (p.overrides_applied || []).length ? h("div", {}, h("h4", {}, "Override rules applied (cap at Red)"), p.overrides_applied.map((o) => h("div", { class: "check" }, h("span", { class: "x" }, "!"), o))) : null,
    p.drivers ? h("div", {}, h("h4", {}, "Biggest drivers"),
      [...(p.drivers.negative || []).map((d) => ["bad", d]), ...(p.drivers.positive || []).map((d) => ["ok", d])].map(([c, d]) => h("div", {}, pill(d.impact > 0 ? "+" + d.impact : d.impact, c), " ", d.dimension.replace(/_/g, " ")))) : null,
    (p.missing_data || []).length ? h("p", { class: "muted" }, "Missing data (lowers confidence): " + p.missing_data.join("; ")) : null);
}
function assessBody(p) {
  const cov = p.requirement_coverage || {};
  return h("div", {}, h("div", {}, pill(`Full ${cov.full || 0}`, "Full"), " ", pill(`Partial ${cov.partial || 0}`, "Partial"), " ", pill(`None ${cov.none || 0}`, "None")),
    kv({ "executed %": p.executed_pct, "pass rate %": p.pass_rate_pct, "blocked scripts": p.blocked_scripts, "open defects": p.open_defects }),
    p.exit_checks ? h("div", {}, h("h4", {}, "Exit criteria"), Object.entries(p.exit_checks).map(([k, v]) => h("div", { class: "check" }, h("span", { class: v ? "v" : "x" }, v ? "✓" : "✗"), k.replace(/_/g, " "))),
      h("div", { class: "big-verdict " + (p.go_no_go_input === "go" ? "go" : "nogo") }, "Go / no-go input: " + p.go_no_go_input.toUpperCase())) : null,
    h("table", { class: "t" }, h("thead", {}, h("tr", {}, ["Scenario", "Total", "Passed", "Failed", "Blocked"].map((x) => h("th", {}, x)))),
      h("tbody", {}, Object.entries(p.per_scenario || {}).map(([k, v]) => h("tr", {}, h("td", {}, k), h("td", {}, v.total), h("td", {}, v.passed), h("td", {}, v.failed), h("td", {}, v.blocked))))));
}
function dodBody(p) {
  return h("div", {}, h("div", { class: "big-verdict " + (p.ready_for_sit ? "go" : "nogo") }, p.ready_for_sit ? "READY FOR SIT" : "BLOCKED"),
    p.checks.map((c) => h("div", { class: "check" }, h("span", { class: c.passed ? "v" : "x" }, c.passed ? "✓" : "✗"), h("div", {}, c.check, c.detail && !c.passed ? h("span", { class: "muted" }, "  (" + c.detail + ")") : null))));
}
function fsBody(p) {
  return h("div", {}, h("table", { class: "t" }, h("thead", {}, h("tr", {}, ["Requirement", "FS section", "Coverage", "Gap"].map((x) => h("th", {}, x)))),
    h("tbody", {}, (p.coverage_matrix || []).map((r) => h("tr", {}, h("td", {}, h("b", {}, r.requirement_id)), h("td", {}, r.fs_section),
      h("td", {}, pill(r.status, /Partial/.test(r.status) ? "Partial" : /Missing|Unmapped/.test(r.status) ? "Missing" : "Full")), h("td", {}, r.gaps))))));
}
function execBody(p) {
  return h("div", {}, h("div", {}, pill(`${p.counts.smooth} smooth`, "smooth"), " ", pill(`${p.counts.watch} watch`, "watch"), " ", pill(`${p.counts.problem} problem`, "problem")),
    kv({ "critical path": (p.critical_path || []).join(" → "), "critical path hours": p.critical_path_hours, "planned hours": p.planned_critical_path_hours,
      "projected overrun (h)": p.projected_overrun_hours, "window at risk": p.window_at_risk }),
    h("table", { class: "t" }, h("thead", {}, h("tr", {}, ["Task", "Classification", "Variance %"].map((x) => h("th", {}, x)))),
      h("tbody", {}, Object.entries(p.tasks || {}).map(([k, v]) => h("tr", {}, h("td", {}, k), h("td", {}, pill(v.classification)), h("td", {}, v.variance_pct ?? "n/a"))))));
}
function qualityBody(p) {
  return h("div", {}, h("div", { class: "big-verdict " + p.rating }, `${p.total} / 100  ${p.rating}`),
    Object.entries(p.scores || {}).map(([k, v]) => h("div", { class: "score-row" }, k.replace(/_/g, " "), bar(v, scoreColor(v)), Math.round(v))),
    p.missing_roles && p.missing_roles.length ? h("p", { class: "muted" }, "Missing client roles: " + p.missing_roles.join(", ")) : null);
}
function weeklyBody(p) {
  const q = p.quality_trend || {};
  return h("div", {}, kv({ "requirements": p.requirements, "quality (per workshop)": q.per_workshop, "cross-team flags": p.cross_team_flags,
    "open conflicts": p.open_conflicts, "template version": p.template_version, "handoff readiness %": p.handoff_readiness_pct }));
}
function seqBody(p) {
  return h("div", {}, (p.waves || []).map((w, i) => h("div", {}, pill("Wave " + (i + 1), "ok"), " ", w.join(", "))), kv({ "critical path": (p.critical_path || []).join(" → ") }));
}
function trackerBody(p) {
  return h("div", {}, h("table", { class: "t" }, h("thead", {}, h("tr", {}, ["Test", "Scenario", "Owner", "Category", "Predecessor", "Status"].map((x) => h("th", {}, x)))),
    h("tbody", {}, (p.rows || []).map((r) => h("tr", {}, h("td", {}, h("b", {}, r.test_id)), h("td", {}, r.scenario), h("td", {}, r.step_owner), h("td", {}, r.category), h("td", {}, (r.predecessor_ids || []).join(", ") || "-"), h("td", {}, r.status))))),
    (p.issues || []).length ? h("p", { class: "muted" }, "Issues: " + p.issues.join("; ")) : null);
}

// ---------------------------------------------------------------------------------------------- cards
function cpFor(proposalId) { return (S.view.checkpoints || []).find((c) => c.proposal.id === proposalId); }
function canDecide(cp) { return persona().roles.some((r) => cp.approver_roles.includes(r)); }

function proposalCard(prop) {
  const live = S.view.proposals.find((x) => x.id === prop.id) || prop;
  const cp = cpFor(live.id);
  const conf = Number(live.confidence);
  const open = live.status === "pending" || live.status === "deferred";
  const flags = (live.flags || []).map((f) => h("span", { class: "flag " + (f === "quote_not_verified" ? "bad" : "") }, f.replace(/_/g, " ")));
  const title = live.payload.proposal_id ? `${live.payload.proposal_id} · ${live.title}` : live.title;
  const card = h("div", { class: `card proposal ${live.status}` },
    h("div", { class: "head" }, h("h4", {}, title), h("span", { class: "kind" }, live.kind.replace(/_/g, " ")), h("span", { class: "status " + live.status }, live.status === "applied" ? "approved" : live.status)),
    h("div", { class: "meta" }, h("span", {}, "by ", h("b", {}, live.agent_id)),
      h("span", { class: "conf " + (conf < 0.7 ? "low" : conf < 0.85 ? "mid" : "") }, "confidence ", h("b", {}, pct(conf) + "%"), bar(pct(conf), "")), h("span", {}, "tier ", live.tier), flags),
    renderBody(live.kind, live.payload),
    (live.evidence || []).length ? h("div", { class: "evidence" }, live.evidence.map((e) => h("blockquote", {}, e.quote || e.source_ref, h("cite", {}, [e.speaker, e.timestamp, e.quote && e.source_ref ? e.source_ref : (e.quote ? "" : "reference")].filter(Boolean).join(" · "))))) : null);
  const lastDec = [...S.view.audit].reverse().find((a) => a.action.startsWith("checkpoint.") && a.data && a.data.proposal_id === live.id);
  if (lastDec) card.append(h("div", { class: "decision-note" }, h("b", {}, lastDec.actor), ` · ${lastDec.action.replace("checkpoint.", "")} as ${lastDec.data.role}`, lastDec.data.reason ? ` · "${lastDec.data.reason}"` : "", ` · ${lastDec.data.approvals}/${lastDec.data.required} approvals`));
  if (open && cp) card.append(decisionButtons(cp, live));
  return card;
}
function decisionButtons(cp, prop) {
  const ok = canDecide(cp);
  const tip = ok ? "" : `Needs role: ${cp.approver_roles.join(" / ")}. You are acting as ${persona().title}.`;
  const mk = (label, cls, outcome) => h("button", { class: `btn sm ${cls}`, title: tip, disabled: !ok, "data-keep": "1", onclick: () => openDecision(cp, prop, outcome) }, label);
  return h("div", { class: "card-actions" }, mk("Approve", "good", "approve"), mk("Modify", "", "modify"), mk("Reject", "bad", "reject"), mk("Defer", "", "defer"),
    h("span", { class: "muted", style: "align-self:center;font-size:.82rem" }, `${cp.code} · needs ${cp.approver_roles.join(" / ")} · approvals ${cp.approvals}`));
}

function reportCard(r) {
  const body = renderBody(r.kind, r);
  return h("div", { class: "card" }, h("div", { class: "head", style: "display:flex;gap:.6rem;align-items:baseline" }, h("h4", { style: "margin:0;flex:1" }, r.title || (r.kind.replace(/_/g, " ") + (r.id ? " · " + r.id : ""))),
    h("span", { class: "kind" }, r.kind.replace(/_/g, " ")), h("span", { class: "status draft" }, "informational")),
  r.kind === "observation" ? h("div", {}, h("div", { class: "meta" }, pill(r.classification), h("span", {}, r.task_id), h("span", {}, r.category)), h("p", {}, r.what_happened),
    (r.evidence || []).map((e) => h("blockquote", { style: "margin:.3rem 0;padding:.3rem .7rem;border-left:3px solid #0ea5a4;background:#f1fbfa" }, e.quote, h("cite", { style: "display:block;font-size:.78rem;color:#66728a" }, [e.speaker, e.timestamp].join(" · "))))) : body);
}

// ---------------------------------------------------------------------------------------------- views
function renderNav() {
  const nav = $("steps");
  nav.replaceChildren();
  let lastPhase = 0;
  S.script.steps.forEach((s, i) => {
    if (s.phase !== lastPhase) { lastPhase = s.phase; nav.append(h("div", { class: "phase-title" }, h("i", { style: `background:${PHASES[s.phase].color}` }), `Phase ${s.phase} · ${PHASES[s.phase].name}`)); }
    const d = S.view.done[s.id] || {};
    const need = (s.run_label ? 1 : 0) + (s.human.length ? 1 : 0);
    const got = (s.run_label && d.ran ? 1 : 0) + (s.human.length && d.human ? 1 : 0);
    const cls = need && got === need ? "done" : got ? "partial" : "";
    nav.append(h("div", { class: `step ${cls} ${i === S.cur ? "active" : ""}`, onclick: () => { S.cur = i; render(); } }, h("div", { class: "dot" }, cls === "done" ? "✓" : cls === "partial" ? "•" : ""), h("div", {}, h("b", {}, s.title))));
  });
}
function renderHeader() {
  const s = stepDef(), d = S.view.done[s.id] || {};
  const box = $("stepHeader");
  box.replaceChildren(...[
    h("span", { class: "pill", style: `background:${PHASES[s.phase].color}` }, `Phase ${s.phase} · ${PHASES[s.phase].name}`),
    h("h2", {}, s.title), h("p", { class: "story" }, s.story),
    s.agents.length ? h("div", { class: "agents" }, s.agents.map((a) => h("span", { class: "chip agent" }, a))) : null,
    h("div", { class: "actions" },
      s.run_label ? h("button", { class: "btn accent", "data-keep": "1", onclick: () => runStep(s) }, "▶ " + s.run_label + (d.ran ? "  (run again)" : "")) : null,
      s.human.length ? h("button", { class: "btn good", "data-keep": "1", onclick: () => humanStep(s) }, "✓ " + (s.human_label || "Perform human decisions")) : null,
      s.id === "p4-tracker" ? h("button", { class: "btn", "data-keep": "1", onclick: downloadTracker }, "⬇ Excel tracker") : null,
      S.cur < S.script.steps.length - 1 ? h("button", { class: "btn", "data-keep": "1", onclick: () => { S.cur++; render(); window.scrollTo({ top: 0, behavior: "smooth" }); } }, "Next step ›") : null),
    s.insight ? h("div", { class: "talk" }, h("b", {}, "Talking point  "), s.insight) : null].filter(Boolean));
}
function renderResult() {
  const s = stepDef(), box = $("result"), d = (S.view.deltas || {})[s.id];
  box.replaceChildren();
  if (!d) {
    const kinds = new Set(s.human.map((x) => x.kind));
    const pending = S.view.proposals.filter((p) => kinds.has(p.kind));
    if (!s.run_label && pending.length) { box.append(h("div", { class: "section-title" }, "Items for this checkpoint", h("span", { class: "count" }, pending.length))); pending.forEach((p) => box.append(proposalCard(p))); }
    else if (s.run_label) box.append(h("div", { class: "card empty" }, "Press ", h("b", {}, s.run_label), " to trigger this step. Results appear here."));
    else box.append(h("div", { class: "card empty" }, "Nothing waiting yet: run the earlier steps first."));
    return;
  }
  if (d.performed) {
    box.append(h("div", { class: "section-title" }, "Human decisions just made", h("span", { class: "count" }, d.performed.length)));
    box.append(h("div", { class: "card" }, d.performed.map((x) => h("div", { class: "check" }, pill(x.outcome === "approve" ? "approved" : x.outcome === "reject" ? "rejected" : x.outcome, x.outcome === "approve" ? "ok" : x.outcome === "reject" ? "bad" : "warn"),
      h("div", {}, h("b", {}, x.persona), ` (${x.title}) · ${x.kind.replace(/_/g, " ")}: ${x.item}`, x.reason ? h("div", { class: "muted" }, "Reason: " + x.reason) : null))),
    d.skipped && d.skipped.length ? h("p", { class: "muted" }, "Skipped: " + d.skipped.map((x) => `${x.kind} ${x.pid} (${x.why})`).join("; ")) : null));
  }
  if ((d.runs || []).length) {
    box.append(h("div", { class: "section-title" }, "Agent runs", h("span", { class: "count" }, d.runs.length)));
    box.append(h("div", { class: "card" }, d.runs.map((r) => h("div", { class: "check" }, pill(r.status === "succeeded" ? "ok" : r.status, r.status === "succeeded" ? "ok" : "bad"),
      h("div", {}, h("b", {}, r.agent_id), `  ${r.proposals.length} proposal(s)`, (r.dropped || []).length ? h("span", { class: "flag bad" }, `${r.dropped.length} dropped by guardrails`) : null, r.error ? h("div", { class: "muted" }, r.error) : null)))));
  }
  if ((d.proposals || []).length) {
    box.append(h("div", { class: "section-title" }, "Agent proposals (nothing is in the register until a human approves)", h("span", { class: "count" }, d.proposals.length)));
    d.proposals.forEach((p) => box.append(proposalCard(p)));
  }
  const reps = (d.reports || []).filter((r) => !HIDE_REPORTS.has(r.kind));
  if (reps.length) { box.append(h("div", { class: "section-title" }, "Informational output", h("span", { class: "count" }, reps.length))); reps.forEach((r) => box.append(reportCard(r))); }
  if ((d.notifications || []).length) {
    box.append(h("div", { class: "section-title" }, "Notifications sent", h("span", { class: "count" }, d.notifications.length)));
    box.append(h("div", { class: "card" }, d.notifications.map(notifRow)));
  }
  if (d.audit_added) box.append(h("p", { class: "muted" }, `${d.audit_added} audit entries written in this step.`));
}
function renderQueue() {
  const q = $("queue"), cps = S.view.checkpoints;
  q.replaceChildren(h("h3", {}, "Waiting for a human", h("span", { class: "count chip" }, cps.length)));
  if (!cps.length) q.append(h("div", { class: "empty" }, "No open checkpoints."));
  cps.forEach((cp) => {
    const prop = S.view.proposals.find((p) => p.id === cp.proposal.id);
    const ok = canDecide(cp);
    q.append(h("div", { class: "q-item" + (cp.overdue ? " overdue" : "") },
      h("div", {}, h("div", { class: "t1" }, cp.proposal.title), h("div", { class: "t2" }, `${cp.code} · ${cp.proposal.kind.replace(/_/g, " ")} · tier ${cp.tier} · approvals ${cp.approvals} · needs ${cp.approver_roles.join(" / ")}`)),
      prop ? h("div", { class: "q-btns" }, ["approve", "modify", "reject", "defer"].map((o) => h("button", { class: `btn sm ${o === "approve" ? "good" : o === "reject" ? "bad" : ""}`, disabled: !ok, "data-keep": "1", title: ok ? "" : `Needs role: ${cp.approver_roles.join(" / ")}`, onclick: () => openDecision(cp, prop, o) }, o))) : null));
  });
}
function notifRow(n) {
  return h("div", { class: "notif " + (n.severity || "") }, h("span", { class: "to" }, "→ " + n.recipient), "  ", h("small", {}, n.created_by), h("div", {}, n.subject), h("p", {}, n.body));
}
function renderSide() {
  const notes = [...S.view.notifications].reverse().slice(0, 6);
  $("notes").replaceChildren(...(notes.length ? notes.map(notifRow) : [h("div", { class: "empty" }, "None yet.")]));
  $("registerCounts").replaceChildren(...(Object.keys(S.view.register).length ? Object.entries(S.view.register).map(([k, v]) => h("span", { class: "chip" }, k.replace(/_/g, " ") + " ", h("b", {}, v))) : [h("span", { class: "empty" }, "Empty: agents have only proposed so far.")]));
  $("auditTicker").replaceChildren(...S.view.audit.slice(-7).reverse().map((a) => auditRow(a)));
  const ok = S.view.audit_ok;
  $("chainState").replaceChildren(h("span", { class: "badge " + (ok ? "" : "bad") }, ok ? "✓ intact" : "✗ broken"));
  $("auditBadge").textContent = S.view.audit_total;
}
function auditRow(a) {
  return h("div", { class: "audit-row" }, h("b", {}, "#" + a.seq), h("div", {}, `${a.actor.split("@")[0]} · ${a.action} · ${a.entity_id}`), h("div", { class: "hash" }, `${(a.prev_hash || "genesis").slice(0, 8)} → ${a.hash.slice(0, 8)}`));
}
function render() {
  if (!S.script || !S.view) return;
  $("persona").value = S.persona;
  renderNav(); renderHeader(); renderResult(); renderQueue(); renderSide();
}
async function refresh() { S.view = await api("/demo/view"); render(); }

// ---------------------------------------------------------------------------------------------- actions
async function runStep(s) {
  try { setBusy(true); await api(`/demo/steps/${s.id}/run`, { method: "POST" }); } catch (e) { toast(e.message, true); } finally { setBusy(false); await refresh(); }
}
async function humanStep(s) {
  try {
    setBusy(true);
    const r = await api(`/demo/steps/${s.id}/human`, { method: "POST" });
    if (!r.performed.length) toast("Nothing to decide yet: " + (r.skipped[0] ? r.skipped[0].why : "run the step first"), true);
  } catch (e) { toast(e.message, true); } finally { setBusy(false); await refresh(); }
}
function openDecision(cp, prop, outcome) {
  const dlg = $("decision");
  $("dTitle").textContent = `${outcome[0].toUpperCase() + outcome.slice(1)}: ${prop.title}`;
  $("dSub").textContent = `Checkpoint ${cp.code} · deciding as ${persona().name} (${persona().title})`;
  const needReason = outcome !== "approve";
  $("dReasonHint").textContent = needReason ? "(required)" : "(optional)";
  $("dReason").value = "";
  $("dModifyWrap").hidden = outcome !== "modify";
  $("dPayload").value = JSON.stringify(prop.payload, null, 2);
  $("dError").textContent = "";
  dlg.dataset.cp = cp.checkpoint_id; dlg.dataset.outcome = outcome; dlg.dataset.need = needReason ? "1" : "";
  dlg.showModal();
}
async function submitDecision(ev) {
  ev.preventDefault();
  const dlg = $("decision"), outcome = dlg.dataset.outcome, reason = $("dReason").value.trim();
  if (dlg.dataset.need && !reason) { $("dError").textContent = "A written reason is required."; return; }
  const body = { outcome, reason };
  if (outcome === "modify") { try { body.modified_payload = JSON.parse($("dPayload").value); } catch { $("dError").textContent = "Payload is not valid JSON."; return; } }
  try {
    await api(`/v1/checkpoints/${dlg.dataset.cp}/decision`, { method: "POST", auth: true, body: JSON.stringify(body) });
    dlg.close(); toast("Decision recorded and audited"); await refresh();
  } catch (e) { $("dError").textContent = e.message; }
}
async function downloadTracker() {
  try {
    const r = await fetch(`/v1/projects/${S.script.project.id}/exports/test-tracker.xlsx`, { headers: authHeaders() });
    if (!r.ok) throw new Error("Approve the tracker first (no test cases in the register yet)");
    const b = await r.blob(); const a = h("a", { href: URL.createObjectURL(b), download: "test-tracker.xlsx" }); document.body.append(a); a.click(); a.remove();
  } catch (e) { toast(e.message, true); }
}
function drawer(title, body) { $("drawerTitle").textContent = title; $("drawerBody").replaceChildren(body); $("drawer").showModal(); }
async function showAudit() {
  await refresh();
  const v = await api("/v1/audit/verify", { auth: true }).catch(() => null);
  drawer(`Audit trail · ${S.view.audit_total} entries`, h("div", {},
    h("p", {}, "Every agent run, proposal and human decision is appended to a SHA-256 hash chain (each entry commits to the previous one) and the database forbids updates or deletes. ",
      v ? pill(v.ok ? "chain verified" : "CHAIN BROKEN at #" + v.first_bad_seq, v.ok ? "ok" : "bad") : null),
    h("table", { class: "t" }, h("thead", {}, h("tr", {}, ["#", "Actor", "Action", "Entity", "prev → hash"].map((x) => h("th", {}, x)))),
      h("tbody", {}, [...S.view.audit].reverse().map((a) => h("tr", {}, h("td", {}, a.seq), h("td", {}, a.actor), h("td", {}, a.action), h("td", {}, a.entity_id), h("td", { class: "mono" }, `${(a.prev_hash || "genesis").slice(0, 8)} → ${a.hash.slice(0, 8)}`)))))));
}
async function showThread() {
  const t = await api("/demo/thread");
  drawer("One requirement, five phases: REQ-FI-019", h("div", {},
    h("p", { class: "muted" }, "Multi-currency tax translation rounding. Follow what the platform recorded at each phase and where the loop catches it."),
    h("div", { class: "thread" }, t.map((n) => h("div", { class: `node ${n.state}` }, h("div", { class: "ph" }, n.phase), h("h4", {}, n.title), h("p", {}, n.detail))))));
}
async function resetDemo() {
  if (!confirm("Reset the demo to its starting state?")) return;
  await api("/demo/reset", { method: "POST" }); S.cur = 0; await refresh(); toast("Demo reset");
}

// ---------------------------------------------------------------------------------------------- boot
async function boot() {
  S.script = await api("/demo/script");
  $("projName").textContent = S.script.project.name;
  const sel = $("persona");
  S.script.personas.forEach((p) => sel.append(h("option", { value: p.key }, `${p.name} · ${p.title}`)));
  S.persona = "pm"; sel.value = "pm";
  sel.addEventListener("change", () => { S.persona = sel.value; render(); });
  $("btnAudit").addEventListener("click", showAudit);
  $("btnThread").addEventListener("click", showThread);
  $("btnReset").addEventListener("click", resetDemo);
  $("drawerClose").addEventListener("click", () => $("drawer").close());
  $("dCancel").addEventListener("click", () => $("decision").close());
  $("decisionForm").addEventListener("submit", submitDecision);
  await refresh();
  // deep links: #<step-id> selects a step, #trace opens the defect trace, #audit opens the audit trail
  const hash = decodeURIComponent(location.hash.slice(1));
  const idx = S.script.steps.findIndex((x) => x.id === hash);
  if (idx >= 0) { S.cur = idx; render(); }
  if (hash === "trace") await showThread();
  if (hash === "audit") await showAudit();
}
boot().catch((e) => { document.body.prepend(h("pre", { style: "padding:1rem;color:#c62f3e" }, "Failed to load the demo: " + e.message)); });
