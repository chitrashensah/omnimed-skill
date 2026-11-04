# Markdown rendering of a comparison run.
#
# The report keeps OmniMed's three layers in separate columns and never blends
# them into one number: citation checks (deterministic), the judge's rubric
# score (a model's opinion), and — later, from the lab — the wet-lab verdict.
# A blended score could never answer the project's question: does the
# automated score predict the wet-lab outcome?

import re
from datetime import datetime, timezone


def _rate(v) -> str:
    return "—" if v is None else f"{round(v * 100)}%"


def _cites(v: dict | None) -> str:
    if not v:
        return "—"
    if not v.get("checked"):
        return "none cited"
    return f"{v.get('verified', 0)}/{v.get('checked', 0)} real"


def _judge(j: dict | None) -> str:
    if not j:
        return "—"
    if j.get("score"):
        return f"{j['score']['overall']}/10"
    return "not scored"


def _unsourced(u: dict | None) -> str:
    if not u or not u.get("checked"):
        return "—"
    return f"{u.get('none_found', 0)} of {u['checked']} unsupported"


def scoreboard(comp: dict) -> str:
    rows = ["| Model | Status | Citations | Fabricated | Off-topic | Retracted | "
            "Uncited claims | Judge score | Time |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for a in comp["answers"]:
        v = a.get("verification") or {}
        ok = a.get("status") == "ok"
        rows.append("| " + " | ".join([
            f"**{a['label']}**",
            "ok" if ok else f"failed: {a.get('error', '?')}",
            _cites(v) if ok else "—",
            str(v.get("fabricated", 0)) if ok and v.get("checked") else "—",
            str(v.get("mismatched", 0)) if ok and v.get("checked") else "—",
            str(v.get("retracted", 0)) if ok and v.get("checked") else "—",
            _unsourced(a.get("unsourced")) if ok else "—",
            _judge(a.get("judge")) if ok else "—",
            f"{a['seconds']}s" if a.get("seconds") else "—",
        ]) + " |")
    return "\n".join(rows)


def candidates(comp: dict) -> str:
    profiles = comp.get("candidates") or []
    if not profiles:
        return "_No miRNA/lncRNA candidates were named in the answers._"
    labels = {a["model"]: a["label"] for a in comp["answers"]}
    rows = ["| Candidate | Named by | PubMed papers | Since 2021 | Trials (as intervention) |",
            "| --- | --- | --- | --- | --- |"]
    for p in profiles:
        named = ", ".join(labels.get(m, m) for m in p.get("proposed_by") or [])
        papers = "lookup failed" if p.get("papers") is None else str(p["papers"])
        recent = "—" if p.get("papers_recent") is None else str(p["papers_recent"])
        trials = "lookup failed" if p.get("trials") is None else str(p["trials"])
        rows.append(f"| {p.get('name')} | {named} | {papers} | {recent} | {trials} |")
    return "\n".join(rows)


def preprints(comp: dict) -> str | None:
    """The latest preprints on the candidates, by id, for the verdict to cite."""
    scan = comp.get("preprints")
    if scan is None:
        return None
    if scan.get("unavailable"):
        return ("_The preprint search (Europe PMC) did not respond, so this is unknown, "
                "not empty. Run `compare` again later._")
    papers = scan.get("preprints") or {}
    groups = [(name, ids, False) for name, ids in (scan.get("by_candidate") or {}).items()]
    groups += [(n["name"], n.get("ids") or [], True) for n in scan.get("new") or []]
    if not papers or not groups:
        return f"_No preprints since {scan.get('since', '')} on these candidates._"
    out = []
    for name, ids, new in groups:
        out.append(f"**{name}**" + (" (named by no model; only in recent preprints)" if new else ""))
        for pid in ids:
            p = papers.get(pid) or {}
            extra = p.get("extra") or {}
            line = (f"- `{pid}` [{p.get('title') or p.get('doi')}]({p.get('url')}) · "
                    f"{p.get('journal', 'preprint')}, posted {extra.get('posted') or p.get('year', '')}")
            pub = extra.get("published_as")
            if pub:
                line += f" · since published: [{pub.get('ref') or pub.get('url')}]({pub.get('url')})"
            out.append(line)
    return "\n".join(out)


def papers_given(g: dict | None) -> str:
    """'📚 25 papers (auto) · PubMed since 2021', as the website labels it."""
    if not g:
        return ""
    if g.get("error"):
        return "📚 literature search failed"
    db = {"pubmed": "PubMed", "europepmc": "Europe PMC"}.get(g.get("db"), g.get("db"))
    n, req = g.get("papers", 0), g.get("requested")
    extra = " (auto)" if req == "auto" else (f" (asked for {req})" if isinstance(req, int) and req > n else "")
    since = f" since {g['since']}" if g.get("since") else ""
    return f"📚 {n} paper{'' if n == 1 else 's'}{extra} · {db}{since}"


def _flagged(v: dict | None, since: int | None = None) -> list[str]:
    out = []
    for c in (v or {}).get("citations") or []:
        cid = c.get("id") or c.get("raw") or "?"
        support = (c.get("support") or {}).get("support")
        if c.get("exists") is False:
            out.append(f"- `{cid}` — **does not exist** (fabricated)")
        elif c.get("retracted"):
            out.append(f"- `{cid}` — real but **retracted**: {c.get('title', '')[:120]}")
        elif support in ("mismatched", "unrelated"):
            reason = (c.get("support") or {}).get("reason", "")
            out.append(f"- `{cid}` — real, but **does not match the claim** ({reason[:140]}): "
                       f"{c.get('title', '')[:120]}")
        elif c.get("exists") is None:
            out.append(f"- `{cid}` — could not be checked (lookup failed; not counted as fabricated)")
        if since and c.get("exists") and str(c.get("year", "")).isdigit() and int(c["year"]) < since:
            out.append(f"- `{cid}` — published {c['year']}, **older than the date range** ({since} onward)")
    return out


def _demote(text: str) -> str:
    """Push an answer's own headings below the report's, so a model's
    "## Candidates" does not read as a section of the report itself."""
    return re.sub(r"^#{1,3}(?=\s)", "####", text or "", flags=re.M)


def render(comp: dict) -> str:
    when = comp.get("created") or datetime.now(timezone.utc).isoformat(timespec="seconds")
    parts = [
        "# OmniMed comparison",
        f"**Question:** {comp['question']}",
        f"_Run `{comp.get('run_id', '')}` · {when}_",
    ]
    verdict = comp.get("verdict") or {}
    if verdict.get("text"):
        parts += [f"## Conclusion\n_by {verdict.get('by', 'host')}_", verdict["text"]]
    parts += [
        "## Scoreboard",
        scoreboard(comp),
        ("Citations, fabricated, off-topic and retracted come from PubMed, Crossref "
         "and DataCite lookups: deterministic, no AI involved. Uncited claims counts "
         "claims made without a citation for which a literature search found nothing "
         "related. The judge score is a different model's rubric opinion "
         "(evidence, mechanism, actionability, calibration). It is never "
         "from the same provider as the answer it scores, and the judge is not told "
         "which model wrote it. Treat it as a hypothesis, not ground truth; "
         "wet-lab results are the ground truth."),
        *([comp["judge_note"]] if comp.get("judge_note") else []),
        "## Candidates, checked against the literature",
        candidates(comp),
        ("Counts come from PubMed and ClinicalTrials.gov, not from the answers. "
         "How many models named a candidate is weak evidence on its own, because models "
         "share training data and can be wrong together."),
    ]
    pre = preprints(comp)
    if pre is not None:
        parts += [f"## Latest preprints (not peer-reviewed, since {comp['preprints'].get('since', '')})",
                  pre,
                  ("Found by OmniMed's own search of bioRxiv, medRxiv and other servers via "
                   "Europe PMC, not by the models, which answered from peer-reviewed papers. "
                   "Preprints have not been peer-reviewed.")]

    flag_blocks = []
    for a in comp["answers"]:
        flags = _flagged(a.get("verification"), (a.get("grounding") or {}).get("since"))
        if a.get("truncated"):
            flags.insert(0, "- **Cut off**: the answer hit the length limit; its end is missing")
        j = a.get("judge") or {}
        if j.get("score") and j["score"].get("red_flags"):
            flags += [f"- Judge red flag: {f}" for f in j["score"]["red_flags"]]
        if flags:
            flag_blocks.append(f"### {a['label']}\n" + "\n".join(flags))
    if flag_blocks:
        parts += ["## Problems found", *flag_blocks]

    parts.append("## Answers in full")
    for a in comp["answers"]:
        head = f"### {a['label']}"
        meta = []
        if a.get("served_model"):
            meta.append(f"served by `{a['served_model']}`")
        if a.get("grounding"):
            meta.append(papers_given(a["grounding"]))
        if a.get("source"):
            meta.append(a["source"])
        j = a.get("judge") or {}
        if j.get("score"):
            meta.append(f"judged by {j.get('judge_label', j.get('judge'))}")
        if a.get("truncated"):
            meta.append("**cut off**")
        body = (_demote(a.get("text")) if a.get("status") == "ok" else
                f"_No answer: {a.get('error')}_" + (f" ({a['detail']})" if a.get("detail") else ""))
        parts.append(head + ("\n_" + " · ".join(meta) + "_" if meta else "") + "\n\n" + (body or ""))
        if j.get("score", {}).get("rationale"):
            s = j["score"]
            dims = ", ".join(f"{k} {v}" for k, v in s["scores"].items() if v is not None)
            parts.append(f"> **Judge ({s['overall']}/10; {dims}):** {s['rationale']}")
    return "\n\n".join(parts) + "\n"
