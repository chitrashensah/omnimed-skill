#!/usr/bin/env python3
"""OmniMed command-line tools, driven by the OmniMed skill.

Every command prints one JSON object to stdout, so the calling agent can parse
it; long material (answers, reports) is written to a run directory and the
JSON gives the paths.

  setup                         check dependencies, env files, which keys exist
  models                        list models, defaults, and ready-made picker questions
  defaults [a,b,c | --reset]    show or change the default models
  search QUERY                  search Europe PMC + PubMed + ClinicalTrials.gov
  verify [FILE|-]               check every PMID/DOI/author-year citation in a text
  unsourced [FILE|-]            look for literature behind uncited claims
  ask QUESTION --models a,b     ask several models in parallel, save the answers
  new-run QUESTION              start an empty run (for pasted or host answers)
  add-answer RUN --label L FILE add an answer from elsewhere (the host, a paste)
  remove-answer RUN a,b         drop models from a run (then compare again)
  compare RUN [--judge auto]    verify, profile candidates, judge, write report.md/.html
  run QUESTION --models a,b     ask + compare in one step (at most 5 models)
  add-verdict RUN FILE          put the host's verdict in the Conclusion box, open the page
  open RUN                      open a run's report.html in the browser

Only the standard library is imported before the dependency check, so a
missing httpx produces a one-time private install instead of a traceback.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
VENV_DIR = Path(os.path.expanduser("~/.cache/omnimed/venv"))
RESEARCH_PROMPT = SKILL_DIR / "reference" / "research-prompt.md"


def _ensure_deps():
    """Re-exec inside a private venv when httpx is missing.

    A skill cannot assume anything about the user's Python. Installing into a
    venv under ~/.cache keeps the user's own environments untouched.
    """
    try:
        import httpx  # noqa: F401
        return
    except ImportError:
        pass
    if os.environ.get("OMNIMED_IN_VENV"):
        print(json.dumps({"status": "error", "error": "DEPENDENCY_INSTALL_FAILED",
                          "message": "httpx is still missing inside the OmniMed venv. "
                                     f"Try: {VENV_DIR}/bin/pip install httpx"}))
        sys.exit(1)
    py = VENV_DIR / "bin" / "python"
    if not py.exists():
        VENV_DIR.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True,
                       stdout=subprocess.DEVNULL)
    check = subprocess.run([str(py), "-c", "import httpx"], capture_output=True)
    if check.returncode != 0:
        subprocess.run([str(py), "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "httpx"], check=True,
                       stdout=subprocess.DEVNULL)
    os.environ["OMNIMED_IN_VENV"] = "1"
    os.execv(str(py), [str(py), str(Path(__file__).resolve()), *sys.argv[1:]])


_ensure_deps()
sys.path.insert(0, str(HERE))

from omnimed_lib import env  # noqa: E402

env.load()  # before literature is imported: it reads NCBI_EMAIL at import time

import asyncio  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

from omnimed_lib import literature_service as lit  # noqa: E402
from omnimed_lib import models  # noqa: E402
from omnimed_lib import report  # noqa: E402
from omnimed_lib import report_html  # noqa: E402
from omnimed_lib import agent_service as rubric  # noqa: E402
from omnimed_lib import grounding  # noqa: E402

RUNS_DIR = Path(os.path.expanduser(os.getenv("OMNIMED_RUNS_DIR", "~/omnimed-runs")))
JUDGE_TIMEOUT = 60
# Expected length of the judge's visible reply. Not the real limit: each caller
# raises it to its provider's floor, so a thinking judge always has room to
# think before it writes the score. Thinking is never turned off.
JUDGE_REPLY_TOKENS = 700
# Worth trying the next judge for. A refusal or an unparseable reply is the
# judge answering; swapping models to get a different answer would be
# shopping for a score.
TRANSIENT = {"SERVICE_UNAVAILABLE", "RATE_LIMIT", "TIMEOUT", "INSUFFICIENT_CREDITS",
             "NO_API_KEY", "API_KEY_INVALID", "MODEL_UNAVAILABLE", "EMPTY_RESPONSE"}


def emit(obj, code=0):
    print(json.dumps(obj, indent=2, ensure_ascii=False))
    sys.exit(code)


def fail(error, message, code=1):
    emit({"status": "error", "error": error, "message": message}, code)


def read_text(src: str | None) -> str:
    if not src or src == "-":
        return sys.stdin.read()
    p = Path(src).expanduser()
    if not p.exists():
        fail("FILE_NOT_FOUND", f"No such file: {src}")
    return p.read_text(encoding="utf-8")


# Models write "miR‑21" with a non-breaking hyphen (U+2011) or an en dash as
# often as with "-". The literature regexes match only ASCII "-", so such an
# answer looked like it named no candidates at all. Normalised for analysis
# only; the answer is still shown exactly as the model wrote it.
_HYPHENS = str.maketrans({c: "-" for c in "\u2010\u2011\u2012\u2013\u2014\u2212\ufe63\uff0d"})


def for_analysis(text: str) -> str:
    return (text or "").translate(_HYPHENS)


def research_prompt() -> str:
    return RESEARCH_PROMPT.read_text(encoding="utf-8").strip()


def parse_models(spec: str | None) -> list[str]:
    if not spec or spec.strip().lower() in ("default", "defaults"):
        keys = [k for k in models.default_set() if models.available(k)]
        if not keys:
            fail("NO_MODELS_AVAILABLE", "No default model has an API key configured. Run `setup`.")
        return keys
    keys, unknown = [], []
    # Commas (or "and") separate models; spaces may be part of a name ("Qwen 3.8 Max").
    for raw in re.split(r"\s*(?:,|;|\band\b)\s*", spec.strip(), flags=re.I):
        raw = raw.strip()
        if not raw:
            continue
        k = models.resolve(raw)
        if k and k not in keys:
            keys.append(k)
        elif not k:
            unknown.append(raw)
    if unknown:
        fail("UNKNOWN_MODEL", f"Unknown model(s): {', '.join(unknown)}. Run `models` for the list.")
    check_limit(keys)
    return keys


def check_limit(keys: list[str]):
    if len(keys) > models.MAX_MODELS:
        labels = ", ".join(models.MODELS[k]["label"] if k in models.MODELS else k for k in keys)
        fail("TOO_MANY_MODELS",
             f"At most {models.MAX_MODELS} models per comparison (like the website's 5 boxes); "
             f"got {len(keys)}: {labels}. Ask the user which to drop.")


def slug(text: str, n=40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:n].rstrip("-") or "run"


def new_run_dir(question: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    d = RUNS_DIR / f"{stamp}-{slug(question)}"
    (d / "answers").mkdir(parents=True, exist_ok=True)
    (d / "question.txt").write_text(question + "\n", encoding="utf-8")
    return d


def save_answer(run: Path, res: dict, source: str):
    key = res["model"]
    meta = {k: v for k, v in res.items() if k != "text"}
    meta["source"] = source
    meta.setdefault("provider", (models.MODELS.get(key) or {}).get("provider"))
    (run / "answers" / f"{key}.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    md = run / "answers" / f"{key}.md"
    if res.get("status") == "ok":
        md.write_text(res["text"], encoding="utf-8")
    elif md.exists():
        md.unlink()          # a failed retry must not resurrect the old answer


def load_run(run: Path) -> tuple[str, list[dict]]:
    if not (run / "question.txt").exists():
        fail("NOT_A_RUN", f"{run} is not an OmniMed run directory (no question.txt).")
    question = (run / "question.txt").read_text(encoding="utf-8").strip()
    answers = []
    for meta_path in sorted((run / "answers").glob("*.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        md = meta_path.with_suffix(".md")
        if md.exists():
            meta["text"] = md.read_text(encoding="utf-8")
        answers.append(meta)
    return question, answers


def run_meta(run: Path) -> dict:
    f = run / "run.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except ValueError:
        return {}


def write_run_meta(run: Path, **fields):
    meta = {**run_meta(run), **{k: v for k, v in fields.items() if v is not None}}
    (run / "run.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def history_chain(run: Path | None, depth: int = 6) -> list[tuple[str, dict]]:
    """Earlier turns of a conversation, oldest first: (question, {model: answer}).

    A follow-up run records the run it follows (`--after`), so a conversation
    is a chain of runs. Six turns back at most, like the website.
    """
    chain, seen = [], set()
    while run and len(chain) < depth and str(run) not in seen:
        seen.add(str(run))
        question, answers = load_run(run)
        chain.append((question, {a["model"]: a for a in answers}))
        after = run_meta(run).get("after")
        run = Path(after) if after else None
    return list(reversed(chain))


# ── Commands ────────────────────────────────────────────────────────────────

def cmd_setup(args):
    info = env.describe()
    info["status"] = "ok"
    info["python"] = sys.executable
    info["runs_dir"] = str(RUNS_DIR)
    info["models_available"] = [m["key"] for m in models.catalog() if m["key_configured"]]
    hints = []
    if not info["env_files"]:
        hints.append(f"No env files found. Put API keys in {env.CONFIG_DIR}/keys.env "
                     "(or set OMNIMED_ENV_FILE). Literature tools work without any keys.")
    if not info["ncbi_email_set"]:
        hints.append("NCBI_EMAIL is not set; PubMed throttles anonymous callers harder.")
    info["hints"] = hints
    emit(info)


def cmd_models(args):
    emit({"status": "ok", "max_models": models.MAX_MODELS,
          "default_set": [k for k in models.default_set() if models.available(k)],
          "picker": models.picker(),
          "models": models.catalog()})


SETTINGS_FILE = env.CONFIG_DIR / "settings.env"


def cmd_defaults(args):
    """Show, set or reset the default models (OMNIMED_DEFAULT_MODELS).

    Written to settings.env only, never to keys.env, which may be a link to
    a file holding secrets."""
    if not args.models and not args.reset:
        emit({"status": "ok", "default_set": models.default_set(),
              "labels": [models.MODELS[k]["label"] for k in models.default_set()],
              "source": "settings.env" if os.getenv("OMNIMED_DEFAULT_MODELS") else "website defaults"})
    lines = []
    if SETTINGS_FILE.exists():
        lines = [l for l in SETTINGS_FILE.read_text(encoding="utf-8").splitlines()
                 if not l.strip().startswith("OMNIMED_DEFAULT_MODELS=")]
    keys = []
    if not args.reset:
        keys = parse_models(args.models)
        lines.append("OMNIMED_DEFAULT_MODELS=" + ",".join(keys))
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    shown = keys or list(models.SITE_DEFAULT)
    emit({"status": "ok", "default_set": shown,
          "labels": [models.MODELS[k]["label"] for k in shown],
          "saved_to": str(SETTINGS_FILE)})


def cmd_search(args):
    sources = tuple(s for s in (args.sources or ",".join(lit.SOURCES)).split(",") if s in lit.SOURCES)
    res = asyncio.run(lit.search(args.query, sources=sources or lit.SOURCES, limit=args.limit,
                                 year_from=args.year_from, year_to=args.year_to))
    for p in res.get("papers", []):
        p["abstract"] = (p.get("abstract") or "")[:args.abstract_chars]
    emit({"status": "ok", **res})


def cmd_verify(args):
    emit({"status": "ok", **asyncio.run(lit.verify_citations(for_analysis(read_text(args.file))))})


def cmd_unsourced(args):
    emit({"status": "ok", **asyncio.run(lit.check_unsourced_claims(for_analysis(read_text(args.file))))})


def literature_options(args) -> dict:
    """The website's per-box options (database, date range, papers), for all
    models in this run. Empty when no database was chosen."""
    if not getattr(args, "db", None):
        return {}
    return {"db": args.db, "dates": args.dates, "papers": args.papers}


def _ask(question: str, keys: list[str], run: Path | None, use_prompt: bool,
         literature: dict | None = None, after: Path | None = None) -> tuple[Path, list[dict]]:
    """Ask each model, the way the website does (services/grounding.py, shared):
    each model gets only its own earlier answers as history, the earlier
    questions it never saw, and — when a database is chosen — the papers found
    for the question, before the question itself."""
    if run:
        if not (run / "question.txt").exists():
            fail("NOT_A_RUN", f"{run} is not an OmniMed run directory.")
        existing = [m.stem for m in (run / "answers").glob("*.json")]
        check_limit(list(dict.fromkeys(existing + keys)))
        after = after or (Path(run_meta(run)["after"]) if run_meta(run).get("after") else None)
        literature = literature or run_meta(run).get("literature")
    if after and not (after / "question.txt").exists():
        fail("NOT_A_RUN", f"--after: {after} is not an OmniMed run directory.")
    run = run or new_run_dir(question)
    write_run_meta(run, after=str(after) if after else None, literature=literature or None)

    chain = history_chain(after)
    histories, missed = {}, {}
    for k in keys:
        turns, unseen = [], []
        for q, answers in chain:
            a = answers.get(k)
            if a and a.get("status") == "ok" and (a.get("text") or "").strip():
                turns += [{"role": "user", "content": q}, {"role": "assistant", "content": a["text"]}]
            else:
                unseen.append(q)
        histories[k] = grounding.cap_history(turns)
        if unseen:
            missed[k] = unseen
    lit_map = grounding.parse_literature({k: literature for k in keys}, keys) if literature else {}
    previous = chain[-1][0] if chain else ""
    system = research_prompt() if use_prompt else None

    async def go():
        search_for = grounding.literature_searcher(question, lit_map, previous)
        prepared = await asyncio.gather(*[grounding.grounded_message(k, question, lit_map, search_for, missed)
                                          for k in keys])
        messages = {k: m for k, (m, _) in zip(keys, prepared)}
        given = {k: g for k, (_, g) in zip(keys, prepared)}
        results = await models.call_many(keys, messages, system, histories=histories)
        for r in results:
            if given.get(r["model"]):
                r["grounding"] = given[r["model"]]
        return results

    results = asyncio.run(go())
    for r in results:
        save_answer(run, r, "api")
    return run, results


def cmd_ask(args):
    keys = parse_models(args.models)
    run, results = _ask(args.question, keys, Path(args.run).expanduser() if args.run else None,
                        not args.no_prompt, literature_options(args),
                        Path(args.after).expanduser() if args.after else None)
    emit({"status": "ok", "run": str(run),
          "answers": [{"model": r["model"], "label": r["label"], "status": r["status"],
                       "error": r.get("error"), "detail": r.get("detail"), "seconds": r["seconds"],
                       "papers_given": r.get("grounding"),
                       "file": str(run / "answers" / f"{r['model']}.md") if r["status"] == "ok" else None}
                      for r in results]})


def cmd_new_run(args):
    run = new_run_dir(args.question)
    emit({"status": "ok", "run": str(run)})


def cmd_remove_answer(args):
    run = Path(args.run).expanduser()
    load_run(run)
    removed = []
    for raw in re.split(r"\s*,\s*", args.models.strip()):
        key = models.resolve(raw) or raw
        for ext in (".json", ".md"):
            f = run / "answers" / f"{key}{ext}"
            if f.exists():
                f.unlink()
                if ext == ".json":
                    removed.append(key)
    _, left = load_run(run)
    emit({"status": "ok", "run": str(run), "removed": removed,
          "remaining": [a["model"] for a in left],
          "next": "run `compare` again to refresh the report"})


def cmd_add_answer(args):
    run = Path(args.run).expanduser()
    if not (run / "question.txt").exists():
        fail("NOT_A_RUN", f"{run} is not an OmniMed run directory.")
    text = read_text(args.file).strip()
    if not text:
        fail("EMPTY_ANSWER", "The answer text is empty.")
    key = args.key or ("pasted-" + slug(args.label, 24))
    existing = [m.stem for m in (run / "answers").glob("*.json")]
    check_limit(list(dict.fromkeys(existing + [key])))
    res = {"model": key, "label": args.label, "status": "ok", "text": text,
           "seconds": None, "usage": None, "served_model": args.served_model}
    meta_provider = args.provider or (models.MODELS.get(key) or {}).get("provider")
    save_answer(run, {**res, "provider": meta_provider}, args.source)
    emit({"status": "ok", "run": str(run), "model": key, "label": args.label,
          "provider": meta_provider})


async def _judge_one(question: str, ans: dict, verification: dict, requested: str | None) -> dict:
    scored_provider = ans.get("provider")
    chain = [k for k in models.judge_chain(ans["model"], requested)
             if models.MODELS[k]["provider"] != scored_provider]
    if not chain:
        return {"error": "NO_JUDGE_AVAILABLE", "tried": []}
    prompt = rubric.build_judge_prompt(question, ans["text"], verification)
    tried = []
    for judge in chain[:4]:
        res = await models.call(judge, prompt, rubric.JUDGE_SYSTEM, JUDGE_REPLY_TOKENS, JUDGE_TIMEOUT)
        tried.append({"judge": judge, "status": res["status"], "error": res.get("error")})
        if res["status"] != "ok":
            if res.get("error") in TRANSIENT:
                continue
            return {"error": res.get("error"), "judge": judge, "tried": tried}
        score = rubric.parse_judge_reply(res.get("text") or "")
        out = {"judge": judge, "judge_label": res["label"],
               "judge_served_model": res.get("served_model"), "tried": tried,
               "saw_verification": True}
        if not score:
            return {**out, "error": "UNPARSEABLE", "raw": (res.get("text") or "")[:1000]}
        return {**out, "score": score}
    return {"error": "ALL_JUDGES_FAILED", "tried": tried}


def _text_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


async def _compare(question: str, answers: list[dict], judge_mode: str,
                   previous: dict | None = None) -> dict:
    ok = [a for a in answers if a.get("status") == "ok" and (a.get("text") or "").strip()]

    # Swapping one model in a run should not re-check the other four. An
    # answer whose text is unchanged keeps its earlier results; that saves
    # PubMed calls and also keeps its judge score stable, since judge scores
    # vary between re-runs.
    # Only results from the current checker: an older one may have reported a
    # review as "does not mention it" before the full-text look existed.
    prior = {a["model"]: a for a in (previous or {}).get("answers", [])
             if a.get("text_hash") and (a.get("verification") or {}).get("checker_version")
             == lit.CHECKER_VERSION}
    fresh = []
    for a in ok:
        a["text_hash"] = _text_hash(a["text"])
        old = prior.get(a["model"])
        if old and old["text_hash"] == a["text_hash"] and (judge_mode == "none" or old.get("judge")):
            for k in ("verification", "unsourced", "judge"):
                if old.get(k) is not None:
                    a[k] = old[k]
            if judge_mode == "none":
                a.pop("judge", None)
        else:
            fresh.append(a)

    verifs = await asyncio.gather(*[lit.verify_citations(for_analysis(a["text"])) for a in fresh],
                                  return_exceptions=True)
    unsourced = await asyncio.gather(*[lit.check_unsourced_claims(for_analysis(a["text"])) for a in fresh],
                                     return_exceptions=True)
    for a, v, u in zip(fresh, verifs, unsourced):
        a["verification"] = v if isinstance(v, dict) else {"error": str(v)[:200]}
        a["unsourced"] = u if isinstance(u, dict) else {"error": str(u)[:200]}

    try:
        profiles = await lit.profile_candidates({a["model"]: for_analysis(a["text"]) for a in ok}, question)
    except Exception:
        profiles = []

    if judge_mode != "none":
        requested = None if judge_mode == "auto" else models.resolve(judge_mode)
        to_judge = [a for a in ok if a in fresh or not a.get("judge")]
        judged = await asyncio.gather(*[_judge_one(question, a, a.get("verification"), requested)
                                        for a in to_judge], return_exceptions=True)
        for a, j in zip(to_judge, judged):
            a["judge"] = j if isinstance(j, dict) else {"error": str(j)[:200]}

    return {"question": question, "answers": answers, "candidates": profiles}


def _write_comparison(run: Path, comp: dict) -> dict:
    comp["run_id"] = run.name
    comp["created"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (run / "comparison.json").write_text(json.dumps(comp, indent=2, ensure_ascii=False),
                                         encoding="utf-8")
    md = report.render(comp)
    (run / "report.md").write_text(md, encoding="utf-8")
    (run / "report.html").write_text(report_html.render(comp), encoding="utf-8")

    summary = []
    for a in comp["answers"]:
        v = a.get("verification") or {}
        j = (a.get("judge") or {})
        summary.append({
            "model": a["model"], "label": a["label"], "status": a.get("status"),
            "error": a.get("error"), "error_detail": a.get("detail"),
            "citations_checked": v.get("checked"), "verified": v.get("verified"),
            "fabricated": v.get("fabricated"), "mismatched": v.get("mismatched"),
            "retracted": v.get("retracted"),
            "hallucination_rate": v.get("hallucination_rate"),
            "miscitation_rate": v.get("miscitation_rate"),
            "uncited_claims_unsupported": (a.get("unsourced") or {}).get("none_found"),
            "judge": j.get("judge"), "judge_score": (j.get("score") or {}).get("overall"),
            "judge_error": j.get("error"),
        })
    return {"status": "ok", "run": str(run), "report": str(run / "report.md"),
            "report_html": str(run / "report.html"),
            "comparison_json": str(run / "comparison.json"),
            "candidates": [{"name": p.get("name"), "named_by": p.get("proposed_by"),
                            "papers": p.get("papers"), "papers_recent": p.get("papers_recent"),
                            "trials": p.get("trials")} for p in comp.get("candidates") or []],
            "scoreboard": summary}


def _previous(run: Path) -> dict | None:
    f = run / "comparison.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    except ValueError:
        return None


def open_in_browser(path: Path) -> bool:
    import webbrowser
    try:
        return webbrowser.open(path.resolve().as_uri())
    except Exception:
        return False


def _finish(run: Path, comp: dict, want_open: bool):
    out = _write_comparison(run, comp)
    if want_open:
        out["opened_in_browser"] = open_in_browser(run / "report.html")
    emit(out)


def cmd_compare(args):
    run = Path(args.run).expanduser()
    question, answers = load_run(run)
    if not answers:
        fail("NO_ANSWERS", f"No answers in {run}/answers. Use `ask` or `add-answer` first.")
    comp = asyncio.run(_compare(question, answers, args.judge, _previous(run)))
    _finish(run, comp, args.open)


def cmd_run(args):
    keys = parse_models(args.models)
    run, _ = _ask(args.question, keys, None, not args.no_prompt, literature_options(args),
                  Path(args.after).expanduser() if args.after else None)
    question, answers = load_run(run)
    comp = asyncio.run(_compare(question, answers, args.judge))
    _finish(run, comp, args.open)


def cmd_add_verdict(args):
    """Store the host's verdict and show it in the report's Conclusion box."""
    run = Path(args.run).expanduser()
    comp = _previous(run)
    if not comp:
        fail("NOT_COMPARED", f"Run `compare {run}` before adding a verdict.")
    verdict = read_text(args.file).strip()
    if not verdict:
        fail("EMPTY_VERDICT", "The verdict text is empty.")
    comp["verdict"] = {"text": verdict, "by": args.by,
                       "created": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (run / "comparison.json").write_text(json.dumps(comp, indent=2, ensure_ascii=False),
                                         encoding="utf-8")
    (run / "report.md").write_text(report.render(comp), encoding="utf-8")
    (run / "report.html").write_text(report_html.render(comp), encoding="utf-8")
    out = {"status": "ok", "run": str(run), "report_html": str(run / "report.html")}
    if not args.no_open:
        out["opened_in_browser"] = open_in_browser(run / "report.html")
    emit(out)


def cmd_open(args):
    run = Path(args.run).expanduser()
    page = run / "report.html"
    if not page.exists():
        fail("NO_REPORT", f"No report.html in {run}; run `compare` first.")
    emit({"status": "ok", "report_html": str(page), "opened_in_browser": open_in_browser(page)})


def main():
    ap = argparse.ArgumentParser(prog="omnimed", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("setup").set_defaults(fn=cmd_setup)
    sub.add_parser("models").set_defaults(fn=cmd_models)

    p = sub.add_parser("defaults", help="show or set the default models")
    p.add_argument("models", nargs="?", help="comma list, e.g. 'gemini38,deepseek_pro,groq'")
    p.add_argument("--reset", action="store_true", help="back to the website's defaults")
    p.set_defaults(fn=cmd_defaults)

    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--sources", help="comma list of: " + ",".join(lit.SOURCES))
    p.add_argument("--year-from", type=int)
    p.add_argument("--year-to", type=int)
    p.add_argument("--abstract-chars", type=int, default=600)
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("verify")
    p.add_argument("file", nargs="?", default="-")
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("unsourced")
    p.add_argument("file", nargs="?", default="-")
    p.set_defaults(fn=cmd_unsourced)

    judge_help = "auto (default): best available judge from another provider; none; or a model key"

    p = sub.add_parser("ask")
    p.add_argument("question")
    p.add_argument("--models", help="comma list of model keys or names; 'default' for the free set")
    p.add_argument("--run", help="existing run directory to add answers to")
    p.add_argument("--no-prompt", action="store_true", help="send the question without OmniMed's research prompt")
    p.add_argument("--db", choices=grounding.LITERATURE_DATABASES,
                   help="give every model papers from this database for the question")
    p.add_argument("--dates", default="all", choices=list(grounding.LITERATURE_RANGES),
                   help="only papers from the last 1, 5 or 10 years (strict: older ones are not cited)")
    p.add_argument("--papers", default="auto",
                   help="'auto' (the model chooses from the 25 best matches) or a number, at most 25")
    p.add_argument("--after", help="previous run this question follows up; each model gets its own earlier answers")
    p.set_defaults(fn=cmd_ask)

    p = sub.add_parser("new-run", help="start an empty run, for answers added by hand")
    p.add_argument("question")
    p.set_defaults(fn=cmd_new_run)

    p = sub.add_parser("add-answer")
    p.add_argument("run")
    p.add_argument("file", nargs="?", default="-")
    p.add_argument("--label", required=True, help="display name, e.g. 'Claude (host)'")
    p.add_argument("--key", help="model key if the answer came from a registered model")
    p.add_argument("--provider", help="anthropic/openai/google/…; keeps that provider off the judge")
    p.add_argument("--served-model", help="exact model id, if known")
    p.add_argument("--source", default="pasted", help="host | pasted | api")
    p.set_defaults(fn=cmd_add_answer)

    p = sub.add_parser("remove-answer", help="drop models from a run (to swap them out)")
    p.add_argument("run")
    p.add_argument("models", help="comma list of model keys")
    p.set_defaults(fn=cmd_remove_answer)

    p = sub.add_parser("compare")
    p.add_argument("run")
    p.add_argument("--judge", default="auto", help=judge_help)
    p.add_argument("--open", action="store_true", help="open report.html in the browser")
    p.set_defaults(fn=cmd_compare)

    p = sub.add_parser("add-verdict", help="put your verdict in the report's Conclusion box")
    p.add_argument("run")
    p.add_argument("file", nargs="?", default="-")
    p.add_argument("--by", default="Claude (host)", help="who wrote the verdict")
    p.add_argument("--no-open", action="store_true")
    p.set_defaults(fn=cmd_add_verdict)

    p = sub.add_parser("open", help="open a run's report.html in the browser")
    p.add_argument("run")
    p.set_defaults(fn=cmd_open)

    p = sub.add_parser("run")
    p.add_argument("question")
    p.add_argument("--models")
    p.add_argument("--judge", default="auto", help=judge_help)
    p.add_argument("--no-prompt", action="store_true")
    p.add_argument("--open", action="store_true", help="open report.html in the browser")
    p.add_argument("--db", choices=grounding.LITERATURE_DATABASES,
                   help="give every model papers from this database for the question")
    p.add_argument("--dates", default="all", choices=list(grounding.LITERATURE_RANGES),
                   help="only papers from the last 1, 5 or 10 years (strict: older ones are not cited)")
    p.add_argument("--papers", default="auto",
                   help="'auto' (the model chooses from the 25 best matches) or a number, at most 25")
    p.add_argument("--after", help="previous run this question follows up; each model gets its own earlier answers")
    p.set_defaults(fn=cmd_run)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
