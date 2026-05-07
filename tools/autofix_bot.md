# Scraper Auto-Fix Bot

This repo can turn failed London, Tokyo, Manchester, and Taipei scraper workflow runs into labeled GitHub issues. A local bot can then run weekly, ask LM Studio for a small patch, verify it locally, open a PR, and email a summary with review/merge links.

## Requirements

- GitHub CLI authenticated with repo access: `gh auth status`
- LM Studio server running, usually at `http://localhost:1234/v1`
- A loaded local model with enough coding ability
- Branch protection / required checks configured in GitHub if you want auto-merge to wait for CI
- Repository auto-merge enabled in GitHub settings

## Check The LM Studio Model ID

```bash
curl http://localhost:1234/v1/models
```

Use the returned model `id` when installing the schedule:

```bash
export LM_STUDIO_MODEL="your-model-id"
export LM_STUDIO_BASE_URL="http://localhost:1234/v1"
./tools/install_autofix_launchd.sh
```

The launchd job runs weekly on Mondays at 09:00 local time. It opens PRs only; it does not auto-merge.

## Manual Test

Dry-run the bot without pushing:

```bash
python3 tools/scraper_autofix_bot.py --model "$LM_STUDIO_MODEL" --dry-run
```

Run for real and send the weekly email summary:

```bash
python3 tools/scraper_autofix_bot.py --model "$LM_STUDIO_MODEL" --email-summary
```

## Safety Policy

The policy lives in `.github/autofix-policy.json`.

The bot only auto-merges when:

- the issue has `auto-fix-candidate`
- the city is inferred from a city label or issue body
- the model returns a unified diff
- the diff only touches that city's scraper files
- the diff is below the configured line limit
- the model confidence is above the configured threshold
- local verification commands pass

The bot pauses and labels the issue `major-change-review` when the change is too broad, too low-confidence, touches blocked paths, or needs human judgment. Auto-merge is still available with `--auto-merge`, but the scheduled install intentionally leaves it off.
