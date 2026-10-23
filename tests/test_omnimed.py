"""Tests for the OmniMed skill.

Offline by default: no API keys, no network.
  python3 -m unittest discover -s tests          (from omnimed-skill/)

Set OMNIMED_LIVE=1 to also run the PubMed checks against the fixtures. They
use only free, keyless literature APIs, never a paid model.
"""

import asyncio
import json
import contextlib
import io
import importlib.util
import os
import re
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The OmniMed website repo, for the checks that the skill matches the site.
# Defaults to a checkout next to this one; those tests skip when it is absent.
SITE = Path(os.getenv("OMNIMED_SITE_DIR", ROOT.parent / "nexora"))
SCRIPTS = ROOT / "skills" / "omnimed" / "scripts"
FIXTURES = ROOT / "evals" / "fixtures"
sys.path.insert(0, str(SCRIPTS))

HAVE_HTTPX = importlib.util.find_spec("httpx") is not None

from omnimed_lib import env  # noqa: E402
from omnimed_lib import agent_service as rubric  # noqa: E402

if HAVE_HTTPX:
    from omnimed_lib import literature_service as lit  # noqa: E402
    from omnimed_lib import grounding  # noqa: E402
    from omnimed_lib import models  # noqa: E402
    from omnimed_lib import report  # noqa: E402
    spec = importlib.util.spec_from_file_location("omnimed_cli", SCRIPTS / "omnimed.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)


class EnvParsing(unittest.TestCase):
    def test_parses_quotes_comments_and_export(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write("# comment\nexport A_KEY='abc'\nB_KEY=\"x y\"\nC_KEY=plain # note\n\nBROKEN\n")
        try:
            vals = env._parse(Path(f.name))
        finally:
            os.unlink(f.name)
        self.assertEqual(vals, {"A_KEY": "abc", "B_KEY": "x y", "C_KEY": "plain"})

    def test_describe_never_contains_values(self):
        os.environ["GROQ_API_KEY"] = "sk-secret-value-123"
        try:
            self.assertNotIn("sk-secret-value-123", repr(env.describe()))
            self.assertTrue(env.describe()["keys_present"]["groq"])
        finally:
            del os.environ["GROQ_API_KEY"]


@unittest.skipUnless(HAVE_HTTPX, "httpx not installed; run with ~/.cache/omnimed/venv/bin/python")
class Models(unittest.TestCase):
    def test_aliases_resolve(self):
        self.assertEqual(models.resolve("GPT"), "gpt55")
        self.assertEqual(models.resolve("Gemini"), "gemini")
        self.assertEqual(models.resolve("llama"), "groq")
        self.assertIsNone(models.resolve("not-a-model"))

    def test_keys_match_backend(self):
        # Keys are written into validations.model; the skill must use the
        # backend's keys so its data pools with the website's.
        backend = SITE / "omnimed-backend" / "routes" / "chat.py"
        if not backend.exists():
            self.skipTest("website repo not found (set OMNIMED_SITE_DIR)")
        src = backend.read_text()
        for key in models.MODELS:
            self.assertIn(f'"{key}"', src, f"model key {key!r} is not a backend key")

    def test_judge_never_same_provider(self):
        with unittest.mock.patch.object(models, "available", return_value=True):
            for key, spec in models.MODELS.items():
                chain = models.judge_chain(key, requested="gemini")
                self.assertTrue(chain, key)
                for j in chain:
                    self.assertNotEqual(models.MODELS[j]["provider"], spec["provider"],
                                        f"{j} would judge {key}")

    def test_missing_key_is_reported_not_raised(self):
        saved = os.environ.pop("COHERE_API_KEY", None)
        try:
            res = asyncio.run(models.call("cohere", "hi"))
        finally:
            if saved:
                os.environ["COHERE_API_KEY"] = saved
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["error"], "NO_API_KEY")

    def test_error_mapping(self):
        self.assertEqual(models._error_for(401, ""), "API_KEY_INVALID")
        self.assertEqual(models._error_for(429, ""), "RATE_LIMIT")
        self.assertEqual(models._error_for(503, ""), "SERVICE_UNAVAILABLE")
        self.assertEqual(models._error_for(404, "model not found"), "MODEL_UNAVAILABLE")


@unittest.skipUnless(HAVE_HTTPX, "httpx not installed")
class Analysis(unittest.TestCase):
    def test_unicode_hyphens_are_normalised(self):
        # Observed live: GPT-OSS writes "miR‑21" with U+2011. Without
        # normalisation the answer appeared to name no candidates at all.
        raw = "The miR‑21 and miR–29a axes; let–7 too."
        found = lit.extract_candidates({"m": raw})       # the service normalises itself
        self.assertEqual(set(found), set(lit.extract_candidates({"m": cli.for_analysis(raw)})))
        self.assertGreaterEqual(len(found), 3, found)

    def test_citation_extraction_handles_markdown(self):
        text = "**PMID:** 19043405 and PMID 22948816; doi 10.1161/CIRCULATIONAHA.109.123."
        found = lit.extract_citations(text)
        self.assertEqual(found["pmids"], ["19043405", "22948816"])
        self.assertEqual(len(found["dois"]), 1)

    def test_bullet_under_candidate_heading_is_checked_against_it(self):
        # Observed 2026-10-23: DeepSeek cited the miR-495-3p paper on a
        # "Cell lines studied" bullet under "#### miR-495-3p". The bullet alone
        # named only "DIC", which was read as a gene, so a correct citation was
        # reported as about "DIC" while the paper concerned "AKT, PTEN".
        answer = ("#### miR-495-3p\n- **Regulatory axis**: Activates AKT signaling.\n"
                  "- **Cell lines studied**: Not detailed in abstract; DIC model [PMID: 35152537]\n")
        paper = {"title": "MicroRNA-495-3p diminishes doxorubicin-induced cardiotoxicity "
                          "through activating AKT.",
                 "abstract": "miR-495-3p directly bound to the 3'UTR of PTEN and activated AKT."}
        ctx = lit._claim_context(answer, "35152537")
        self.assertIn("miR-495-3p", ctx)
        self.assertEqual(lit.assess_citation_support(ctx, paper)["support"], "supported")

    def test_disease_and_cell_line_abbreviations_are_not_genes(self):
        self.assertEqual(lit._targets("DIC model in AC16 cells; DOX; iPSC-MSCs, BMSC EVs"), set())
        self.assertEqual(lit._targets("HMGB1 and PTEN"), {"HMGB1", "PTEN"})

    def test_parse_models_default_and_unknown(self):
        with unittest.mock.patch.object(models, "available", return_value=True):
            self.assertEqual(cli.parse_models("default"), list(models.SITE_DEFAULT))
            self.assertEqual(cli.parse_models("Gemini 3.8 Flash, GPT and deepseek"),
                             ["gemini38", "gpt55", "deepseek_pro"])
            self.assertEqual(cli.parse_models("Qwen 3.8 Max"), ["qwen38max0902"])
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(io.StringIO()):
            cli.parse_models("gemini,nonsense")


@unittest.skipUnless(HAVE_HTTPX, "httpx not installed")
class Selection(unittest.TestCase):
    def test_registry_matches_website(self):
        # The skill offers exactly the site's models, labels and defaults.
        site = SITE / "omnimed-frontend" / "src" / "data" / "models.js"
        if not site.exists():
            self.skipTest("website repo not found (set OMNIMED_SITE_DIR)")
        src = site.read_text()
        block = src[src.index("export const MODELS = ["):src.index("export const RETIRED_MODELS")]
        site_models = dict(re.findall(r"key:\s*'([a-z0-9_]+)',\s*label:\s*'([^']+)'", block))
        self.assertEqual(set(site_models), set(models.MODELS))
        for k, label in site_models.items():
            self.assertEqual(models.MODELS[k]["label"], label, k)
        self.assertIn("export const DEFAULT_BOXES = ['" + "', '".join(models.SITE_DEFAULT) + "']", src)
        self.assertIn(f"export const MAX_BOXES = {models.MAX_MODELS}", src)

    def test_more_than_five_is_refused(self):
        with unittest.mock.patch.object(models, "available", return_value=True), \
                self.assertRaises(SystemExit), contextlib.redirect_stdout(io.StringIO()):
            cli.parse_models("gemini38,gemini37,gemini36,gemini,groq,cohere")

    def test_picker_fits_a_checkbox_question(self):
        with unittest.mock.patch.object(models, "available", return_value=True):
            qs = models.picker()
        self.assertLessEqual(len(qs), 4)
        offered = []
        for q in qs:
            self.assertTrue(q["multiSelect"])
            self.assertLessEqual(len(q["header"]), 12)
            self.assertTrue(2 <= len(q["options"]) <= 4)
            offered += [o["label"] for o in q["options"]]
        self.assertEqual(len(offered), 16)
        self.assertTrue(any("(default)" in o for o in offered))

    def test_picker_skips_models_without_keys(self):
        with unittest.mock.patch.object(models, "available", side_effect=lambda k: k.startswith("gemini")):
            qs = models.picker()
        self.assertEqual([q["header"] for q in qs], ["Google"])

    def test_default_override(self):
        with unittest.mock.patch.dict(os.environ, {"OMNIMED_DEFAULT_MODELS": "gpt mini, gemini36"}):
            self.assertEqual(models.default_set(), ["gpt54mini", "gemini36"])


@unittest.skipUnless(HAVE_HTTPX, "httpx not installed")
class Html(unittest.TestCase):
    def test_answer_text_cannot_break_out_of_the_data_block(self):
        from omnimed_lib import report_html
        comp = {"question": "Q", "answers": [{"model": "groq", "label": "x", "status": "ok",
                                              "text": "</script><script>alert(1)</script>"}]}
        page = report_html.render(comp)
        self.assertNotIn("</script><script>alert(1)", page)
        self.assertIn("<\\/script>", page)


@unittest.skipUnless(HAVE_HTTPX, "httpx not installed")
class SharedWithWebsite(unittest.TestCase):
    """The skill must check, ground and score exactly as the website does."""

    def test_shared_modules_are_identical(self):
        backend = SITE / "omnimed-backend" / "services"
        if not backend.exists():
            self.skipTest("website repo not found (set OMNIMED_SITE_DIR)")
        for name in ("literature_service.py", "agent_service.py", "grounding.py"):
            mine = (SCRIPTS / "omnimed_lib" / name).read_text()
            self.assertEqual(mine, (backend / name).read_text(),
                             f"{name} differs from the website's; run sync_from_backend.sh")

    def test_research_prompt_is_generated_from_the_website(self):
        builtin = SITE / "omnimed-frontend" / "src" / "data" / "builtinPrompts.js"
        if not builtin.exists():
            self.skipTest("website repo not found (set OMNIMED_SITE_DIR)")
        mirna = re.search(r"id: 'builtin_mirna'.*?content: `(.*?)`", builtin.read_text(), re.S).group(1)
        expected = grounding.BIOMEDICAL_BASE_PROMPT.strip() + "\n\n" + mirna.strip() + "\n"
        self.assertEqual((ROOT / "skills/omnimed/reference/research-prompt.md").read_text(), expected)


@unittest.skipUnless(HAVE_HTTPX, "httpx not installed")
class Conversation(unittest.TestCase):
    def _run(self, root, name, question, answers, after=None):
        run = root / name
        (run / "answers").mkdir(parents=True)
        (run / "question.txt").write_text(question)
        for model, text in answers.items():
            status = "ok" if text else "error"
            (run / "answers" / f"{model}.json").write_text(json.dumps({"model": model, "label": model, "status": status}))
            if text:
                (run / "answers" / f"{model}.md").write_text(text)
        if after:
            (run / "run.json").write_text(json.dumps({"after": str(after)}))
        return run

    def test_history_chain_follows_after_links_oldest_first(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            r1 = self._run(root, "r1", "Q1", {"groq": "A1", "cohere": ""})
            r2 = self._run(root, "r2", "Q2", {"groq": "A2"}, after=r1)
            chain = cli.history_chain(r2)
        self.assertEqual([q for q, _ in chain], ["Q1", "Q2"])
        self.assertEqual(chain[0][1]["groq"]["text"], "A1")
        self.assertEqual(chain[0][1]["cohere"]["status"], "error")

    def test_literature_options_match_the_website(self):
        from argparse import Namespace
        self.assertEqual(cli.literature_options(Namespace(db=None)), {})
        opts = cli.literature_options(Namespace(db="pubmed", dates="5y", papers="auto"))
        parsed = grounding.parse_literature({"groq": opts}, ["groq"])
        self.assertEqual(parsed["groq"][0], "pubmed")
        self.assertEqual(parsed["groq"][2], "auto")
        self.assertEqual(grounding.parse_literature({"groq": {**opts, "papers": "8"}}, ["groq"])["groq"][2], 8)

    def test_papers_given_label(self):
        self.assertEqual(report.papers_given({"db": "pubmed", "since": 2021, "requested": "auto", "papers": 12}),
                         "📚 12 papers (auto) · PubMed since 2021")
        self.assertEqual(report.papers_given({"db": "europepmc", "since": None, "requested": 25, "papers": 4}),
                         "📚 4 papers (asked for 25) · Europe PMC")

    def test_older_citations_are_flagged(self):
        v = {"citations": [{"id": "1", "exists": True, "year": "2008", "support": {"support": "supported"}},
                           {"id": "2", "exists": True, "year": "2023", "support": {"support": "supported"}}]}
        flags = report._flagged(v, since=2021)
        self.assertEqual(len(flags), 1)
        self.assertIn("older than the date range", flags[0])


class Rubric(unittest.TestCase):
    def test_judge_prompt_is_blind(self):
        prompt = rubric.build_judge_prompt("Q?", "Answer text", None)
        for name in ("gemini", "claude", "gpt", "deepseek", "qwen", "cohere"):
            # whole words: "coherent" is in the rubric itself
            self.assertIsNone(re.search(rf"\b{name}\b", prompt, re.I), name)

    def test_parse_judge_reply_tolerates_fences(self):
        out = rubric.parse_judge_reply(
            'Sure:\n```json\n{"evidence":3,"mechanism":11,"actionability":5,'
            '"calibration":2,"overall":4,"rationale":"thin","red_flags":["x"]}\n```')
        self.assertEqual(out["scores"]["mechanism"], 10)   # clamped
        self.assertEqual(out["overall"], 5)                # mean of 3, 10, 5, 2
        self.assertEqual(out["judge_overall"], 4)          # the judge's own, kept for the record

    def test_overall_is_the_average_not_the_judges_impression(self):
        # Seen live: an answer that declined to answer scored 9/10 overall
        # with mechanism 1 and actionability 3.
        out = rubric.parse_judge_reply('{"evidence":9,"mechanism":1,"actionability":3,'
                                       '"calibration":10,"overall":9}')
        self.assertEqual(out["overall"], 6)

    def test_parse_judge_reply_rejects_prose(self):
        self.assertIsNone(rubric.parse_judge_reply("I think it's good."))


@unittest.skipUnless(HAVE_HTTPX, "httpx not installed")
class Report(unittest.TestCase):
    def test_render_keeps_layers_separate_and_demotes_headings(self):
        comp = {"question": "Q?", "run_id": "r", "candidates": [], "answers": [{
            "model": "gemini", "label": "Gemini", "status": "ok", "seconds": 3,
            "text": "## Candidates\n- miR-21",
            "verification": {"checked": 2, "verified": 1, "fabricated": 1, "mismatched": 0,
                             "retracted": 0, "citations": [{"id": "98765432", "exists": False}]},
            "judge": {"judge": "groq", "judge_label": "GPT-OSS",
                      "score": {"overall": 4, "scores": {"evidence": 3}, "rationale": "r",
                                "red_flags": []}},
        }, {"model": "cohere", "label": "Cohere", "status": "error", "error": "RATE_LIMIT"}]}
        md = report.render(comp)
        self.assertIn("| **Gemini** | ok | 1/2 real | 1 |", md)
        self.assertIn("4/10", md)
        self.assertIn("failed: RATE_LIMIT", md)
        self.assertIn("**does not exist**", md)
        self.assertIn("#### Candidates", md)
        self.assertNotIn("\n## Candidates\n", md)


@unittest.skipUnless(HAVE_HTTPX, "needs httpx")
class ConversationView(unittest.TestCase):
    """A follow-up adds to one page kept in the conversation's first run."""

    def _run(self, root, name, question, after=None):
        run = root / name
        (run / "answers").mkdir(parents=True)
        (run / "question.txt").write_text(question)
        if after:
            cli.write_run_meta(run, after=str(after))
        (run / "comparison.json").write_text(json.dumps(
            {"question": question, "answers": [], "candidates": []}))
        return run

    def test_follow_up_updates_the_first_runs_page(self):
        with tempfile.TemporaryDirectory() as d:
            first = self._run(Path(d), "a", "Which miRNAs protect against DOX?")
            second = self._run(Path(d), "b", "Which have in vivo data?", after=first)
            page = cli.write_conversation(second)
            self.assertEqual(page, first / "conversation.html")
            html = page.read_text()
            self.assertIn("Which miRNAs protect against DOX?", html)
            self.assertIn("Which have in vivo data?", html)
            self.assertEqual([p.name for p in cli.run_chain(second)], ["a", "b"])


@unittest.skipUnless(HAVE_HTTPX, "needs httpx")
class Unreachable(unittest.TestCase):
    """A database that cannot be reached must not look like 'no papers exist'."""

    def _down(self):
        async def down(*a, **k):
            raise lit.httpx.ConnectError("blocked")
        return unittest.mock.patch.multiple(lit, search_pubmed=down, search_europepmc=down, search_trials=down)

    def test_search_reports_unavailable_and_does_not_cache(self):
        q = "unreachable test %s" % os.getpid()
        with self._down(), unittest.mock.patch.object(lit, "_cache_put") as put:
            res = asyncio.run(lit.search(q, sources=("pubmed",)))
        self.assertEqual(res["unavailable"], ["pubmed"])
        put.assert_not_called()

    def test_cli_search_fails_loudly(self):
        import argparse
        args = argparse.Namespace(query="miR-21 fibrosis %s" % os.getpid(), sources=None, limit=5,
                                  year_from=None, year_to=None, abstract_chars=600)
        out = io.StringIO()
        with self._down(), contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            cli.cmd_search(args)
        self.assertEqual(json.loads(out.getvalue())["error"], "LITERATURE_UNREACHABLE")

    def test_grounding_marks_failed_search(self):
        litmap = grounding.parse_literature({"m": {"db": "pubmed", "dates": "5y", "papers": "auto"}}, ["m"])

        async def go():
            search_for = grounding.literature_searcher("miR-21 in cardiac fibrosis", litmap)
            return await grounding.grounded_message("m", "miR-21 in cardiac fibrosis", litmap, search_for)
        with self._down():
            msg, given = asyncio.run(go())
        self.assertEqual(given.get("error"), "SEARCH_FAILED")
        self.assertNotIn("found no papers", msg)


@unittest.skipUnless(HAVE_HTTPX and os.getenv("OMNIMED_LIVE"), "set OMNIMED_LIVE=1 for PubMed checks")
class LivePubMed(unittest.TestCase):
    def test_fake_pmid_and_miscitation_are_caught(self):
        text = (FIXTURES / "answer_with_fake_pmid.md").read_text()
        res = asyncio.run(lit.verify_citations(cli.for_analysis(text)))
        by_id = {c["id"]: c for c in res["citations"]}
        self.assertIs(by_id["98765432"]["exists"], False)          # fabricated
        self.assertEqual(by_id["19043405"]["support"]["support"], "supported")
        self.assertIn(by_id["22948816"]["support"]["support"], ("mismatched", "unrelated"))

    def test_clean_answer_has_no_fabrications(self):
        text = (FIXTURES / "answer_clean.md").read_text()
        res = asyncio.run(lit.verify_citations(text))
        self.assertEqual(res["fabricated"], 0)
        self.assertGreaterEqual(res["verified"], 1)


if __name__ == "__main__":
    import unittest.mock  # noqa: F401
    unittest.main()
