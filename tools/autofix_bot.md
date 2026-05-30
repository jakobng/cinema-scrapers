# Scraper Auto-Fix Bot

This repo can turn failed London, Tokyo, Manchester, and Taipei scraper workflow runs into labeled GitHub issues. A local launchd job can then retry every few hours while your Mac is awake, ask Ollama or LM Studio for a small patch, verify it locally, open a PR, and email a summary with review/merge links.

Before the local bot asks the model for fixes, it also runs `tools/cinema_health_monitor.py`. That monitor checks:

- generated movie-post output freshness in `ig_posts`
- recent Instagram media for Tokyo, London, and Manchester when the IG secrets are available
- a deterministic weekly sample of source/detail cinema URLs from the scraped showtimes
- basic data freshness and duplicate-showing checks

Source/data failures become `auto-fix-candidate` issues so the local LLM can try a scraper patch. Instagram/API/output failures become `monitoring` + `manual-review` issues, because they are usually expired tokens, Meta API trouble, or workflow/schedule issues rather than safe scraper-code patches.
This does not depend on Codex, a Codex subscription, or the OpenAI API. It does depend on your Mac being awake occasionally, GitHub CLI auth, and a local model server running.

## Recommended Ollama Setup

Install Ollama, then pull a coding model:

```bash
ollama pull qwen3:14b
```

The default bot settings use Ollama's OpenAI-compatible local endpoint:

```bash
export AUTOFIX_MODEL_PROVIDER="ollama"
export OLLAMA_MODEL="qwen3:14b"
export OLLAMA_BASE_URL="http://localhost:11434/v1"
```

## Requirements

- GitHub CLI authenticated with repo access: `gh auth status`
- Ollama running locally, or LM Studio if you choose `--provider lm-studio`
- A loaded local model with enough coding ability
- SMTP environment variables if you want summary emails: `SMTP_EMAIL`, `SMTP_PASSWORD`, `SMTP_SERVER`, `SMTP_PORT`, and `ALERT_RECIPIENT_EMAIL`

## Install The Retry Job

```bash
./tools/install_autofix_launchd.sh
```

The launchd job wakes every 6 hours while this Mac is awake, but the bot records a successful run in `logs/autofix_state.json` and skips the rest of that ISO week. If the laptop is off or asleep before a successful run, it simply tries again at a future 6-hour interval when launchd is running. It opens PRs only; it does not auto-merge.

The GitHub workflow `Cinema - Health Monitor` also runs weekly without Codex or OpenAI. It opens monitoring issues from GitHub Actions so problems can be queued even if your Mac is asleep; the local Ollama job can then pick up source/data `auto-fix-candidate` issues the next time the laptop is awake.
## Optional LM Studio Setup

Check the LM Studio model ID:

```bash
curl http://localhost:1234/v1/models
```

Use the returned model `id` when installing the schedule:

```bash
export LM_STUDIO_MODEL="your-model-id"
export LM_STUDIO_BASE_URL="http://localhost:1234/v1"
./tools/install_autofix_launchd.sh
```

## Manual Test

Dry-run the bot without pushing against Ollama:

```bash
python3 tools/scraper_autofix_bot.py --provider ollama --model qwen3:14b --dry-run
```

Optional: install an Ollama vision model and set `OLLAMA_VISION_MODEL` if you want semantic image review of generated Instagram slides in addition to the built-in image sanity checks.
Dry-run against a local LM Studio model:

```bash
python3 tools/scraper_autofix_bot.py --provider lm-studio --model "$LM_STUDIO_MODEL" --dry-run
```

Run for real and send the weekly email summary:

```bash
python3 tools/scraper_autofix_bot.py --provider ollama --email-summary
```

Run only the health monitor:

```bash
python3 tools/cinema_health_monitor.py --sample-size 5 --create-issues --email-summary
```
Force a second run in the same week, if you really need one:

```bash
python3 tools/scraper_autofix_bot.py --provider ollama --email-summary --force
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
