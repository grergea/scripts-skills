#!/usr/bin/env python3
"""
skill-reviewer.py - Collect skill/agent data for review
Outputs JSON for Claude agent to analyze with karpathy-guidelines lens
"""
import json
import re
import sys
from pathlib import Path
from datetime import datetime

VAULT = Path("/Users/shlee/leesh/mynotes")
SKILLS_DIR = VAULT / ".claude/skills"
AGENTS_DIR = VAULT / ".claude/agents"
PROMPT_LOG = VAULT / "06_Metadata/Reference/Prompt Log.md"


def read_skill(skill_dir):
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        return None
    content = skill_file.read_text(encoding="utf-8")

    desc_match = re.search(r'^description:\s*(.+)$', content, re.MULTILINE)
    desc = desc_match.group(1).strip().strip('"') if desc_match else ""

    sections = re.findall(r'^## .+$', content, re.MULTILINE)
    has_when_to_use = bool(re.search(r'when to use|언제 사용|사용 시', content, re.IGNORECASE))
    has_success_criteria = bool(re.search(r'성공 기준|success criteria|검증|verify', content, re.IGNORECASE))
    trigger_keywords = re.findall(r'[가-힣]{2,}|[a-zA-Z]{4,}', desc)

    return {
        "name": skill_dir.name,
        "description": desc,
        "has_description": bool(desc.strip()),
        "sections": sections,
        "has_when_to_use": has_when_to_use,
        "has_success_criteria": has_success_criteria,
        "trigger_keyword_count": len(trigger_keywords),
        "char_count": len(content),
        "content": content,
    }


def read_agent(agent_file):
    content = agent_file.read_text(encoding="utf-8")
    desc_match = re.search(r'^description:\s*(.+)$', content, re.MULTILINE)
    desc = desc_match.group(1).strip().strip('"') if desc_match else ""

    return {
        "name": agent_file.stem,
        "description": desc,
        "has_description": bool(desc.strip()),
        "char_count": len(content),
        "content": content,
    }


def read_log_content():
    """현재 로그 + 이번 주 보관본을 합쳐서 반환 (로테이션 직후 대비)"""
    content = PROMPT_LOG.read_text(encoding="utf-8") if PROMPT_LOG.exists() else ""

    now = datetime.now()
    this_year, this_week = now.isocalendar()[:2]
    pattern = re.compile(r"^Prompt Log - (\d{4}-\d{2}-\d{2})\.md$")

    for f in sorted(PROMPT_LOG.parent.iterdir()):
        m = pattern.match(f.name)
        if not m:
            continue
        archive_date = datetime.strptime(m.group(1), "%Y-%m-%d")
        if archive_date.isocalendar()[:2] == (this_year, this_week):
            content += f.read_text(encoding="utf-8")
            break

    return content


def extract_prompts(log_content):
    rows = re.findall(r'\|\s*[\d-]+ [\d:]+\s*\|\s*`([^`]+)`\s*\|', log_content)
    return rows


def count_mentions(name, log_content):
    safe = re.escape(name)
    return len(re.findall(safe, log_content, re.IGNORECASE))


def main():
    skills = []
    for d in sorted(SKILLS_DIR.iterdir()):
        if d.is_dir():
            s = read_skill(d)
            if s:
                skills.append(s)

    agents = []
    for f in sorted(AGENTS_DIR.glob("*.md")):
        agents.append(read_agent(f))

    log_content = read_log_content()
    prompts = extract_prompts(log_content)

    for s in skills:
        s["mention_count"] = count_mentions(s["name"], log_content)
    for a in agents:
        a["mention_count"] = count_mentions(a["name"], log_content)

    result = {
        "generated_at": datetime.now().isoformat(),
        "skills": skills,
        "agents": agents,
        "recent_prompts": prompts[-80:],
        "issues": {
            "no_description": [s["name"] for s in skills if not s["has_description"]],
            "no_when_to_use": [s["name"] for s in skills if not s["has_when_to_use"]],
            "never_mentioned": [s["name"] for s in skills if s["mention_count"] == 0],
            "agents_no_desc": [a["name"] for a in agents if not a["has_description"]],
        },
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
