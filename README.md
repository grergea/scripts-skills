# Obsidian Skills Scripts

Obsidian vault management and automation scripts integrated with Claude Code skills.

## Scripts

### Vault Quality Assurance

- **vault-lint** - Unified vault health checker: structure (orphan/stale/cross-ref), wikilink integrity, YAML frontmatter metadata, and tag normalization (merged from obsidian-link-checker, obsidian-metadata-validator, obsidian-tag-normalizer)
- **vault-management** - Weekly vault report generation (clipping alerts, link health, concept stats)

### Knowledge Network

- **concept-analyzer** - Analyze concept note network structure
- **attachment-cleaner** - Clean up unused attachments and duplicates

### Agent Support

- **skill-reviewer** - Collect skill/agent metadata for periodic quality review (outputs JSON for Claude agent)

## Usage

Each script is integrated with Claude Code skills or agents. See individual script directories for detailed documentation.

## Related

- Script Notes: `/03_Resources/Scripts/Skills/`
- Skills Config: `/.claude/skills/`
- Agents Config: `/.claude/agents/`
