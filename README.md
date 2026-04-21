# Obsidian Skills Scripts

Obsidian vault management and automation scripts integrated with Claude Code skills.

## Scripts

### Vault Quality Assurance

- **clean-note** - Remove AI artifacts and formatting issues from notes (v1.3.0: code block protection)
- **obsidian-link-checker** - Validate wikilink integrity and detect broken links
- **obsidian-metadata-validator** - Validate YAML frontmatter metadata
- **obsidian-tag-normalizer** - Normalize tags and detect similar tags
- **vault-lint** - Detect orphan notes, stale notes, and missing cross-references
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
