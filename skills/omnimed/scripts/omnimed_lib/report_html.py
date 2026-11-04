# The browser view of a comparison: the website's layout, as one local file.
# A conversation (a run and its follow-ups, `--after`) is one page: each turn's
# question, scoreboard and model boxes in order, earlier turns collapsed, like
# the website's chat.
#
# Boxes, colours, fonts and the grid rule are taken from the OmniMed site
# (omnimed-frontend: index.css variables, Chat.css .mbox, gridCols()), so a run
# from the skill reads like a run on the site. Nothing is uploaded: the page is
# a file in the run directory, opened from disk.
#
# All run data is embedded as JSON and drawn by the page's own script. Model
# answers are untrusted text: they are rendered as Markdown only through
# DOMPurify, and shown as plain text if either library fails to load (offline).

import json

from . import models
from . import report

MARKED = "https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js"
PURIFY = "https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.1.6/purify.min.js"


def _payload(comp: dict) -> dict:
    answers = []
    for a in comp.get("answers", []):
        spec = models.MODELS.get(a.get("model")) or {}
        v = a.get("verification") or {}
        j = a.get("judge") or {}
        since = (a.get("grounding") or {}).get("since")
        flagged = []
        for c in v.get("citations") or []:
            support = (c.get("support") or {}).get("support")
            kind = ("fabricated" if c.get("exists") is False else
                    "retracted" if c.get("retracted") else
                    "offtopic" if support in ("mismatched", "unrelated") else
                    "unchecked" if c.get("exists") is None else None)
            if not kind and since and c.get("exists") and str(c.get("year", "")).isdigit() \
                    and int(c["year"]) < since:
                kind = "older"
            if kind:
                flagged.append({"id": c.get("id") or c.get("raw"), "kind": kind, "year": c.get("year"),
                                "since": since,
                                "title": (c.get("title") or "")[:160],
                                "reason": ((c.get("support") or {}).get("reason") or "")[:180],
                                "url": c.get("url")})
        answers.append({
            "model": a.get("model"), "label": a.get("label"), "status": a.get("status"),
            "error": a.get("error"), "detail": a.get("detail"),
            "seconds": a.get("seconds"), "source": a.get("source"),
            "served_model": a.get("served_model"), "text": a.get("text") or "",
            "truncated": bool(a.get("truncated")),
            "color": spec.get("color", "#475569"), "bg": spec.get("bg", "#f1f5f9"),
            "tier": spec.get("tier"),
            "cites": {k: v.get(k) for k in ("checked", "verified", "fabricated", "mismatched",
                                            "retracted", "unresolved")},
            "unsourced": {k: (a.get("unsourced") or {}).get(k) for k in ("checked", "none_found")},
            "flagged": flagged,
            "papers": report.papers_given(a.get("grounding")),
            "fulltext": sum(1 for c in v.get("citations") or []
                            if (c.get("support") or {}).get("source") == "full text"),
            "judge": ({"label": j.get("judge_label") or j.get("judge"),
                       **(j.get("score") or {})} if j.get("score") else
                      ({"error": j.get("error")} if j else None)),
        })
    return {"question": comp.get("question", ""), "run_id": comp.get("run_id", ""),
            "created": comp.get("created", ""), "answers": answers,
            "candidates": comp.get("candidates") or [], "verdict": comp.get("verdict"),
            "preprints": comp.get("preprints"),
            "judge_note": comp.get("judge_note")}


def render_conversation(comps: list[dict]) -> str:
    """One page for a whole conversation, oldest turn first."""
    data = json.dumps({"turns": [_payload(c) for c in comps]},
                      ensure_ascii=False).replace("</", "<\\/")
    return _TEMPLATE.replace("__DATA__", data).replace("__TITLE__", "OmniMed comparison") \
                    .replace("__MARKED__", MARKED).replace("__PURIFY__", PURIFY)


def render(comp: dict) -> str:
    return render_conversation([comp])


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Space+Grotesk:wght@500;600&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #ffffff; --bg-secondary: #eeece7; --surface: #ffffff; --border: #d9d9dd;
  --text: #212121; --text-muted: #616161; --text-slate: #75758a;
  --panel-bg: #f8f8fb; --panel-border: rgba(0,0,0,0.08);
  --coral: #ff7759; --action-blue: #1863dc; --deep-green: #003c33; --pale-green: #edfce9;
  --pale-blue: #f1f5ff; --primary: #17171c;
  --bad: #b42318; --bad-bg: #fef3f2; --warn: #b54708; --warn-bg: #fffaeb; --ok: #067647; --ok-bg: #ecfdf3;
  --font-display: 'Space Grotesk', Inter, ui-sans-serif, system-ui, sans-serif;
  --font-body: Inter, -apple-system, ui-sans-serif, system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #0d0d10; --bg-secondary: #17171c; --surface: #17171c; --border: rgba(255,255,255,0.1);
    --text: #f0f0f2; --text-muted: #93939f; --panel-bg: #141418; --panel-border: rgba(255,255,255,0.08);
    --pale-green: #0f2a22; --pale-blue: #131a2b; --primary: #f0f0f2;
    --bad: #fda29b; --bad-bg: #2b1513; --warn: #fec84b; --warn-bg: #2a2111; --ok: #75e0a7; --ok-bg: #0f2a1d;
  }
}
:root[data-theme="dark"] {
  --bg: #0d0d10; --bg-secondary: #17171c; --surface: #17171c; --border: rgba(255,255,255,0.1);
  --text: #f0f0f2; --text-muted: #93939f; --panel-bg: #141418; --panel-border: rgba(255,255,255,0.08);
  --pale-green: #0f2a22; --pale-blue: #131a2b; --primary: #f0f0f2;
  --bad: #fda29b; --bad-bg: #2b1513; --warn: #fec84b; --warn-bg: #2a2111; --ok: #75e0a7; --ok-bg: #0f2a1d;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font-family: var(--font-body); font-size: 14px; line-height: 1.55; }
header { padding: 20px 24px 14px; border-bottom: 1px solid var(--border); }
.brand { font-family: var(--font-display); font-weight: 600; font-size: 15px; letter-spacing: .01em; }
.brand span { color: var(--coral); }
h1 { font-family: var(--font-display); font-weight: 600; font-size: 22px; line-height: 1.3; margin: 8px 0 4px; }
.meta { color: var(--text-slate); font-size: 12px; }
main { padding: 16px 24px 40px; display: flex; flex-direction: column; gap: 16px; }
.toolbar { display: flex; gap: 8px; flex-wrap: wrap; }
.btn { border: 1px solid var(--coral); color: var(--coral); background: transparent; border-radius: 9999px; padding: 6px 16px; font: 500 13px var(--font-body); cursor: pointer; }
.btn:hover { background: rgba(255,119,89,.08); }
details.panel { background: var(--panel-bg); border: 1px solid var(--panel-border); border-radius: 8px; padding: 10px 14px; }
details.panel > summary { cursor: pointer; font-weight: 600; font-family: var(--font-display); }
.note { color: var(--text-muted); font-size: 12px; margin: 8px 0 0; }
.tablewrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 13px; margin-top: 8px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); vertical-align: top; }
th { font-weight: 600; color: var(--text-muted); font-size: 12px; }
.grid { display: grid; grid-template-columns: repeat(var(--cols, 3), minmax(0, 1fr)); gap: 12px; }
@media (max-width: 1100px) { .grid { grid-template-columns: repeat(min(var(--cols, 3), 2), minmax(0, 1fr)); } }
@media (max-width: 720px) { .grid { grid-template-columns: minmax(0, 1fr); } header, main { padding-left: 16px; padding-right: 16px; } }
.mbox { background: var(--panel-bg); border: 1px solid var(--panel-border); border-radius: 8px; display: flex; flex-direction: column; min-width: 0; overflow: hidden; }
.mbox-head { display: flex; align-items: center; gap: 8px; padding: 7px 10px; border-bottom: 2px solid; flex-wrap: wrap; }
.mbadge { border-radius: 5px; padding: 3px 8px; font-size: 12px; font-weight: 600; letter-spacing: .02em; border: 1px solid rgba(0,0,0,.12); }
.mhint { font-size: 10px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--text-slate); }
.mtime { margin-left: auto; color: var(--text-slate); font-size: 11px; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; padding: 8px 10px 0; }
.chip { font-size: 11px; font-weight: 600; border-radius: 9999px; padding: 2px 9px; background: var(--bg-secondary); color: var(--text-muted); }
.chip.ok { background: var(--ok-bg); color: var(--ok); }
.chip.bad { background: var(--bad-bg); color: var(--bad); }
.chip.warn { background: var(--warn-bg); color: var(--warn); }
.flags { margin: 0 10px 10px; padding: 8px 10px; border-radius: 6px; background: var(--bad-bg); font-size: 12px; }
.flags ul { margin: 4px 0 0; padding-left: 18px; }
.flags b { color: var(--bad); }
.mbody { padding: 10px 12px; overflow: auto; max-height: 70vh; overflow-wrap: anywhere; }
.expanded .mbody { max-height: none; }
.mbody h1, .mbody h2, .mbody h3, .mbody h4 { font-family: var(--font-display); font-size: 15px; margin: 14px 0 6px; }
.mbody table { font-size: 12px; display: block; overflow-x: auto; }
.mbody th, .mbody td { min-width: 90px; }
.mbody code { font-family: var(--font-mono); font-size: 12px; }
.mbody pre.plain { white-space: pre-wrap; font-family: var(--font-body); margin: 0; }
.mjudge { border-top: 1px solid var(--panel-border); padding: 8px 12px; font-size: 12px; color: var(--text-muted); }
.mjudge b { color: var(--text); }
.failed { padding: 14px 12px; color: var(--bad); font-weight: 500; }
.conclusion { border: 1px solid var(--coral); }
.conclusion .mbox-head { border-bottom-color: var(--coral); }
.conclusion .mbadge { background: var(--coral); color: #fff; border: none; }
.empty { color: var(--text-slate); font-style: italic; }
a { color: var(--action-blue); }
.turn { display: flex; flex-direction: column; gap: 12px; }
.turn + .turn { border-top: 1px solid var(--border); padding-top: 16px; }
.turn > summary, .turn-head { cursor: pointer; list-style: none; }
.turn-head { cursor: default; }
.turn-q { font-family: var(--font-display); font-weight: 600; font-size: 18px; line-height: 1.35; margin: 2px 0; }
.turn-n { font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--coral); }
details.turn:not([open]) > summary .turn-q { font-size: 15px; color: var(--text-muted); }
details.turn > summary .turn-q::after { content: ' · show'; color: var(--text-slate); font-size: 12px; font-weight: 400; }
details.turn[open] > summary .turn-q::after { content: ' · hide'; }
</style>
</head>
<body>
<header>
  <div class="brand">Omni<span>Med</span> · model comparison</div>
  <h1 id="q"></h1>
  <div class="meta" id="meta"></div>
</header>
<main>
  <div class="toolbar">
    <button class="btn" id="expand" type="button">Expand all answers</button>
  </div>
  <div id="turns"></div>
</main>
<script type="application/json" id="data">__DATA__</script>
<script src="__MARKED__"></script>
<script src="__PURIFY__"></script>
<script>
(function () {
  var D = JSON.parse(document.getElementById('data').textContent);
  var canRender = !!(window.marked && window.DOMPurify);

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function md(target, text) {
    if (canRender) {
      target.innerHTML = DOMPurify.sanitize(marked.parse(text || ''));
      target.querySelectorAll('a').forEach(function (a) { a.target = '_blank'; a.rel = 'noopener noreferrer'; });
    } else {
      target.appendChild(el('pre', 'plain', text || ''));
    }
  }
  function row(table, cells, head) {
    var tr = el('tr');
    cells.forEach(function (c) { tr.appendChild(el(head ? 'th' : 'td', null, c)); });
    table.appendChild(tr);
  }
  // Same rule as the site's gridCols(): keeps boxes wide enough to read.
  function gridCols(total) { return total <= 2 ? total : (total <= 4 ? 2 : 3); }

  var T = D.turns || [];
  var first = T[0] || {question: '', answers: []}, last = T[T.length - 1] || first;
  document.getElementById('q').textContent = first.question;
  document.getElementById('meta').textContent =
    (T.length > 1 ? T.length + ' questions · ' : '') + last.answers.length + ' models' +
    (last.created ? ' · updated ' + last.created.replace('T', ' ').slice(0, 16) + ' UTC' : '');
  document.title = 'OmniMed · ' + first.question.slice(0, 60);

  function panel(title, open, note) {
    var d = el('details', 'panel'); d.open = open;
    d.appendChild(el('summary', null, title));
    var wrap = el('div', 'tablewrap'), table = el('table');
    wrap.appendChild(table); d.appendChild(wrap);
    if (note) d.appendChild(el('p', 'note', note));
    return {node: d, table: table};
  }

  function drawTurn(t, n, isLast) {
    var turn = el(isLast ? 'section' : 'details', 'turn');
    var head = el(isLast ? 'div' : 'summary', isLast ? 'turn-head' : null);
    head.appendChild(el('div', 'turn-n', T.length > 1 ? 'Question ' + n : 'Question'));
    head.appendChild(el('div', 'turn-q', t.question));
    turn.appendChild(head);

    // Scoreboard
    var sp = panel('Scoreboard', isLast, 'Citation columns come from PubMed, Crossref and DataCite lookups: deterministic, no AI. The judge score is one model\'s rubric opinion, always from a different provider than the answer, blinded to who wrote it. It is noisy. Wet-lab results are the ground truth.');
    var score = sp.table;
    row(score, ['Model', 'Citations real', 'Fabricated', 'Off-topic', 'Retracted', 'Uncited claims w/o literature', 'Judge', 'Time'], true);
    t.answers.forEach(function (a) {
      var c = a.cites || {}, ok = a.status === 'ok', has = ok && c.checked;
      row(score, [
        a.label + (a.truncated ? ' (cut off)' : ''),
        !ok ? 'failed: ' + a.error : (c.checked ? c.verified + ' / ' + c.checked : 'none cited'),
        has ? String(c.fabricated) : '—', has ? String(c.mismatched) : '—', has ? String(c.retracted || 0) : '—',
        ok && a.unsourced && a.unsourced.checked ? a.unsourced.none_found + ' of ' + a.unsourced.checked : '—',
        ok && a.judge && a.judge.overall ? a.judge.overall + '/10' : '—',
        a.seconds ? a.seconds + 's' : '—'
      ]);
    });
    if (t.judge_note) sp.node.appendChild(el('p', 'note', t.judge_note));
    turn.appendChild(sp.node);

    // Candidates
    var cp = panel('Candidates, checked against the literature', false, 'Counts come from PubMed and ClinicalTrials.gov, not from the answers. Many models naming a candidate is weak evidence on its own.');
    var cands = cp.table, labels = {};
    t.answers.forEach(function (a) { labels[a.model] = a.label; });
    if (!t.candidates.length) {
      cands.appendChild(el('caption', 'empty', 'No miRNA/lncRNA candidates were named.'));
    } else {
      row(cands, ['Candidate', 'Named by', 'PubMed papers', 'Since 2021', 'Trials (as intervention)'], true);
      t.candidates.forEach(function (p) {
        row(cands, [p.name, (p.proposed_by || []).map(function (m) { return labels[m] || m; }).join(', '),
          p.papers == null ? 'lookup failed' : String(p.papers),
          p.papers_recent == null ? '—' : String(p.papers_recent),
          p.trials == null ? 'lookup failed' : String(p.trials)]);
      });
    }
    turn.appendChild(cp.node);

    // Latest preprints, for the conclusion: OmniMed's search, not the models'
    if (t.preprints) turn.appendChild(drawPreprints(t.preprints).node);

    // Model boxes + conclusion, laid out like the site
    var grid = el('div', 'grid');
    grid.style.setProperty('--cols', gridCols(t.answers.length + 1));
    t.answers.forEach(function (a) { grid.appendChild(drawBox(a)); });
    grid.appendChild(drawConclusion(t.verdict));
    turn.appendChild(grid);
    return turn;
  }

  function drawBox(a) {
    var box = el('section', 'mbox');
    var head = el('div', 'mbox-head');
    head.style.borderBottomColor = a.color;
    head.appendChild(el('span', 'mhint', 'Model'));
    var badge = el('span', 'mbadge', a.label);
    badge.style.background = a.bg; badge.style.color = a.color;
    head.appendChild(badge);
    if (a.source && a.source !== 'api') head.appendChild(el('span', 'mhint', a.source));
    if (a.seconds) head.appendChild(el('span', 'mtime', a.seconds + 's'));
    box.appendChild(head);

    if (a.status !== 'ok') {
      box.appendChild(el('div', 'failed', 'No answer: ' + a.error));
      if (a.detail) box.appendChild(el('div', 'mjudge', a.detail));
      return box;
    }

    var chips = el('div', 'chips'), c = a.cites || {};
    function chip(text, kind) { chips.appendChild(el('span', 'chip ' + (kind || ''), text)); }
    if (!c.checked) chip('no citations');
    else {
      chip(c.verified + '/' + c.checked + ' citations real', c.fabricated ? '' : 'ok');
      if (c.fabricated) chip(c.fabricated + ' fabricated', 'bad');
      if (c.mismatched) chip(c.mismatched + ' off-topic', 'warn');
      if (c.retracted) chip(c.retracted + ' retracted', 'bad');
    }
    if (a.papers) chip(a.papers);
    if (a.fulltext) chip(a.fulltext + ' checked in full text', 'ok');
    if (a.unsourced && a.unsourced.checked) chip(a.unsourced.none_found + '/' + a.unsourced.checked + ' uncited claims unsupported', a.unsourced.none_found ? 'warn' : '');
    if (a.judge && a.judge.overall) chip('Judge ' + a.judge.overall + '/10');
    if (a.truncated) chip('cut off', 'bad');
    box.appendChild(chips);

    var body = el('div', 'mbody');
    md(body, a.text);
    if (a.truncated) body.appendChild(el('p', 'failed', '… The answer stops here: it hit the length limit, so its end (often the citations) is missing.'));
    box.appendChild(body);

    var serious = a.flagged.filter(function (f) { return f.kind !== 'unchecked'; });
    if (serious.length) {
      var flags = el('div', 'flags');
      flags.appendChild(el('b', null, 'Problems found'));
      var ul = el('ul');
      serious.forEach(function (f) {
        var what = f.kind === 'fabricated' ? 'does not exist' :
                   f.kind === 'retracted' ? 'retracted: ' + f.title :
                   f.kind === 'older' ? 'published ' + f.year + ', older than the date range (' + f.since + ' onward)' :
                   'real, but not about the claim: ' + f.title;
        var li = el('li');
        li.appendChild(el('code', null, f.id));
        li.appendChild(document.createTextNode(' ' + what));
        ul.appendChild(li);
      });
      flags.appendChild(ul);
      box.appendChild(flags);
    }

    if (a.judge && a.judge.overall) {
      var j = el('div', 'mjudge');
      j.appendChild(el('b', null, 'Judge (' + a.judge.label + '): ' + a.judge.overall + '/10. '));
      j.appendChild(document.createTextNode(a.judge.rationale || ''));
      box.appendChild(j);
    } else if (a.judge && a.judge.error) {
      box.appendChild(el('div', 'mjudge', 'Not scored: ' + a.judge.error));
    }
    return box;
  }


  function drawPreprints(scan) {
    var pp = panel('Latest preprints (not peer-reviewed' + (scan.since ? ', since ' + scan.since : '') + ')', false,
      'Found by OmniMed\'s own search of bioRxiv, medRxiv and other servers via Europe PMC, not by the models, which answered from peer-reviewed papers. The conclusion refers to them by ID.');
    var tb = pp.table, papers = scan.preprints || {};
    var groups = Object.keys(scan.by_candidate || {}).map(function (k) { return [k, scan.by_candidate[k], false]; })
      .concat((scan.new || []).map(function (n) { return [n.name, n.ids || [], true]; }));
    if (scan.unavailable) {
      tb.appendChild(el('caption', 'empty', 'The preprint search (Europe PMC) did not respond, so this is unknown, not empty.'));
      return pp;
    }
    if (!groups.length) {
      tb.appendChild(el('caption', 'empty', 'No recent preprints on these candidates.'));
      return pp;
    }
    row(tb, ['ID', 'Candidate', 'Preprint', 'Server', 'Posted', 'Since published'], true);
    groups.forEach(function (g) {
      g[1].forEach(function (id) {
        var p = papers[id]; if (!p) return;
        var x = p.extra || {}, tr = el('tr');
        tr.appendChild(el('td', null, id));
        tr.appendChild(el('td', null, g[0] + (g[2] ? ' (no model named it)' : '')));
        var td = el('td'), a = el('a', null, p.title || p.doi);
        a.href = p.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; td.appendChild(a); tr.appendChild(td);
        tr.appendChild(el('td', null, p.journal || 'Preprint'));
        tr.appendChild(el('td', null, x.posted || p.year || ''));
        var pub = el('td');
        if (x.published_as) {
          var b = el('a', null, x.published_as.ref || 'journal version');
          b.href = x.published_as.url; b.target = '_blank'; b.rel = 'noopener noreferrer'; pub.appendChild(b);
        } else pub.textContent = '—';
        tr.appendChild(pub);
        tb.appendChild(tr);
      });
    });
    return pp;
  }

  function drawConclusion(verdict) {
    var concl = el('section', 'mbox conclusion');
    var ch = el('div', 'mbox-head');
    ch.appendChild(el('span', 'mbadge', 'Conclusion'));
    if (verdict && verdict.by) ch.appendChild(el('span', 'mtime', 'by ' + verdict.by));
    concl.appendChild(ch);
    var cbody = el('div', 'mbody');
    if (verdict && verdict.text) md(cbody, verdict.text);
    else cbody.appendChild(el('p', 'empty', 'No verdict yet. Ask Claude for its conclusion on this comparison.'));
    concl.appendChild(cbody);
    return concl;
  }

  var turns = document.getElementById('turns');
  T.forEach(function (t, i) { turns.appendChild(drawTurn(t, i + 1, i === T.length - 1)); });

  var expanded = false;
  document.getElementById('expand').addEventListener('click', function () {
    expanded = !expanded;
    document.querySelectorAll('.grid').forEach(function (g) { g.classList.toggle('expanded', expanded); });
    this.textContent = expanded ? 'Collapse answers' : 'Expand all answers';
  });
})();
</script>
</body>
</html>
"""
