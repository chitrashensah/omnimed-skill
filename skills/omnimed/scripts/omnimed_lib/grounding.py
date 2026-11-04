"""How a question is put to a model: the biomedical base prompt, literature
grounding (papers from PubMed or Europe PMC), and the note for a model that
joined a conversation part-way.

Shared, unchanged, by the OmniMed website (omnimed-backend/services) and the
OmniMed Agent Skill (skills/omnimed/scripts/omnimed_lib, copied by
sync_from_backend.sh) so both put the same question to a model the same way.
Imports only literature_service and the standard library for that reason.
"""

import re
import asyncio
from datetime import date

from . import literature_service


# Hidden baseline for biomedical mode only (normal mode sends no system prompt).
# It is the single place citation rules live: the selectable prompts and the
# literature block used to repeat them in their own words, and three overlapping
# warnings about fabrication made models over-cautious — some declined to list
# candidates at all.
#
# Why each rule is there:
# - PMIDs after findings make an answer checkable; told to "always cite",
#   models also cited definitions and pleasantries, burying the claims that
#   needed support.
# - Link format and the note on automatic checking stop the "I cannot browse
#   the internet, so I cannot provide links" padding: a PubMed link needs no
#   browsing, and the platform verifies every identifier after the answer.
# How to cite, so the citation checker can read and verify it. It is all a
# model is told in Biomedical mode: every other instruction changed the answer
# (tone, depth, length, structure) away from what the model gives on its own.
CITATION_PROMPT = (
    "When you state a specific finding, cite it as "
    "[PMID: 12345678](https://pubmed.ncbi.nlm.nih.gov/12345678/) or by DOI. "
    "Never invent an identifier; if you are unsure of one, leave the claim uncited."
)

BIOMEDICAL_BASE_PROMPT = CITATION_PROMPT


# ── Literature grounding (the per-box "database" and "date range" options) ───
# A box with a database selected gets the papers that database returns for the
# question, with the instruction to cite from them. Boxes without one answer
# from training alone, which is the comparison the option exists for.
LITERATURE_DATABASES = ("pubmed", "europepmc")
LITERATURE_RANGES = {"1y": 1, "5y": 5, "10y": 10, "all": None}
# Papers per box: a number the user chose, or "auto". A paper with its
# abstract costs ~200 input tokens on every question; a title line ~30.
LITERATURE_PAPERS_MAX = 25            # what one PubMed / Europe PMC page returns
# Auto: the model sees the 25 best matches and decides which to use. Only the
# top ones carry abstracts, so it costs about what a fixed 8 did (~2,100 tokens)
# while offering three times the candidates. A relevance filter on our side
# was tried first, but PubMed already ANDs every term, so nearly every result
# "matched" — including an immune-adverse-events review for a fibrosis question.
LITERATURE_AUTO_ABSTRACTS = 8
LITERATURE_ABSTRACT_CHARS = 10_000   # whole abstracts; they were cut at 700

# Words about the request rather than the topic. PubMed ANDs every term, so
# each one left in narrows the search to papers that use it: "Which miRNAs are
# the most promising targets…" returned 4 papers as typed and 8 relevant ones
# reduced to its terms. Worse, "give me the citations again with the link…
# cite properly" searched for "citations", "link" and "cite", and the model was
# handed papers ABOUT citations and links (a citation-network recommender,
# "social prescribing link workers") instead of anything on miRNAs.
# Written-out RNA classes, longest first ("long non-coding RNA" before "non-coding RNA").
_RNA_CLASSES = (
    (r"\blong[\s-]*non[\s-]*coding[\s-]*rnas?\b|\blncrnas?\b", "lncRNA"),
    (r"\bcircular[\s-]*rnas?\b|\bcircrnas?\b", "circRNA"),
    (r"\bmicro[\s-]*rnas?\b|\bmirnas?\b", "microRNA"),
    (r"\bnon[\s-]*coding[\s-]*rnas?\b|\bncrnas?\b", "ncRNA"),
)
# Disease and tissue words, which keep a search on topic.
_CONTEXT_STEMS = (
    "cardi", "heart", "myocard", "infarct", "fibro", "hypertroph", "isch", "reperf",
    "atheroscl", "vascul", "endotheli", "arrhythm", "doxorubicin", "anthracycl", "ferropt",
    "pyropt", "apopto", "seps", "hypertens", "aort", "coronar", "stroke", "valv", "disease",
    "injur", "failure", "remodel", "angiogen", "inflamm", "diabet", "cancer", "tumor", "tumour",
)

_QUERY_FILLER = {
    "hi", "hello", "thanks", "thank", "just", "cases", "case", "over", "down", "models",
    "model", "expression", "overexpression", "downregulation", "upregulation", "regulation",
    "such", "like", "may", "might", "these", "those", "them", "kind", "types", "type",
    "citation", "citations", "cite", "cited", "citing", "reference", "references",
    "source", "sources", "link", "links", "url", "urls", "pmid", "pmids", "doi",
    "paper", "papers", "article", "articles", "literature", "pubmed", "publication",
    "publications", "again", "find", "show", "provide", "properly", "proper",
    "tentative", "related", "relevant", "regarding", "concerning", "involved",
    "latest", "recent", "new", "help", "can", "you", "also", "more", "some", "any",
    "all", "please", "need", "want", "know", "using", "use", "based", "make",
    "which", "what", "most", "promising", "therapeutic", "targets", "target", "reduce",
    "after", "protect", "against", "does", "the", "are", "how", "strong", "evidence",
    "about", "with", "from", "that", "this", "into", "their", "there", "best", "good",
    "role", "roles", "current", "known", "potential", "could", "would", "should",
    "explain", "give", "list", "tell", "answer", "under", "words", "word", "briefly",
    "brief", "summarize", "summarise", "sentences", "sentence", "bullet",
    "bullets", "points", "detail", "detailed", "include", "format", "table", "short",
}


def parse_literature(raw, models: list) -> dict:
    """{model: (database, year_from, papers)} for the boxes that asked for literature."""
    out = {}
    for m, opt in (raw or {}).items():
        if m not in models or not isinstance(opt, dict):
            continue
        db = opt.get("db")
        if db not in LITERATURE_DATABASES:
            continue
        dates = str(opt.get("dates") or "all")
        years = LITERATURE_RANGES.get(dates)
        # A year ("2018") as well as a range: researchers say "since 2018".
        since = (int(dates) if dates.isdigit() and 1900 <= int(dates) <= date.today().year
                 else date.today().year - years if years else None)
        try:
            papers = max(1, min(int(opt.get("papers")), LITERATURE_PAPERS_MAX))
        except (TypeError, ValueError):
            papers = "auto"                 # no preference: the model decides
        out[m] = (db, since, papers)
    return out


def literature_terms(question: str, previous: str = "") -> list:
    """The question's search terms, in order.

    Only the question itself is used: instructions after it ("Answer in under
    150 words") went into the PubMed query and made it return nothing.
    A follow-up with almost no topic of its own ("give me the citations again")
    is searched on the previous question's topic instead.
    """
    def terms(text):
        text = text or ""
        if "?" in text:
            text = text[:text.index("?")]
        # RNA classes written out ("micro RNA", "long non coding RNAs") were
        # split into words that every paper had to contain; asking for two
        # classes made a paper need both. They become one OR group instead.
        classes = []
        for pattern, name in _RNA_CLASSES:
            if re.search(pattern, text, re.I):
                classes.append(name)
                text = re.sub(pattern, " ", text, flags=re.I)
        words = [w for w in dict.fromkeys(re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", text))
                 if w.lower() not in _QUERY_FILLER and w.lower() not in literature_service._STOPWORDS]
        # Most central first, since a search that finds nothing drops terms from
        # the end: named RNAs, the RNA classes, the disease context, the rest.
        # In question order the topic ("cardiovascular disease") came last and
        # was dropped before a typo ("proeprly"), leaving an oral-cancer paper.
        named = [w for w in words if literature_service._rna_entities(w)]
        context = [w for w in words if w not in named and w.lower().startswith(_CONTEXT_STEMS)]
        rest = [w for w in words if w not in named and w not in context]
        group = ([classes[0]] if len(classes) == 1 else
                 [f"({' OR '.join(classes)})"] if classes else [])
        return named + group + context + rest

    found = terms(question)
    if len(found) < 2 and previous:
        found = list(dict.fromkeys(found + terms(previous)))
    return found


def topic_terms(question: str) -> list:
    """The question's topic without its RNA names or classes: disease, tissue, drug.

    What the preprint scan pairs each candidate with ("miR-210 AND doxorubicin").
    """
    classes = {name.lower() for _, name in _RNA_CLASSES}
    return [t for t in literature_terms(question)
            if not t.startswith("(") and t.lower() not in classes
            and not literature_service._rna_entities(t)]


def literature_block(db: str, year_from: int | None, papers: list,
                      abstracts: int | None = None) -> str:
    """The papers as the model sees them. `abstracts` limits how many carry
    their abstract (auto mode); the rest are title lines."""
    name = {"pubmed": "PubMed", "europepmc": "Europe PMC"}[db]
    since = f" published since {year_from}" if year_from else ""
    # The date range filtered only these papers; the model was never told it,
    # so for anything it cited from memory it reached for the classic papers
    # it knows best (2007, 2008, 2013) despite "Past 5 years". The range is
    # strict, at the user's request: older work may be described, not cited.
    dates = f" Cite only papers published in {year_from} or later." if year_from else ""
    if not papers:
        return f"[A {name} search for this question found no papers{since}.{dates}]"
    rows = []
    for i, p in enumerate(papers, 1):
        ident = f"PMID: {p['pmid']}" if p.get("pmid") else (f"DOI: {p['doi']}" if p.get("doi") else "")
        head = f"[{i}] {p.get('title', '').rstrip('.')}. {p.get('journal', '')} {p.get('year', '')}. {ident}"
        abstract = (p.get("abstract") or "")[:LITERATURE_ABSTRACT_CHARS]
        if abstract and (abstracts is None or i <= abstracts):
            head += f"\nAbstract: {abstract}"
        rows.append(head)
    # Marked as background the user neither wrote nor saw: inside the user's
    # turn it was otherwise taken for the user's own references, and "give me
    # the citations again" got these papers listed back instead of an answer.
    # "Answer fully" because a model told only to ground itself in off-topic
    # results declined to answer at all.
    # Kept to one line on purpose: each extra instruction here reshaped the
    # answer. "The user did not write or see this list" alone stops models
    # from listing it back or treating it as the user's own references.
    return (f"[{name} papers found for this question; the user did not write or see this "
            f"list. Cite any that are relevant.{dates}]\n\n"
            + "\n\n".join(rows) + "\n[End of papers]")


MAX_MISSED_QUESTIONS = 3
MAX_MISSED_CHARS = 300


def missed_note(questions) -> str:
    """Earlier questions of this chat that this model never saw.

    A model put into a box mid-conversation has no history of its own, so a
    follow-up like "give me the citations again" made no sense to it ("I don't
    have access to any previous conversation"). It is told the questions only,
    never the other models' answers: those would make the answers depend on
    each other, and comparing independent answers is the point.
    """
    qs = [str(q).strip()[:MAX_MISSED_CHARS] for q in (questions or []) if str(q).strip()]
    qs = qs[-MAX_MISSED_QUESTIONS:]
    if not qs:
        return ""
    lines = "\n".join(f"- {q}" for q in qs)
    return f"[Earlier in this chat the user asked:\n{lines}]"


async def grounded_message(model: str, full_message: str, literature: dict, search_for,
                            missed: dict | None = None) -> tuple:
    """The message for one model: its literature block if it asked for one,
    and the earlier questions it missed, before the user's own message.

    Both go into this turn's message, after the history, so a box's cached
    conversation prefix is unaffected by them.
    """
    note = missed_note((missed or {}).get(model))

    def wrapped(*parts) -> str:
        parts = [p for p in parts if p]
        return "\n\n".join(parts + [f"The user's message:\n{full_message}"]) if parts else full_message

    if model not in literature:
        return wrapped(note), None
    db, year_from, wanted = literature[model]
    grounding = {"db": db, "since": year_from, "requested": wanted}
    auto = wanted == "auto"
    try:
        found = await search_for(db, year_from)
        papers = (found.get("papers") or [])[:LITERATURE_PAPERS_MAX if auto else wanted]
    except Exception:
        return wrapped(note), {**grounding, "error": "SEARCH_FAILED"}
    block = literature_block(db, year_from, papers,
                              abstracts=LITERATURE_AUTO_ABSTRACTS if auto else None)
    return wrapped(block, note), {**grounding, "papers": len(papers)}


def previous_question(histories: dict, history: list) -> str:
    """The last question asked before this one, from any box's history."""
    for h in list(histories.values()) + [history]:
        for turn in reversed(h or []):
            if turn.get("role") == "user" and turn.get("content"):
                return str(turn["content"])
    return ""


def literature_searcher(question: str, literature: dict, previous: str = ""):
    """One search per (database, year), shared by every box that chose it.

    It fetches the most papers any of those boxes asked for; each box then
    takes its own number from the top of the same relevance-ranked list.
    """
    terms = literature_terms(question, previous) or [(question or "")[:300]]
    limits: dict = {}
    for db, year_from, wanted in literature.values():
        n = LITERATURE_PAPERS_MAX if wanted == "auto" else wanted
        limits[(db, year_from)] = max(n, limits.get((db, year_from), 0))
    tasks = {}

    async def search(db, year_from):
        # PubMed ANDs every term, so one over-specific word can empty the
        # result. Rather than hand the model "no papers found", drop terms
        # from the end (the least central) and try again, down to three.
        attempt = terms
        while True:
            found = await literature_service.search(
                " ".join(attempt)[:300], sources=(db,),
                limit=limits.get((db, year_from), LITERATURE_PAPERS_MAX),
                year_from=year_from)
            # An unreachable database is a failed search, not "no papers":
            # grounded_message then labels it so instead of telling the
            # model that nothing on the topic exists.
            if found.get("unavailable"):
                raise RuntimeError(f"{db} unavailable")
            if found.get("papers") or len(attempt) <= 3:
                return found
            attempt = attempt[:max(3, len(attempt) - 2)]

    def search_for(db, year_from):
        key = (db, year_from)
        if key not in tasks:
            tasks[key] = asyncio.ensure_future(search(db, year_from))
        return tasks[key]
    return search_for


# ── Conversation history ────────────────────────────────────────────────────
# Each model gets its whole earlier conversation, answers unshortened: trimming
# them changed what it built on. The only bound is a safety margin under the
# smallest context window offered (~128k tokens), so a very long chat cannot
# make a request fail; the oldest turns go first if it is ever reached.
MAX_HISTORY_ITEMS = 1_000
MAX_HISTORY_CHARS = 300_000       # ≈75k tokens
MAX_HISTORY_MSG_CHARS = 300_000   # no per-answer trimming


def _trim_msg(content: str, role: str) -> str:
    """Keep a long assistant answer's shape without its bulk.

    The head carries the claims and the tail carries the citation list, which
    is what later turns actually refer back to; the middle is elaboration the
    model can do without. User messages are left alone — they are short, and
    they are the questions the thread is about.
    """
    if role == "user" or len(content) <= MAX_HISTORY_MSG_CHARS:
        return content
    head = int(MAX_HISTORY_MSG_CHARS * 0.7)
    tail = MAX_HISTORY_MSG_CHARS - head
    return f"{content[:head]}\n\n[…trimmed for context…]\n\n{content[-tail:]}"


def cap_history(history: list) -> list:
    """Most recent turns, under both an item cap and a character budget."""
    valid = [h for h in history
             if h.get("role") in ("user", "assistant") and h.get("content")]

    kept, total = [], 0
    for h in reversed(valid[-MAX_HISTORY_ITEMS:]):
        content = _trim_msg(str(h["content"]), h["role"])
        if kept and total + len(content) > MAX_HISTORY_CHARS:
            break                      # always keep at least the latest exchange
        kept.append({"role": h["role"], "content": content})
        total += len(content)

    kept.reverse()
    # A leading assistant turn is a dangling reply to a question that was
    # dropped; some providers also reject a history that does not start with
    # a user turn.
    while kept and kept[0]["role"] == "assistant":
        kept.pop(0)
    return kept


# ── Content builders for multimodal ────────────────────────────────────────
