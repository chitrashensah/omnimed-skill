#!/bin/sh
# Copy the modules shared with the OmniMed website into the skill, unchanged.
#
#   literature_service.py  citation checks, literature search, candidate profiles
#   agent_service.py       judge rubric and parsing
#   grounding.py           citation instruction, literature grounding, missed-question note
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

echo "Synced literature_service.py, agent_service.py and grounding.py from $BACKEND"
