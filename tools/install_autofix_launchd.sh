#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
plist="$HOME/Library/LaunchAgents/com.cinema-scrapers.autofix.plist"
log_dir="$repo_dir/logs"
provider="${AUTOFIX_MODEL_PROVIDER:-ollama}"
model="${AUTOFIX_MODEL:-${OLLAMA_MODEL:-qwen2.5-coder:14b}}"
ollama_base_url="${OLLAMA_BASE_URL:-http://localhost:11434/v1}"
lm_base_url="${LM_STUDIO_BASE_URL:-http://localhost:1234/v1}"

mkdir -p "$log_dir" "$HOME/Library/LaunchAgents"

cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.cinema-scrapers.autofix</string>

  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>$repo_dir/tools/scraper_autofix_bot.py</string>
    <string>--provider</string>
    <string>$provider</string>
    <string>--model</string>
    <string>$model</string>
    <string>--ollama-base-url</string>
    <string>$ollama_base_url</string>
    <string>--lm-base-url</string>
    <string>$lm_base_url</string>
    <string>--email-summary</string>
  </array>

  <key>WorkingDirectory</key>
  <string>$repo_dir</string>

  <key>StartInterval</key>
  <integer>21600</integer>

  <key>RunAtLoad</key>
  <false/>

  <key>StandardOutPath</key>
  <string>$log_dir/autofix.log</string>

  <key>StandardErrorPath</key>
  <string>$log_dir/autofix.err.log</string>
</dict>
</plist>
PLIST

launchctl unload "$plist" >/dev/null 2>&1 || true
launchctl load "$plist"

echo "Installed launchd job at $plist"
echo "It will retry every 21600 seconds (6 hours) while this Mac is awake."
echo "Provider: $provider"
echo "Model: $model"
echo "It opens PRs only; it does not auto-merge."
echo "Logs:"
echo "  $log_dir/autofix.log"
echo "  $log_dir/autofix.err.log"
