#!/usr/bin/env python3
"""
skill-reviewer.py - Collect skill/agent data for review

볼트가 소유한 스킬(.claude/skills)과 에이전트(.claude/agents)의 메타데이터를 수집하고,
Claude Code 트랜스크립트에서 실제 호출 횟수를 집계해 JSON으로 출력한다.
분석과 판단은 vault-skill-review 스킬이 수행한다.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
from glob import glob
from pathlib import Path
from datetime import datetime

VAULT = Path("/Users/shlee/mynotes")
SKILLS_DIR = VAULT / ".claude/skills"
AGENTS_DIR = VAULT / ".claude/agents"
# 서브에이전트 트랜스크립트는 <세션>/subagents/ 아래에 따로 쌓이므로 재귀로 훑는다
TRANSCRIPTS = os.path.expanduser("~/.claude/projects/**/*.jsonl")
HISTORY = VAULT / ".claude/cache/skill-usage-history.json"

OVERSIZE_LINES = 300
DELETE_STREAK = 3


def read_skill(skill_dir):
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        return None
    content = skill_file.read_text(encoding="utf-8")

    desc_match = re.search(r"^description:\s*(.+)$", content, re.MULTILINE)
    desc = desc_match.group(1).strip().strip('"') if desc_match else ""

    sections = re.findall(r"^## .+$", content, re.MULTILINE)

    # 트리거 안내는 description 의 "Use when / Triggers on" 이나 본문 When to Use 섹션
    # 둘 중 하나만 있으면 충족된다. 최신 스킬은 description 에만 두는 편이라
    # 섹션 유무만 보면 정상 스킬이 대량 오탐된다.
    has_when_to_use_section = bool(
        re.search(
            r"^#{2,3} .*(when to use|언제 사용)", content, re.IGNORECASE | re.MULTILINE
        )
    )
    desc_has_trigger = bool(
        re.search(
            r"use when|triggers on|use this skill when|할 때|사용", desc, re.IGNORECASE
        )
    )

    return {
        "name": skill_dir.name,
        "description": desc,
        "has_description": bool(desc.strip()),
        "desc_length": len(desc),
        "sections": sections,
        "has_when_to_use_section": has_when_to_use_section,
        "desc_has_trigger": desc_has_trigger,
        "has_trigger_guidance": has_when_to_use_section or desc_has_trigger,
        "char_count": len(content),
        "line_count": content.count("\n") + 1,
    }


def read_agent(agent_file):
    content = agent_file.read_text(encoding="utf-8")
    desc_match = re.search(r"^description:\s*(.+)$", content, re.MULTILINE)
    desc = desc_match.group(1).strip().strip('"') if desc_match else ""

    return {
        "name": agent_file.stem,
        "description": desc,
        "has_description": bool(desc.strip()),
        "char_count": len(content),
        "line_count": content.count("\n") + 1,
    }


def scan_transcripts():
    """Claude Code 트랜스크립트에서 Skill/Agent 실제 호출을 집계한다.

    반환: (skill_usage, agent_usage, window)
    usage 는 {이름: {"count": N, "last_used": "YYYY-MM-DD"}}.
    트랜스크립트는 일정 기간 후 삭제되므로 window 로 관측 구간을 함께 보고한다.
    """
    skill_usage, agent_usage = {}, {}
    earliest = latest = None
    files = glob(TRANSCRIPTS, recursive=True)

    def record(bucket, name, day):
        e = bucket.setdefault(name, {"count": 0, "last_used": None})
        e["count"] += 1
        if day and (e["last_used"] is None or day > e["last_used"]):
            e["last_used"] = day

    for path in files:
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    if '"tool_use"' not in line:
                        continue
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue
                    day = (entry.get("timestamp") or "")[:10]
                    if day.startswith("20"):
                        if earliest is None or day < earliest:
                            earliest = day
                        if latest is None or day > latest:
                            latest = day
                    message = entry.get("message") or {}
                    for block in message.get("content") or []:
                        if (
                            not isinstance(block, dict)
                            or block.get("type") != "tool_use"
                        ):
                            continue
                        params = block.get("input") or {}
                        if block.get("name") == "Skill":
                            if params.get("skill"):
                                record(skill_usage, params["skill"], day)
                        elif block.get("name") == "Agent":
                            if params.get("subagent_type"):
                                record(agent_usage, params["subagent_type"], day)
        except OSError:
            continue

    window = {
        "source": "~/.claude/projects/**/*.jsonl",
        "session_files": len(files),
        "earliest": earliest,
        "latest": latest,
    }
    return skill_usage, agent_usage, window


def run_validate():
    """구조 검증은 `claude plugin validate` 에 위임한다.

    frontmatter 누락, 매니페스트 오류, 인식 못 하는 필드까지 잡아 주므로
    자체 정규식으로 흉내 내지 않는다. validate 는 심볼릭 링크를 따라가지
    않으므로 링크된 스킬의 실제 경로를 따로 한 번 더 검사한다.
    """
    exe = shutil.which("claude")
    if not exe:
        return {"available": False, "reason": "claude 실행 파일을 찾을 수 없음"}

    targets = [str(VAULT / ".claude")]
    for entry in sorted(SKILLS_DIR.iterdir()):
        if entry.is_symlink():
            targets.append(str(entry.resolve().parent))
    targets = list(dict.fromkeys(targets))

    runs = []
    for target in targets:
        try:
            proc = subprocess.run(
                [exe, "plugin", "validate", target, "--strict"],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            runs.append({"target": target, "error": str(exc)})
            continue
        output = (proc.stdout or "") + (proc.stderr or "")
        runs.append(
            {
                "target": target,
                "passed": proc.returncode == 0,
                "findings": [
                    line.strip().lstrip("❯ ").strip()
                    for line in output.splitlines()
                    if line.strip().startswith("❯")
                ],
            }
        )

    return {
        "available": True,
        "command": "claude plugin validate <target> --strict",
        "runs": runs,
    }


def load_history():
    try:
        data = json.loads(HISTORY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record_history(history, skills, agents, window):
    """이번 실행 결과를 월 단위 스냅샷으로 남긴다.

    트랜스크립트는 몇 주 뒤 삭제되므로 그때그때의 집계를 보존해야
    장기 미사용 여부를 판단할 수 있다. 같은 달에 여러 번 실행하면
    해당 달 항목을 덮어써서 주기 수가 부풀지 않게 한다.
    """
    month = datetime.now().strftime("%Y-%m")
    history[month] = {
        "recorded_at": datetime.now().strftime("%Y-%m-%d"),
        "window": [window["earliest"], window["latest"]],
        "skills": {s["name"]: s["invocation_count"] for s in skills},
        "agents": {a["name"]: a["invocation_count"] for a in agents},
    }

    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    tmp = HISTORY.with_name(HISTORY.name + ".tmp")
    tmp.write_text(
        json.dumps(history, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp.replace(HISTORY)
    return history


def zero_streak(history, kind, name):
    """최근 달부터 거슬러 올라가며 호출 0회가 연속된 주기 수.

    해당 스냅샷에 이름이 없으면 그 시점에 존재하지 않던 스킬이므로
    거기서 멈춘다. 신설 스킬이 과거 미기록을 미사용으로 오인하지 않도록.
    """
    streak = 0
    for month in sorted(history, reverse=True):
        counts = history[month].get(kind) or {}
        if counts.get(name) != 0:
            break
        streak += 1
    return streak


def main(record=True):
    skills = []
    for d in sorted(SKILLS_DIR.iterdir()):
        if d.is_dir():
            s = read_skill(d)
            if s:
                skills.append(s)

    agents = []
    for f in sorted(AGENTS_DIR.glob("*.md")):
        agents.append(read_agent(f))

    skill_usage, agent_usage, window = scan_transcripts()

    for item, usage in ((skills, skill_usage), (agents, agent_usage)):
        for entry in item:
            hit = usage.get(entry["name"], {})
            entry["invocation_count"] = hit.get("count", 0)
            entry["last_used"] = hit.get("last_used")

    known = {s["name"] for s in skills} | {a["name"] for a in agents}
    external = sorted(
        ({**v, "name": k} for k, v in skill_usage.items() if k not in known),
        key=lambda e: -e["count"],
    )

    history = load_history()
    if record:
        history = record_history(history, skills, agents, window)

    for kind, item in (("skills", skills), ("agents", agents)):
        for entry in item:
            entry["zero_streak"] = zero_streak(history, kind, entry["name"])

    result = {
        "generated_at": datetime.now().isoformat(),
        "usage_window": window,
        "structural_validation": run_validate(),
        "history": {
            "path": str(HISTORY),
            "recorded": record,
            "months": sorted(history),
        },
        "skills": skills,
        "agents": agents,
        "external_skill_usage": external,
        "issues": {
            "no_trigger_guidance": [
                s["name"] for s in skills if not s["has_trigger_guidance"]
            ],
            "never_invoked": [s["name"] for s in skills if s["invocation_count"] == 0],
            "oversized": [
                f"{s['name']} ({s['line_count']}줄)"
                for s in skills
                if s["line_count"] > OVERSIZE_LINES
            ],
            "delete_candidates": [
                f"{s['name']} ({s['zero_streak']}주기 연속 미호출)"
                for s in skills
                if s["zero_streak"] >= DELETE_STREAK
            ],
        },
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-record",
        action="store_true",
        help="이번 실행 결과를 사용 이력에 기록하지 않는다 (dry-run 용)",
    )
    args = parser.parse_args()
    main(record=not args.no_record)
