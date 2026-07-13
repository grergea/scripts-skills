#!/usr/bin/env python3
"""
vault-report.py
볼트 현황 리포트 생성기. /lint 스킬의 Phase 1 입력 소스 (수동 실행).
리포트는 월 단위(Concept_Review_YYYY-MM.md)로 관리 — 같은 달 재실행 시
최신 현황 섹션은 갱신하고 '점검 이력' 테이블에 실행 결과를 누적한다.
- 미처리 클리핑 알림 (00_Inbox/Clippings*, 30일 초과)
- Personal/Tech 비율 체크
- Raw Sources(00~03)의 Concept 반영률 집계 (미연결 소스 노트 탐지)
- #isolated Concept 노트 카운트
- 깨진 위키링크 카운트
- 이전 달 리포트 status → completed 갱신
"""

import re
from datetime import date, timedelta
from pathlib import Path

VAULT = Path("/Users/shlee/mynotes")
OUTPUT_DIR = VAULT / "06_Metadata/Concepts"
CONCEPT_DIRS = [
    VAULT / "03_Resources/Concepts_Tech",
    VAULT / "03_Resources/Concepts_Personal",
]
# LLM Wiki 레이어 구분 — Raw Sources(00~03) 노트의 Concept 반영률 집계용
RAW_SOURCE_AREAS = ["00_Inbox", "01_Projects", "02_Areas", "03_Resources"]
WIKI_PREFIXES = (  # 위키 레이어 — Raw Source 집계에서 제외
    "03_Resources/Concepts_Tech/",
    "03_Resources/Concepts_Personal/",
    "03_Resources/Index/",
)
NON_SOURCE_TYPES = {"meeting", "people"}  # Atomic 개념 추출 대상이 아닌 노트 타입
INBOX_CLIPPING_PREFIX = (
    "00_Inbox/Clippings"  # 00_Inbox는 Clippings* 경로만 집계 (Scratchpad 등 제외)
)
VAULT_LINT_PATH = VAULT / "scripts-skills/vault-lint/vault-lint.py"

today = date.today()
month_str = today.strftime("%Y-%m")
month_ago = today - timedelta(days=30)


def get_created(text: str) -> date | None:
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return None
    for line in m.group(1).splitlines():
        if line.startswith("created:"):
            raw = line.split(":", 1)[1].strip().strip("\"'")
            try:
                return date.fromisoformat(raw[:10])
            except ValueError:
                return None
    return None


def fm_date(fm: dict | None, field: str) -> date | None:
    """frontmatter 날짜 필드 파싱 (yaml date 객체/문자열 모두 처리)"""
    if not fm:
        return None
    raw = fm.get(field)
    if isinstance(raw, date):
        return raw
    if isinstance(raw, str):
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None
    return None


def load_records() -> tuple[list, int]:
    """vault-lint 모듈로 볼트 단일 스캔 → (FileRecord 목록, 깨진 링크 수)"""
    import importlib.util
    import io
    from contextlib import redirect_stdout, redirect_stderr

    spec = importlib.util.spec_from_file_location("vault_lint", VAULT_LINT_PATH)
    mod = importlib.util.module_from_spec(spec)
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        spec.loader.exec_module(mod)
        records = mod.scan_vault(VAULT)
        broken = mod.count_broken_links(records)
    return records, broken


def collect_clippings(records: list) -> list[dict]:
    """00_Inbox/Clippings* 에서 30일 초과 미처리 클리핑 수집"""
    clips = []
    for rec in records:
        if not rec.rel.startswith(INBOX_CLIPPING_PREFIX):
            continue
        created = fm_date(rec.fm, "created")
        if created and created <= month_ago:
            clips.append(
                {
                    "name": rec.stem,
                    "created": created,
                    "days_old": (today - created).days,
                    "folder": Path(rec.rel).parent.name,
                }
            )
    return sorted(clips, key=lambda x: x["created"])


def count_concepts() -> tuple[int, int]:
    tech = (
        sum(1 for _ in CONCEPT_DIRS[0].glob("*.md")) if CONCEPT_DIRS[0].exists() else 0
    )
    personal = (
        sum(1 for _ in CONCEPT_DIRS[1].glob("*.md")) if CONCEPT_DIRS[1].exists() else 0
    )
    return tech, personal


def count_isolated(records: list) -> int:
    """#isolated 태그가 있는 Concept 노트 수"""
    count = 0
    for rec in records:
        if not rec.rel.startswith(WIKI_PREFIXES[:2]):
            continue
        tags = (rec.fm or {}).get("tags") or []
        if "isolated" in tags or "#isolated" in rec.content:
            count += 1
    return count


def concept_coverage(records: list) -> tuple[dict, list[dict]]:
    """Raw Sources(00~03) 노트의 Concept 반영률 집계.

    Concept 노트로의 위키링크가 하나도 없는 노트를 '미연결'로 판정.
    반환: (영역별 통계, 미연결 노트 목록[updated 최신순])
    """
    concept_stems = {f.stem for d in CONCEPT_DIRS if d.exists() for f in d.glob("*.md")}
    stats = {a: {"total": 0, "linked": 0} for a in RAW_SOURCE_AREAS}
    unlinked = []
    for rec in records:
        area = rec.rel.split("/", 1)[0]
        if area not in stats:
            continue
        if rec.rel.startswith(WIKI_PREFIXES):
            continue
        if area == "00_Inbox" and not rec.rel.startswith(INBOX_CLIPPING_PREFIX):
            continue
        if (rec.fm or {}).get("type") in NON_SOURCE_TYPES:
            continue
        stats[area]["total"] += 1
        if any(t.split("/")[-1] in concept_stems for _, t, _, _ in rec.links):
            stats[area]["linked"] += 1
        else:
            unlinked.append(
                {
                    "name": rec.stem,
                    "area": area,
                    "updated": fm_date(rec.fm, "updated") or fm_date(rec.fm, "created"),
                }
            )
    unlinked.sort(key=lambda x: x["updated"] or date.min, reverse=True)
    return stats, unlinked


def section_clippings(clips: list[dict]) -> str:
    lines = [f"## 미처리 클리핑 ({len(clips)}개, 30일 초과)\n"]
    if clips:
        lines.append("| 파일명 | 수집일 | 경과일 | 폴더 |")
        lines.append("|--------|--------|--------|------|")
        for c in clips:
            lines.append(
                f"| {c['name']} | {c['created']} | {c['days_old']}일 | {c['folder']} |"
            )
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


def section_coverage(stats: dict) -> str:
    lines = [
        "## Concept 반영률 (Raw Sources 00~03)\n",
        "> Concept 노트로의 위키링크가 하나도 없는 원본 소스 노트를 '미연결'로 집계 (meeting/people 타입 제외, 00_Inbox는 Clippings*만)\n",
        "| 영역 | 소스 노트 | Concept 연결 | 미연결 | 반영률 |",
        "|------|----------|-------------|--------|--------|",
    ]
    total_all = linked_all = 0
    for area, s in stats.items():
        total, linked = s["total"], s["linked"]
        total_all += total
        linked_all += linked
        pct = linked / total * 100 if total else 0
        lines.append(
            f"| {area} | {total}개 | {linked}개 | {total - linked}개 | {pct:.0f}% |"
        )
    pct_all = linked_all / total_all * 100 if total_all else 0
    lines.append(
        f"| **전체** | {total_all}개 | {linked_all}개 | {total_all - linked_all}개 | {pct_all:.0f}% |"
    )
    return "\n".join(lines)


def section_link_health(broken: int, isolated: int) -> str:
    broken_status = "✅ 없음" if broken == 0 else f"⚠️ {broken}개"
    isolated_status = "✅ 없음" if isolated == 0 else f"⚠️ {isolated}개"
    lines = [
        "## 링크 건강도\n",
        "| 항목 | 현황 | 권장 액션 |",
        "|------|------|---------|",
        f"| 깨진 위키링크 | {broken_status} | `/lint fix:links` |",
        f"| #isolated Concept | {isolated_status} | `@concept-analyzer` → `/autoresearch` |",
    ]
    return "\n".join(lines)


def section_actions(
    clips: list[dict],
    tech: int,
    personal: int,
    broken: int,
    isolated: int,
    unlinked: list[dict],
) -> str:
    actions = []
    if broken > 0:
        actions.append(f"- 깨진 링크 수정: {broken}개 → `/lint fix:links`")
    if isolated > 0:
        actions.append(
            f"- 고립 Concept 연결: {isolated}개 → `@concept-analyzer` → `/autoresearch`"
        )
    for c in clips[:5]:
        actions.append(f"- 클리핑 소화: `{c['name']}` ({c['days_old']}일 경과)")
    for u in unlinked[:5]:
        updated = u["updated"] or "-"
        actions.append(
            f"- Concept 반영: `{u['name']}` ({u['area']}, 갱신 {updated}) → `/ingest`"
        )
    if personal < tech * 0.15:
        actions.append(
            f"- Concepts_Personal 보강: 현재 {personal}개 → 목표 {int(tech * 0.15)}개 이상"
        )

    lines = ["## 권장 액션\n"]
    if actions:
        lines.extend(actions)
    else:
        lines.append("- 특이사항 없음 ✅")
    return "\n".join(lines)


def load_history(output_path: Path) -> list[str]:
    """기존 리포트의 점검 이력 테이블 행 로드 (오늘 행은 제외 → 최신 값으로 교체)"""
    if not output_path.exists():
        return []
    text = output_path.read_text(encoding="utf-8")
    m = re.search(r"## 점검 이력\n(.*?)(?:\n## |\Z)", text, re.DOTALL)
    if not m:
        return []
    rows = [
        line
        for line in m.group(1).splitlines()
        if line.startswith("|") and "---" not in line and "점검일" not in line
    ]
    return [r for r in rows if not r.startswith(f"| {today} ")]


def section_history(
    prev_rows: list[str],
    clips_n: int,
    broken: int,
    isolated: int,
    tech: int,
    personal: int,
    unlinked_n: int,
) -> str:
    lines = [
        "## 점검 이력\n",
        "| 점검일 | 깨진 링크 | 미처리 클리핑 | #isolated | Tech/Personal | Concept 미연결 |",
        "|--------|----------|-------------|-----------|---------------|----------------|",
    ]
    lines.extend(prev_rows)
    lines.append(
        f"| {today} | {broken} | {clips_n} | {isolated} | {tech}/{personal} | {unlinked_n} |"
    )
    return "\n".join(lines)


def close_previous_reports():
    """이전 달 리포트의 status를 completed로 갱신 (구 일 단위 파일 포함)"""
    patterns = ["Concept_Review_*.md", "Concept Review 20*.md"]
    for pattern in patterns:
        for f in OUTPUT_DIR.glob(pattern):
            if f.stem == f"Concept_Review_{month_str}":
                continue
            text = f.read_text(encoding="utf-8")
            if "status: inProgress" in text:
                updated = text.replace("status: inProgress", "status: completed")
                f.write_text(updated, encoding="utf-8")
                print(f"✅ 이전 리포트 완료 처리: {f.name}")


def main():
    print(f"📊 볼트 현황 리포트 생성 중... ({month_str})")

    print("  - 볼트 스캔 중... (vault-lint, 시간이 걸릴 수 있습니다)")
    try:
        records, broken = load_records()
    except Exception as e:
        print(f"❌ vault-lint 스캔 실패: {e}", file=sys.stderr)
        sys.exit(1)

    clips = collect_clippings(records)
    tech, personal = count_concepts()
    isolated = count_isolated(records)
    stats, unlinked = concept_coverage(records)
    print(
        f"  - 클리핑: {len(clips)}개, Concepts: Tech {tech} / Personal {personal}, isolated: {isolated}"
    )
    print(f"  - 깨진 링크: {broken}개, Concept 미연결 소스: {len(unlinked)}개")

    close_previous_reports()

    output_path = OUTPUT_DIR / f"Concept_Review_{month_str}.md"
    history_rows = load_history(output_path)

    # 같은 달 재실행 시 기존 created 날짜 보존
    created = today
    if output_path.exists():
        prev = get_created(output_path.read_text(encoding="utf-8"))
        if prev:
            created = prev

    frontmatter = f"""---
type: note
author:
  - "[[이상훈]]"
created: {created}
updated: {today}
tags:
  - vault-review
  - monthly
status: inProgress
---"""

    header = f"""# 볼트 현황 리포트 - {month_str}

> 자동 생성 리포트입니다. 검토 후 권장 액션을 실행하세요. (최종 갱신: {today})
"""

    body = "\n\n".join(
        [
            section_clippings(clips),
            section_ratio(tech, personal),
            section_coverage(stats),
            section_link_health(broken, isolated),
            section_actions(clips, tech, personal, broken, isolated, unlinked),
            section_history(
                history_rows,
                len(clips),
                broken,
                isolated,
                tech,
                personal,
                len(unlinked),
            ),
        ]
    )

    content = frontmatter + "\n\n" + header + "\n" + body + "\n"

    output_path.write_text(content, encoding="utf-8")
    print(f"✅ 리포트 생성 완료: {output_path}")


if __name__ == "__main__":
    main()
