# Installing Research Harness Skills

## Overview

Research Harness provides several slash command skills for Claude Code and Codex. These skills need to be symlinked to the respective skills directories.

## Available Skills

- `/rh-status` - Show workflow status and next actions
- `/rh-continue` - Smart workflow continuation with decision handling
- `/rh-decide` - Interactive decision making
- `/rh-write` - One-command paper generation (end-to-end)

## Installation

### For Claude Code

1. Create symlinks:

```bash
cd /path/to/scianchor
ln -s $(pwd)/skills/rh-status ~/.claude/skills/rh-status
ln -s $(pwd)/skills/rh-continue ~/.claude/skills/rh-continue
ln -s $(pwd)/skills/rh-write ~/.claude/skills/rh-write
ln -s $(pwd)/skills/rh-decide ~/.claude/skills/rh-decide
```

2. Restart Claude Code or start a new conversation

3. Verify by typing `/rh-` and seeing autocomplete suggestions

### For Codex

**Important**: Codex does NOT use `/` slash commands for skills. Skills are
invoked with the `$` prefix (e.g. `$rh-write`), and listed via `/skills`.
The legacy `~/.codex/prompts/*.md` custom-prompt slash commands are
deprecated upstream and no longer appear in the `/` menu in recent versions
(0.117+).

1. Create symlinks:

```bash
cd /path/to/scianchor
ln -s $(pwd)/skills/rh-status ~/.codex/skills/rh-status
ln -s $(pwd)/skills/rh-continue ~/.codex/skills/rh-continue
ln -s $(pwd)/skills/rh-write ~/.codex/skills/rh-write
ln -s $(pwd)/skills/rh-decide ~/.codex/skills/rh-decide
```

2. **Restart Codex** so the skills watcher picks up new directories

3. Verify with `/skills` — the rh- skills should appear in the list

4. Invoke with the `$` prefix, for example:

```text
$rh-write "Temporal GNN for Traffic Prediction" NeurIPS
$rh-status
$rh-continue
```

Natural-language triggers also work (e.g. "用 rh-write 写一篇关于X的论文"),
since Codex matches skill descriptions implicitly.

## Verification

Check that skills are installed correctly:

```bash
# For Claude Code
ls -la ~/.claude/skills/ | grep rh-

# For Codex
ls -la ~/.codex/skills/ | grep rh-

# Verify skill files are readable
cat ~/.claude/skills/rh-write/SKILL.md | head -10
cat ~/.codex/skills/rh-write/SKILL.md | head -10
```

## Troubleshooting

### Skills not appearing in autocomplete

**Cause**: Skills are loaded at startup. New skills won't appear until restart.

**Solution**:
- **Claude Code**: Start a new conversation or restart the app
- **Codex**: Fully restart the Codex service/app (quit and reopen)

### Symlink broken

**Symptoms**: Skill appears in list but cannot be invoked

**Solution**:
```bash
# Remove broken symlink
rm ~/.claude/skills/rh-write  # or ~/.codex/skills/rh-write

# Recreate with absolute path
ln -s /path/to/scianchor/skills/rh-write ~/.claude/skills/rh-write
```

### Skill executes but fails

**Cause**: The skill implementation may depend on MCP tools or internal modules

**Solution**:
1. Check that Research Harness is installed: `rh --version`
2. Check that MCP server is running (for MCP-based tools)
3. Read the skill's SKILL.md for dependencies

## Quick Test Script

Run this to verify all skills are correctly installed:

```bash
cat > /tmp/verify-rh-skills.sh << 'EOF'
#!/bin/bash
echo "=== Claude Code Skills ==="
ls -1 ~/.claude/skills/ | grep '^rh-' || echo "No RH skills found"

echo ""
echo "=== Codex Skills ==="
ls -1 ~/.codex/skills/ | grep '^rh-' || echo "No RH skills found"

echo ""
echo "=== Skill File Check ==="
for skill in rh-status rh-continue rh-write rh-decide; do
    claude_ok="❌"
    codex_ok="❌"
    [ -f ~/.claude/skills/$skill/SKILL.md ] && claude_ok="✅"
    [ -f ~/.codex/skills/$skill/SKILL.md ] && codex_ok="✅"
    echo "$skill: Claude $claude_ok | Codex $codex_ok"
done

echo ""
echo "If all show ✅, restart Claude Code or Codex to load the skills."
EOF

chmod +x /tmp/verify-rh-skills.sh
/tmp/verify-rh-skills.sh
```

## Auto-Install Script

Add to your setup routine:

```bash
#!/bin/bash
# Auto-install RH skills for Claude Code and Codex

RH_SKILLS="rh-status rh-continue rh-write rh-decide"
RH_REPO="/path/to/scianchor"

echo "Installing Research Harness skills..."

for skill in $RH_SKILLS; do
    # Claude Code
    if [ -d ~/.claude/skills ]; then
        ln -sf "$RH_REPO/skills/$skill" ~/.claude/skills/$skill
        echo "  ✅ Installed $skill for Claude Code"
    fi
    
    # Codex
    if [ -d ~/.codex/skills ]; then
        ln -sf "$RH_REPO/skills/$skill" ~/.codex/skills/$skill
        echo "  ✅ Installed $skill for Codex"
    fi
done

echo ""
echo "✅ Installation complete!"
echo "⚠️  Restart Claude Code or Codex to activate the new skills."
```

## Uninstalling

To remove skills:

```bash
# Claude Code
rm ~/.claude/skills/rh-status
rm ~/.claude/skills/rh-continue
rm ~/.claude/skills/rh-write
rm ~/.claude/skills/rh-decide

# Codex
rm ~/.codex/skills/rh-status
rm ~/.codex/skills/rh-continue
rm ~/.codex/skills/rh-write
rm ~/.codex/skills/rh-decide
```

## Next Steps

After installation:

1. **Try the simplest flow**: `/rh-write "Your Research Topic" NeurIPS`
2. **Check workflow status**: `/rh-status`
3. **Resume paused workflows**: `/rh-continue`
4. **Make decisions manually**: `/rh-decide`

See `docs/ONE_COMMAND_QUICKSTART.md` for usage examples.
