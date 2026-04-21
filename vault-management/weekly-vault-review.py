#!/usr/bin/env python3
"""
weekly-vault-review.py
볼트 주간 리포트 생성기.
- 클리핑 소화 알림
- Personal/Tech 비율 체크
- #isolated Concept 노트 카운트
- 깨진 위키링크 카운트
- 이전 리포트 status → completed 갱신
"""

import re
import sys
from datetime import date, timedelta
from pathlib import Path

VAULT = Path("/Users/shlee/leesh/mynotes")
OUTPUT_DIR = VAULT / "06_Metadata/Reference"
CONCEPT_DIRS = [
    VAULT / "03_Resources/Concepts_Tech",
    VAULT / "03_Resources/Concepts_Personal",
]
CLIPPING_DIRS = [
    VAULT / "00_Inbox/Clippings",
    VAULT / "00_Inbox/Clippings_Git",
    VAULT / "00_Inbox/Clippings_YouTube",
]
LINK_CHECKER_DIR = VAULT / "scripts-skills/obsidian-link-checker"

today = date.today()
month_ago = today - timedelta(days=30)


def get_created(text: str) -> date | None:
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return None
    for line in m.group(1).splitlines():
        if line.startswith("created:"):
            raw = line.split(":", 1)[1].strip().strip('"\'')
            try:
                return date.fromisoformat(raw[:10])
            except ValueError:
                return None
    return None


def collect_clippings() -> list[dict]:
    clips = []
    for d in CLIPPING_DIRS:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.md")):
            text = f.read_text(encoding="utf-8", errors="ignore")
            created = get_created(text)
            if created and created <= month_ago:
                clips.append({
                    "name": f.stem,
                    "created": created,
                    "days_old": (today - created).days,
                    "folder": d.name,
                })
    return sorted(clips, key=lambda x: x["created"])


def count_concepts() -> tuple[int, int]:
    tech = sum(1 for _ in CONCEPT_DIRS[0].glob("*.md")) if CONCEPT_DIRS[0].exists() else 0
    personal = sum(1 for _ in CONCEPT_DIRS[1].glob("*.md")) if CONCEPT_DIRS[1].exists() else 0
    return tech, personal


def count_isolated() -> int:
    """#isolated 태그가 있는 Concept 노트 수"""
    count = 0
    for d in CONCEPT_DIRS:
        if not d.exists():
            continue
        for f in d.glob("*.md"):
            text = f.read_text(encoding="utf-8", errors="ignore")
            if re.search(r"^\s*-\s*isolated\b", text, re.MULTILINE):
                count += 1
    return count


def count_broken_links() -> int:
    """obsidian-link-checker를 import해 깨진 링크 수 반환 (출력 억제)"""
    if not LINK_CHECKER_DIR.exists():
        return -1
    try:
        import importlib.util
        import io
        from contextlib import redirect_stdout, redirect_stderr

        spec = importlib.util.spec_from_file_location(
            "obsidian_link_checker",
            LINK_CHECKER_DIR / "obsidian-link-checker.py",
        )
        mod = importlib.util.module_from_spec(spec)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            spec.loader.exec_module(mod)
            checker = mod.LinkHealthChecker(str(VAULT))
            checker.scan_vault()
            checker.extract_links()
            checker.validate_links()
        return len(checker.broken_links)
    except Exception as e:
        print(f"⚠️  link-checker 실행 실패: {e}", file=sys.stderr)
        return -1


def section_clippings(clips: list[dict]) -> str:
    lines = [f"## 미처리 클리핑 ({len(clips)}개, 30일 초과)\n"]
    if clips:
        lines.append("| 파일명 | 수집일 | 경과일 | 폴더 |")
        lines.append("|--------|--------|--------|------|")
        for c in clips:
            lines.append(f"| {c['name']} | {c['created']} | {c['days_old']}일 | {c['folder']} |")
    else:
        lines.append("미처리 클리핑 없음 ✅")
    return "\n".join(lines)


def section_ratio(tech: int, personal: int) -> str:
    ratio = personal / tech * 100 if tech else 0
    status = "✅ 양호" if ratio >= 15 else "⚠️ 보강 필요"
    lines = [
        "## Concepts 분포 현황\n",
        "| 영역 | 개수 | 비율 |",
        "|------|------|------|",
        f"| Concepts_Tech | {tech}개 | - |",
        f"| Concepts_Personal | {personal}개 | {ratio:.1f}% |",
        f"| 상태 | {status} | 기준: Personal ≥ Tech × 15% |",
    ]
    return "\n".join(lines)


def section_link_health(broken: int, isolated: int) -> str:
    broken_status = "✅ 없음" if broken == 0 else f"⚠️ {broken}개"
    isolated_status = "✅ 없음" if isolated == 0 else f"⚠️ {isolated}개"
    lines = [
        "## 링크 건강도\n",
        "| 항목 | 현황 | 권장 액션 |",
        "|------|------|---------|",
        f"| 깨진 위키링크 | {broken_status} | `/link-health fix:true` |",
        f"| #isolated Concept | {isolated_status} | `/note-linker` |",
    ]
    if broken == -1:
        lines.append("\n> ⚠️ link-checker 실행 실패 — 수동으로 `/link-health` 실행 필요")
    return "\n".join(lines)


def section_actions(clips: list[dict], tech: int, personal: int,
                    broken: int, isolated: int) -> str:
    actions = []
    if broken > 0:
        actions.append(f"- 깨진 링크 수정: {broken}개 → `/link-health fix:true`")
    if isolated > 0:
        actions.append(f"- 고립 Concept 연결: {isolated}개 → `/note-linker`")
    for c in clips[:5]:
        actions.append(f"- 클리핑 소화: `{c['name']}` ({c['days_old']}일 경과)")
    if personal < tech * 0.15:
        actions.append(
            f"- Concepts_Personal 보강: 현재 {personal}개 → 목표 {int(tech * 0.15)}개 이상"
        )

    lines = ["## 권장 액션\n"]
    if actions:
        lines.extend(actions)
    else:
        lines.append("- 이번 주 특이사항 없음 ✅")
    return "\n".join(lines)


def close_previous_reports():
    """이전 Concept Review 파일의 status를 completed로 갱신"""
    for f in OUTPUT_DIR.glob("Concept Review *.md"):
        if f.stem == f"Concept Review {today}":
            continue
        text = f.read_text(encoding="utf-8")
        if "status: inProgress" in text:
            updated = text.replace("status: inProgress", "status: completed")
            f.write_text(updated, encoding="utf-8")
            print(f"✅ 이전 리포트 완료 처리: {f.name}")


def main():
    print("📊 볼트 주간 리포트 생성 중...")

    clips = collect_clippings()
    tech, personal = count_concepts()
    isolated = count_isolated()
    print(f"  - 클리핑: {len(clips)}개, Concepts: Tech {tech} / Personal {personal}, isolated: {isolated}")

    print("  - 깨진 링크 검사 중... (시간이 걸릴 수 있습니다)")
    broken = count_broken_links()
    print(f"  - 깨진 링크: {broken}개")

    close_previous_reports()

    frontmatter = f"""---
type: note
author:
  - "[[이상훈]]"
created: {today}
updated: {today}
tags:
  - vault-review
  - weekly
status: inProgress
---"""

    header = f"""# 볼트 주간 리포트 - {today}

> 자동 생성 리포트입니다. 검토 후 권장 액션을 실행하세요.
"""

    body = "\n\n".join([
        section_clippings(clips),
        section_ratio(tech, personal),
        section_link_health(broken, isolated),
        section_actions(clips, tech, personal, broken, isolated),
    ])

    content = frontmatter + "\n\n" + header + "\n" + body + "\n"

    output_path = OUTPUT_DIR / f"Concept Review {today}.md"
    output_path.write_text(content, encoding="utf-8")
    print(f"✅ 리포트 생성 완료: {output_path}")


if __name__ == "__main__":
    main()
