#!/usr/bin/env python3
"""
vault-lint.py — Obsidian 볼트 통합 건강도 검사기

구조(고아/스테일/연결부족), 위키링크, 메타데이터, 태그를 단일 스캔으로 검사합니다.
(구 obsidian-link-checker / obsidian-metadata-validator / obsidian-tag-normalizer 통합)

Usage:
  python3 vault-lint.py <vault_path> [--checks structure,links,meta,tags]
                        [--scope <path>] [--stale-days <days>]
                        [--min-similarity <pct>] [--export-json <file>]
"""

import re
import sys
import json
import argparse
from datetime import datetime, date
from pathlib import Path
from collections import defaultdict, Counter
from difflib import SequenceMatcher

import yaml

# ──────────────────────────────────────────
# 설정
# ──────────────────────────────────────────

# 스캔 자체에서 제외 (모든 검사 공통)
EXCLUDE_SCAN_DIRS = {
    ".git",
    ".obsidian",
    ".trash",
    ".claude",
    "node_modules",
    "scripts-repo",
    "scripts-skills",
    "scripts-finance",
    "scripts-local",
    "ons-api-tools",
    "skills-gws",
    "04_Archive",
    "05_Attachments",
}
EXCLUDE_SCAN_PREFIXES = {"06_Metadata/Templates"}

# 링크 인덱스에서 제외할 파일명 (링크 타겟으로 부적절한 설정 파일)
EXCLUDE_LINK_TARGETS = {"CLAUDE", "GEMINI", "AGENTS"}

# 구조 검사(고아/스테일/연결부족) 추가 제외
STRUCTURE_EXCLUDE_PREFIXES = {
    "00_Inbox",  # 받은 편지함
    "06_Metadata",  # 메타데이터/템플릿
    "03_Resources/Index",  # 색인 폴더 (링크 안 받는 게 정상)
    # ── 개인 참고 기록 (지식 그래프 노드 아님) ──
    "02_Areas/개인_금융",
    "02_Areas/개인_여행",
    "02_Areas/개인_성장",
    "02_Areas/개인_홈",
}
STRUCTURE_EXCLUDE_FILES = {"hot.md", "Dashboard.md", "GEMINI.md", "CLAUDE.md"}

DEFAULT_STALE_DAYS = 180
DEFAULT_MIN_SIMILARITY = 70
ALL_CHECKS = ["structure", "links", "meta", "tags"]

# 메타데이터 검증 규칙
REQUIRED_FIELDS = {"type", "author", "created", "updated", "tags", "status"}
TYPE_REQUIRED_FIELDS = {
    "troubleshooting": {"customer", "responder"},
    "people": {"organization", "group", "role"},
    "script": {"language"},
}
VALID_STATUS = {"inProgress", "completed", "archived"}
PEOPLE_VALID_STATUS = {"active", "inactive"}  # people 노트는 active/inactive 사용
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# ANSI 색상
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"
BOLD = "\033[1m"
RESET = "\033[0m"

FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
INLINE_TAG_PATTERN = re.compile(r"#([a-zA-Z0-9가-힣_-]+(?:/[a-zA-Z0-9가-힣_-]+)*)")
WIKILINK_PATTERN = re.compile(r"\[\[([^\]|#]+)(?:#([^\]|]+))?(?:\|([^\]]+))?\]\]")


# ──────────────────────────────────────────
# 스캔 (단일 패스)
# ──────────────────────────────────────────


class FileRecord:
    """파일 1개의 스캔 결과"""

    def __init__(self, path: Path, vault: Path, content: str):
        self.path = path
        self.rel = str(path.relative_to(vault))
        self.stem = path.stem
        self.content = content
        self.fm = self._parse_frontmatter(content)  # None = frontmatter 없음
        self.links = self._extract_links(content)  # [(line_num, target, section, raw)]

    @staticmethod
    def _parse_frontmatter(content: str):
        match = FRONTMATTER_PATTERN.match(content)
        if not match:
            return None
        try:
            metadata = yaml.safe_load(match.group(1))
            return metadata if isinstance(metadata, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _extract_links(content: str):
        """코드블록 제외, 라인 번호 포함 위키링크 추출"""
        links = []
        in_code_block = False
        for line_num, line in enumerate(content.splitlines(), 1):
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue
            line_no_code = re.sub(r"`[^`]+`", "", line)
            for m in WIKILINK_PATTERN.finditer(line_no_code):
                target = m.group(1).strip()
                if target.endswith(".md"):
                    target = target[:-3]
                section = m.group(2).strip() if m.group(2) else None
                links.append((line_num, target, section, m.group(0)))
        return links


def is_scan_excluded(path: Path, vault: Path) -> bool:
    rel = path.relative_to(vault)
    if rel.parts and rel.parts[0] in EXCLUDE_SCAN_DIRS:
        return True
    rel_str = str(rel)
    return any(rel_str.startswith(p) for p in EXCLUDE_SCAN_PREFIXES)


def scan_vault(vault: Path) -> list:
    """전체 볼트 단일 스캔 → FileRecord 목록"""
    records = []
    for md_file in sorted(vault.rglob("*.md")):
        if is_scan_excluded(md_file, vault):
            continue
        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            print(f"{YELLOW}⚠️  파일 읽기 오류: {md_file} - {e}{RESET}")
            continue
        records.append(FileRecord(md_file, vault, content))
    return records


def in_scope(rec: FileRecord, scope: str) -> bool:
    return not scope or rec.rel.startswith(scope)


def print_section(title: str, color: str = CYAN):
    print(f"\n{color}{BOLD}{'═' * 60}{RESET}")
    print(f"{color}{BOLD}  {title}{RESET}")
    print(f"{color}{BOLD}{'═' * 60}{RESET}")


# ──────────────────────────────────────────
# 검사 1: 구조 (고아 / 스테일 / 연결 부족)
# ──────────────────────────────────────────


def structure_excluded(rec: FileRecord) -> bool:
    if rec.path.name in STRUCTURE_EXCLUDE_FILES:
        return True
    return any(rec.rel.startswith(p) for p in STRUCTURE_EXCLUDE_PREFIXES)


def check_structure(records: list, scope: str, stale_days: int) -> dict:
    targets = [r for r in records if not structure_excluded(r) and in_scope(r, scope)]

    # 고아 노트: 전체 볼트의 링크 대상 수집 (scope와 무관하게 전역)
    all_linked_stems = set()
    for rec in records:
        for _, target, _, _ in rec.links:
            all_linked_stems.add(Path(target).stem if "/" in target else target)

    orphans = sorted(r.rel for r in targets if r.stem not in all_linked_stems)

    # 스테일 노트: 중요 타입만
    check_types = {"concept", "troubleshooting", "documentation", "customer"}
    today = date.today()
    stale = []
    for rec in targets:
        fm = rec.fm or {}
        if str(fm.get("type", "")) not in check_types:
            continue
        updated_str = str(fm.get("updated", ""))
        try:
            updated_date = datetime.strptime(updated_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        delta = (today - updated_date).days
        if delta >= stale_days:
            stale.append(
                {
                    "path": rec.rel,
                    "type": fm["type"],
                    "updated": updated_str,
                    "days_ago": delta,
                }
            )
    stale.sort(key=lambda x: x["days_ago"], reverse=True)

    # 연결 부족 Concept
    crossref = []
    for rec in targets:
        fm = rec.fm or {}
        if str(fm.get("type", "")) != "concept":
            continue
        has_related = "## 관련 개념" in rec.content or "## 관련 문서" in rec.content
        link_count = len({t for _, t, _, _ in rec.links})
        if not has_related or link_count < 2:
            crossref.append(
                {
                    "path": rec.rel,
                    "has_related_section": has_related,
                    "link_count": link_count,
                }
            )
    crossref.sort(key=lambda x: x["link_count"])

    # ── 출력 ──
    print_section("1. 고아 노트 (Orphan Notes)", RED)
    print(f"  {YELLOW}아무 노트도 링크하지 않는 노트입니다.{RESET}")
    if orphans:
        print(f"\n  {RED}발견: {len(orphans)}개{RESET}")
        for p in orphans[:30]:
            print(f"    📄 {p}")
        if len(orphans) > 30:
            print(f"    ... 외 {len(orphans) - 30}개")
    else:
        print(f"\n  {GREEN}✅ 고아 노트 없음{RESET}")

    print_section("2. 스테일 노트 (Stale Notes)", YELLOW)
    print(f"  {YELLOW}{stale_days}일 이상 업데이트되지 않은 중요 노트입니다.{RESET}")
    if stale:
        print(f"\n  {YELLOW}발견: {len(stale)}개{RESET}")
        for item in stale[:20]:
            print(f"    🕰️  [{item['type']}] {item['path']}")
            print(
                f"        마지막 업데이트: {item['updated']} ({item['days_ago']}일 전)"
            )
    else:
        print(f"\n  {GREEN}✅ 스테일 노트 없음{RESET}")

    print_section("3. 연결 부족 Concept 노트", YELLOW)
    print(
        f"  {YELLOW}'관련 개념' 섹션이 없거나 위키링크가 2개 미만인 Concept 노트입니다.{RESET}"
    )
    if crossref:
        print(f"\n  {YELLOW}발견: {len(crossref)}개{RESET}")
        for item in crossref[:20]:
            flags = []
            if not item["has_related_section"]:
                flags.append("관련 개념 섹션 없음")
            if item["link_count"] < 2:
                flags.append(f"링크 {item['link_count']}개")
            print(f"    🔗 {item['path']}")
            print(f"        ⚠️  {', '.join(flags)}")
    else:
        print(f"\n  {GREEN}✅ 모든 Concept 노트가 잘 연결되어 있습니다.{RESET}")

    return {
        "고아 노트": len(orphans),
        "스테일 노트": len(stale),
        "연결 부족 Concept": len(crossref),
    }


# ──────────────────────────────────────────
# 검사 2: 위키링크 (깨진 / 모호 / 섹션 오류)
# ──────────────────────────────────────────


def build_link_index(records: list) -> dict:
    """stem -> [FileRecord] 링크 인덱스 (항상 전체 볼트 기준)"""
    index = defaultdict(list)
    for rec in records:
        if rec.stem not in EXCLUDE_LINK_TARGETS:
            index[rec.stem].append(rec)
    return index


def count_broken_links(records: list) -> int:
    """깨진 위키링크 수만 조용히 계산 (외부 스크립트용, 예: vault-report)"""
    index = build_link_index(records)
    return sum(
        1
        for rec in records
        for _, target, _, _ in rec.links
        if "../" not in target and target not in index
    )


def check_links(records: list, scope: str) -> dict:
    index = build_link_index(records)

    broken, ambiguous, section_errors = [], [], []
    total_links = 0
    for rec in records:
        if not in_scope(rec, scope):
            continue
        for line_num, target, section, raw in rec.links:
            if "../" in target:
                continue  # 상대경로 링크는 검증 제외 (고아 판정에는 반영됨)
            total_links += 1
            entry = (rec.rel, line_num, target, section, raw)
            matches = index.get(target)
            if not matches:
                broken.append(entry)
            elif len(matches) > 1:
                ambiguous.append(entry)
            elif section and not _has_section(matches[0].content, section):
                section_errors.append(entry)

    valid_count = total_links - len(broken) - len(ambiguous) - len(section_errors)
    valid_pct = (valid_count / total_links * 100) if total_links else 100.0

    def suggest_similar(target: str, threshold: float = 0.6):
        scored = [
            (stem, SequenceMatcher(None, target.lower(), stem.lower()).ratio())
            for stem in index
        ]
        scored = [s for s in scored if s[1] >= threshold]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:5]

    # ── 출력 ──
    print_section("🔗 Link Health", RED if broken else GREEN)
    print(f"  총 위키링크: {total_links}개")
    print(f"  ✅ 유효한 링크: {valid_count}개 ({valid_pct:.1f}%)")
    print(f"  ❌ 깨진 링크: {len(broken)}개")
    print(f"  ⚠️  모호한 링크: {len(ambiguous)}개")
    print(f"  🔧 섹션 오류: {len(section_errors)}개")

    if broken:
        print(f"\n{RED}{BOLD}❌ Broken Links:{RESET}")
        broken_by_file = defaultdict(list)
        for entry in broken:
            broken_by_file[entry[0]].append(entry)
        for rel, entries in list(broken_by_file.items())[:10]:
            print(f"\n  📄 {CYAN}{rel}{RESET}")
            for _, line_num, target, _, raw in entries[:5]:
                print(f"    Line {line_num}: {RED}{raw}{RESET}")
                suggestions = suggest_similar(target)
                if suggestions:
                    stem, sim = suggestions[0]
                    print(f"      💡 제안: [[{stem}]] (유사도: {sim * 100:.0f}%)")
        if len(broken_by_file) > 10:
            print(f"\n  ... 외 {len(broken_by_file) - 10}개 파일")

    if ambiguous:
        print(f"\n{YELLOW}{BOLD}⚠️  Ambiguous Links (동일 파일명 중복):{RESET}")
        by_target = defaultdict(list)
        for entry in ambiguous:
            by_target[entry[2]].append(entry)
        for target, entries in list(by_target.items())[:5]:
            print(f"\n  🔀 {YELLOW}{target}{RESET} (참조: {len(entries)}개)")
            for match in index[target]:
                print(f"    📍 {match.rel}")

    if section_errors:
        print(f"\n{YELLOW}{BOLD}🔧 Section Errors:{RESET}")
        for rel, line_num, _, section, raw in section_errors[:10]:
            print(f"  📄 {rel}:{line_num}")
            print(f"    {raw}")
            print(f"    ❌ 섹션 없음: #{section}")

    return {
        "깨진 링크": len(broken),
        "모호한 링크": len(ambiguous),
        "섹션 오류": len(section_errors),
    }


def _has_section(content: str, section: str) -> bool:
    headings = re.findall(r"^#{1,6}\s+(.+)$", content, re.MULTILINE)
    norm = lambda s: re.sub(r"[^\w가-힣]", "", s.lower())
    return norm(section) in {norm(h) for h in headings}


# ──────────────────────────────────────────
# 검사 3: 메타데이터 (frontmatter)
# ──────────────────────────────────────────


def check_meta(records: list, scope: str) -> dict:
    targets = [r for r in records if in_scope(r, scope)]
    issues = []  # (rel, issue_type, field, message)
    no_frontmatter = []
    valid_count = 0

    for rec in targets:
        if rec.fm is None:
            no_frontmatter.append(rec.rel)
            continue
        fm = rec.fm
        if not fm:
            issues.append(
                (rec.rel, "empty", "frontmatter", "Frontmatter가 비어있습니다")
            )
            continue

        before = len(issues)

        for field in REQUIRED_FIELDS:
            if field not in fm:
                issues.append(
                    (rec.rel, "missing", field, f"필수 필드 '{field}'가 누락되었습니다")
                )

        note_type = fm.get("type")
        for field in TYPE_REQUIRED_FIELDS.get(note_type, set()):
            if field not in fm:
                issues.append(
                    (
                        rec.rel,
                        "missing",
                        field,
                        f"type '{note_type}'에 필요한 필드 '{field}'가 누락되었습니다",
                    )
                )

        author = fm.get("author")
        if author is not None:
            if not isinstance(author, list):
                issues.append(
                    (
                        rec.rel,
                        "invalid",
                        "author",
                        f"author는 리스트 형식이어야 합니다 (현재: {type(author).__name__})",
                    )
                )
            elif author and not all(
                isinstance(a, str) and a.startswith("[[") for a in author
            ):
                issues.append(
                    (
                        rec.rel,
                        "invalid",
                        "author",
                        "author는 위키링크 형식이어야 합니다 (예: [[이상훈]])",
                    )
                )

        for date_field in ("created", "updated"):
            if date_field in fm:
                date_value = str(fm[date_field])
                if not DATE_PATTERN.match(date_value):
                    issues.append(
                        (
                            rec.rel,
                            "incorrect_format",
                            date_field,
                            f"날짜 형식이 올바르지 않습니다 (현재: {date_value}, 필요: YYYY-MM-DD)",
                        )
                    )
                else:
                    try:
                        datetime.strptime(date_value, "%Y-%m-%d")
                    except ValueError:
                        issues.append(
                            (
                                rec.rel,
                                "invalid",
                                date_field,
                                f"유효하지 않은 날짜입니다: {date_value}",
                            )
                        )

        if "status" in fm:
            valid_status = (
                PEOPLE_VALID_STATUS if note_type == "people" else VALID_STATUS
            )
            if fm["status"] not in valid_status:
                issues.append(
                    (
                        rec.rel,
                        "invalid",
                        "status",
                        f"유효하지 않은 status 값입니다 (현재: {fm['status']}, "
                        f"가능: {', '.join(sorted(valid_status))})",
                    )
                )

        for list_field in ("tags", "aliases"):
            value = fm.get(list_field)
            if value is not None and not isinstance(value, list):
                issues.append(
                    (
                        rec.rel,
                        "invalid",
                        list_field,
                        f"{list_field}는 리스트 형식이어야 합니다 (현재: {type(value).__name__})",
                    )
                )

        if len(issues) == before:
            valid_count += 1

    total = len(targets)
    files_with_issues = len({i[0] for i in issues})

    # ── 출력 ──
    print_section("📋 Metadata Validation", RED if issues or no_frontmatter else GREEN)
    print(f"  검사한 파일: {total}개")
    if total:
        print(f"  ✅ 정상 파일: {valid_count}개 ({valid_count / total * 100:.1f}%)")
    print(f"  ⚠️  이슈 있는 파일: {files_with_issues}개")
    print(f"  ❌ Frontmatter 없는 파일: {len(no_frontmatter)}개")
    print(f"  🔧 총 이슈 수: {len(issues)}개")

    if no_frontmatter:
        print(f"\n{RED}{BOLD}❌ Frontmatter 없는 파일:{RESET}")
        for rel in no_frontmatter[:10]:
            print(f"  📄 {CYAN}{rel}{RESET}")
        if len(no_frontmatter) > 10:
            print(f"  ... 외 {len(no_frontmatter) - 10}개")

    by_type = defaultdict(list)
    for issue in issues:
        by_type[issue[1]].append(issue)

    if by_type.get("missing"):
        print(f"\n{RED}{BOLD}❌ 누락된 필드:{RESET}")
        by_field = defaultdict(list)
        for issue in by_type["missing"]:
            by_field[issue[2]].append(issue)
        for field, items in sorted(
            by_field.items(), key=lambda x: len(x[1]), reverse=True
        ):
            print(f"\n  🔸 {YELLOW}{field}{RESET} ({len(items)}개 파일)")
            for rel, *_ in items[:5]:
                print(f"    📄 {rel}")
            if len(items) > 5:
                print(f"    ... 외 {len(items) - 5}개")

    for issue_type, label in (
        ("incorrect_format", "⚠️  잘못된 형식:"),
        ("invalid", "⚠️  유효하지 않은 값:"),
    ):
        if by_type.get(issue_type):
            print(f"\n{YELLOW}{BOLD}{label}{RESET}")
            for rel, _, field, message in by_type[issue_type][:10]:
                print(f"  📄 {rel}")
                print(f"    ❌ {field}: {message}")

    return {"메타데이터 이슈": len(issues), "Frontmatter 없음": len(no_frontmatter)}


# ──────────────────────────────────────────
# 검사 4: 태그 (유사 태그 / 드문 태그)
# ──────────────────────────────────────────


def check_tags(records: list, min_similarity: int, export_json: str = None) -> dict:
    # 태그 분석은 병합 판단을 위해 항상 전체 볼트 기준 (scope 미적용)
    tag_frequency = Counter()
    for rec in records:
        tags = set()
        fm = rec.fm or {}
        if isinstance(fm.get("tags"), list):
            for tag in fm["tags"]:
                if isinstance(tag, str) and tag.lstrip("#").strip():
                    tags.add(tag.lstrip("#").strip())
        # 인라인 태그 (frontmatter·코드블록 제거 후)
        body = FRONTMATTER_PATTERN.sub("", rec.content)
        body = re.sub(r"```[\s\S]*?```|`[^`]+`", "", body)
        for m in INLINE_TAG_PATTERN.finditer(body):
            tags.add(m.group(1))
        for tag in tags:
            tag_frequency[tag] += 1

    threshold = min_similarity / 100.0

    def similarity(t1: str, t2: str) -> float:
        a, b = t1.lower(), t2.lower()
        score = SequenceMatcher(None, a, b).ratio()
        if (a.endswith("s") and a[:-1] == b) or (b.endswith("s") and b[:-1] == a):
            score += 0.1
        if a.replace("-", "_") == b.replace("-", "_"):
            score += 0.1
        return min(score, 1.0)

    tags = list(tag_frequency.keys())
    similar_pairs = []
    for i, t1 in enumerate(tags):
        for t2 in tags[i + 1 :]:
            if t1.startswith(t2 + "/") or t2.startswith(t1 + "/"):
                continue
            score = similarity(t1, t2)
            if score >= threshold:
                similar_pairs.append((t1, t2, score))
    similar_pairs.sort(key=lambda x: x[2], reverse=True)

    rare_tags = {t: c for t, c in tag_frequency.items() if c <= 2}
    nested_tags = {t for t in tag_frequency if "/" in t}

    # ── 출력 ──
    print_section("🏷️  Tag Normalization", YELLOW if similar_pairs else GREEN)
    print(f"  총 고유 태그: {len(tag_frequency)}개")
    print(f"  🔀 유사 태그 쌍: {len(similar_pairs)}개")
    print(f"  📁 계층 태그: {len(nested_tags)}개")
    print(f"  🔸 드문 태그 (1-2회): {len(rare_tags)}개")

    print(f"\n{BOLD}{GREEN}🏆 Top 20 Most Used Tags:{RESET}")
    for i, (tag, count) in enumerate(tag_frequency.most_common(20), 1):
        print(f"  {i:2d}. #{GREEN}{tag}{RESET} ({count}회)")

    if similar_pairs:
        print(f"\n{YELLOW}{BOLD}🔀 Similar Tags (병합 후보):{RESET}")
        for i, (t1, t2, score) in enumerate(similar_pairs[:20], 1):
            c1, c2 = tag_frequency[t1], tag_frequency[t2]
            print(f"\n  {i:2d}. {YELLOW}유사도: {score * 100:.1f}%{RESET}")
            print(f"      #{t1} ({c1}회) ↔ #{t2} ({c2}회)")
            merge = f"#{t2} → #{t1}" if c1 > c2 else f"#{t1} → #{t2}"
            print(f"      {CYAN}→ 권장: {merge}{RESET}")
        if len(similar_pairs) > 20:
            print(f"\n  ... 외 {len(similar_pairs) - 20}개 쌍")

    if rare_tags:
        print(f"\n{BLUE}{BOLD}🔸 Rare Tags (1-2회 사용):{RESET}")
        for i, (tag, count) in enumerate(
            sorted(rare_tags.items(), key=lambda x: x[1])[:20], 1
        ):
            print(f"  {i:2d}. #{BLUE}{tag}{RESET} ({count}회)")
        if len(rare_tags) > 20:
            print(f"  ... 외 {len(rare_tags) - 20}개")

    if export_json:
        report = {
            "summary": {
                "total_tags": len(tag_frequency),
                "similar_pairs": len(similar_pairs),
                "nested_tags": len(nested_tags),
                "rare_tags": len(rare_tags),
            },
            "tag_frequency": dict(tag_frequency.most_common()),
            "similar_pairs": [
                {
                    "tag1": t1,
                    "tag2": t2,
                    "similarity": round(s * 100, 1),
                    "count1": tag_frequency[t1],
                    "count2": tag_frequency[t2],
                    "recommended_merge": (
                        f"{t2} → {t1}"
                        if tag_frequency[t1] > tag_frequency[t2]
                        else f"{t1} → {t2}"
                    ),
                }
                for t1, t2, s in similar_pairs
            ],
            "rare_tags": rare_tags,
        }
        with open(export_json, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n{GREEN}✅ 태그 리포트 저장: {export_json}{RESET}")

    return {"유사 태그 쌍": len(similar_pairs), "드문 태그": len(rare_tags)}


# ──────────────────────────────────────────
# main
# ──────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Obsidian 볼트 통합 건강도 검사기 (구조/링크/메타데이터/태그)"
    )
    parser.add_argument("vault", help="볼트 루트 경로")
    parser.add_argument(
        "--checks",
        default=",".join(ALL_CHECKS),
        help=f"실행할 검사 (쉼표 구분, 기본: {','.join(ALL_CHECKS)})",
    )
    parser.add_argument("--scope", help="검사할 하위 폴더 경로 (태그 검사에는 미적용)")
    parser.add_argument(
        "--stale-days",
        type=int,
        default=DEFAULT_STALE_DAYS,
        help=f"스테일 기준 일수 (기본: {DEFAULT_STALE_DAYS}일)",
    )
    parser.add_argument(
        "--min-similarity",
        type=int,
        default=DEFAULT_MIN_SIMILARITY,
        help=f"유사 태그 최소 유사도 %% (기본: {DEFAULT_MIN_SIMILARITY})",
    )
    parser.add_argument(
        "--export-json", metavar="FILE", help="태그 리포트를 JSON으로 저장"
    )
    args = parser.parse_args()

    vault = Path(args.vault).resolve()
    if not vault.exists():
        print(f"{RED}오류: 볼트 경로가 존재하지 않습니다: {vault}{RESET}")
        sys.exit(1)

    checks = [c.strip() for c in args.checks.split(",") if c.strip()]
    invalid = [c for c in checks if c not in ALL_CHECKS]
    if invalid:
        print(
            f"{RED}오류: 알 수 없는 검사: {', '.join(invalid)} "
            f"(가능: {', '.join(ALL_CHECKS)}){RESET}"
        )
        sys.exit(1)

    scope = args.scope.rstrip("/") + "/" if args.scope else None

    print(f"\n{BOLD}🔍 Vault Lint 실행 중...{RESET}")
    print(f"  볼트: {vault}")
    print(f"  검사: {', '.join(checks)}")
    if scope:
        print(f"  범위: {scope}")

    records = scan_vault(vault)
    print(f"  검사 파일: {len(records)}개")

    summary = {}
    if "structure" in checks:
        summary.update(check_structure(records, scope, args.stale_days))
    if "links" in checks:
        summary.update(check_links(records, scope))
    if "meta" in checks:
        summary.update(check_meta(records, scope))
    if "tags" in checks:
        summary.update(check_tags(records, args.min_similarity, args.export_json))

    # ── 요약 ──
    print_section("📊 요약", CYAN)
    print(f"  검사 파일: {len(records)}개")
    for label, count in summary.items():
        print(f"  {label}: {count}개")

    total_issues = sum(summary.values())
    if total_issues == 0:
        print(f"\n  {GREEN}{BOLD}✅ 볼트 상태 양호!{RESET}")
    else:
        print(f"\n  {YELLOW}총 {total_issues}개 항목이 개선을 필요로 합니다.{RESET}")
        print(f"  {YELLOW}/lint 스킬로 Claude에게 수정을 요청하세요.{RESET}")
    print()


if __name__ == "__main__":
    main()
