#!/bin/sh
# Copy the modules shared with the OmniMed website into the skill, unchanged.
#
#   literature_service.py  citation checks, literature search, candidate profiles
#   agent_service.py       judge rubric and parsing
#   grounding.py           base prompt, literature grounding, missed-question note
#
# They stay byte-identical so the website and the skill check a citation, ground
# a question and score an answer the same way (tests/test_omnimed.py fails if
# they drift). Run this after changing any of them in omnimed-backend/services.
#
#   sync_from_backend.sh [path/to/omnimed-backend]
#
# Default: the website repo checked out next to this one (../nexora), or
# $OMNIMED_SITE_DIR/omnimed-backend when that is set.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
SITE=${OMNIMED_SITE_DIR:-"$HERE/../../../../nexora"}
BACKEND=${1:-"$SITE/omnimed-backend"}
if [ ! -f "$BACKEND/services/grounding.py" ]; then
  echo "Backend not found at $BACKEND. Pass its path as the first argument." >&2
  exit 1
fi
for f in literature_service.py agent_service.py grounding.py; do
  cp "$BACKEND/services/$f" "$HERE/omnimed_lib/$f"
done

# The research prompt is the website's biomedical base prompt followed by its
# "miRNA Research" prompt — generated from both, never edited by hand.
python3 - "$BACKEND/services/grounding.py" "$BACKEND/../omnimed-frontend/src/data/builtinPrompts.js" \
         "$HERE/../reference/research-prompt.md" <<'PY'
import ast, re, sys, pathlib
grounding, prompts, out = map(pathlib.Path, sys.argv[1:])
tree = ast.parse(grounding.read_text())
base = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
            and getattr(n.targets[0], "id", "") == "BIOMEDICAL_BASE_PROMPT")
mirna = re.search(r"id: 'builtin_mirna'.*?content: `(.*?)`", prompts.read_text(), re.S).group(1)
out.write_text(base.strip() + "\n\n" + mirna.strip() + "\n")
PY
echo "Synced literature_service.py, agent_service.py, grounding.py and reference/research-prompt.md from $BACKEND"
