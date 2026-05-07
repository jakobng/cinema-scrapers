#!/usr/bin/env bash
set -euo pipefail

city="${1:?city is required}"
run_url="${2:?run URL is required}"
workflow="${3:?workflow name is required}"
run_id="${4:?run ID is required}"

candidate_label="auto-fix-candidate"
city_label="${city}"

gh label create "$candidate_label" --color "0e8a16" --description "Candidate for local scraper auto-fix bot" >/dev/null 2>&1 || true
gh label create "$city_label" --color "1d76db" --description "City scraper: ${city}" >/dev/null 2>&1 || true
gh label create "major-change-review" --color "b60205" --description "Auto-fix bot paused for human review" >/dev/null 2>&1 || true
gh label create "auto-fix-done" --color "5319e7" --description "Auto-fix bot has opened a PR or handled this issue" >/dev/null 2>&1 || true

existing="$(
  gh issue list \
    --state open \
    --label "$candidate_label" \
    --label "$city_label" \
    --search "\"Run ID: ${run_id}\" in:body" \
    --json number \
    --jq '.[0].number // empty'
)"

if [[ -n "$existing" ]]; then
  echo "Auto-fix issue already exists: #${existing}"
  exit 0
fi

title="${city^} scraper failure: run ${run_id}"
body="$(cat <<BODY
The ${city} scraper workflow failed.

City: ${city}
Workflow: ${workflow}
Run ID: ${run_id}
Run URL: ${run_url}

The local auto-fix bot can inspect this issue, fetch the run logs, and attempt a small maintenance patch.
BODY
)"

gh issue create \
  --title "$title" \
  --body "$body" \
  --label "$candidate_label" \
  --label "$city_label"
