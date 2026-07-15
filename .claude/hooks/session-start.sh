#!/bin/bash
# eonedge agent-skills — session start hook
# Injects the using-agent-skills meta-skill (skill-discovery flowchart) into every
# new session so the agent routes intent to the right skill instead of winging it.

# Resolve the skills dir whether we're running as a local .claude/ hook or a plugin.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CANDIDATES=(
  "$(dirname "$SCRIPT_DIR")/skills"                      # .claude/hooks -> .claude/skills
  "${CLAUDE_PLUGIN_ROOT}/.claude/skills"                 # installed plugin
  "${CLAUDE_PROJECT_DIR}/.claude/skills"                 # project dir
)

META_SKILL=""
for dir in "${CANDIDATES[@]}"; do
  [ -f "$dir/using-agent-skills/SKILL.md" ] && META_SKILL="$dir/using-agent-skills/SKILL.md" && break
done

# JSON is emitted with python3 — already a repo dependency (the validator and its
# tests use it) and near-universally preinstalled. No jq required.
if ! command -v python3 >/dev/null 2>&1; then
  echo '{"priority": "INFO", "message": "eonedge-skills: python3 not found on PATH — skills remain available individually."}'
  exit 0
fi

if [ -n "$META_SKILL" ] && [ -f "$META_SKILL" ]; then
  CONTENT=$(cat "$META_SKILL")
  EONEDGE_MSG="eonedge-skills loaded. Use the skill discovery flowchart to pick the right skill; the fullstack-standard skill is the always-on engineering bar.

$CONTENT" python3 -c 'import json, os; print(json.dumps({"priority": "IMPORTANT", "message": os.environ["EONEDGE_MSG"]}))'
else
  echo '{"priority": "INFO", "message": "eonedge-skills: using-agent-skills meta-skill not found. Skills may still be available individually."}'
fi
