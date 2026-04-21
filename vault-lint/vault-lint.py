#!/usr/bin/env python3
"""
vault-lint.py — Obsidian 볼트 건강도 검사기
고아 노트, 스테일 노트, 누락 교차참조를 탐지합니다.

Usage:
  python3 vault-lint.py <vault_path> [--scope <path>] [--stale-days <days>]
"""

import os
import re
import sys
import argparse
from datetime import datetime, date
from pathlib import Path

# ──────────────────────────────────────────
# 설정
# ──────────────────────────────────────────

EXCLUDE_DIRS = {
    "04_Archive", "05_Attachments", "06_Metadata",
    ".git", ".obsidian", ".trash", ".claude", "node_modules",
    "scripts-repo", "scripts-skills", "scripts-finance",
    "ons-api-tools", "scripts-skills"
}

EXCLUDE_FILES = {"hot.md", "Dashboard.md", "GEMINI.md", "CLAUDE.md"}

# 이 폴더의 노트는 고아 검사에서 제외 (Index, template 등은 링크 안 받는 게 정상)
ORPHAN_EXCLUDE_DIRS = {
    "03_Resources/Index",
    "06_Metadata/Templates",
    "00_Inbox",
}

DEFAULT_STALE_DAYS = 180  # 6개월


# ──────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────

def is_excluded(path: Path, vault: Path) -> bool:
    rel = path.relative_to(vault)
    parts = rel.parts
    if parts[0] in EXCLUDE_DIRS:
        return True
    if path.name in EXCLUDE_FILES:
        return True
    return False


def is_orphan_excluded(path: Path, vault: Path) -> bool:
    rel = str(path.relative_to(vault))
    for ex in ORPHAN_EXCLUDE_DIRS:
        if rel.startswith(ex):
            return True
    return False


def get_frontmatter(content: str) -> dict:
    if not content.startswith("---"):
        return {}
    end = content.find("---", 3)
    if end == -1:
        return {}
    fm_text = content[3:end]
    result = {}
    for line in fm_text.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            result[key.strip()] = val.strip()
    return result


def extract_wikilinks(content: str) -> set:
    """코드블록 제외하고 위키링크 추출"""
    # 코드블록 제거
    content_no_code = re.sub(r"```[\s\S]*?```", "", content)
    content_no_code = re.sub(r"`[^`]+`", "", content_no_code)
    links = re.findall(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]", content_no_code)
    return {l.strip() for l in links}


# ──────────────────────────────────────────
# 인덱스 구축
# ──────────────────────────────────────────

def build_index(vault: Path, scope: Path = None) -> dict:
    """파일명(stem) → 파일 경로 매핑"""
    index = {}
    root = scope if scope and scope.is_dir() else vault

    for md_file in root.rglob("*.md"):
        if is_excluded(md_file, vault):
            continue
        stem = md_file.stem
        if stem not in index:
            index[stem] = []
        index[stem].append(md_file)

    return index


def build_all_files(vault: Path) -> list:
    """전체 볼트 .md 파일 목록"""
    files = []
    for md_file in vault.rglob("*.md"):
        if is_excluded(md_file, vault):
            continue
        files.append(md_file)
    return files


# ──────────────────────────────────────────
# 검사 1: 고아 노트 (아무도 링크하지 않는 노트)
# ──────────────────────────────────────────

def find_orphans(vault: Path, all_files: list) -> list:
    """모든 파일에서 위키링크를 수집하고, 한 번도 링크되지 않은 노트를 찾음"""

    # 전체 링크 수집 (링크 대상 stem 집합)
    all_linked_stems = set()
    for md_file in all_files:
        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for link in extract_wikilinks(content):
            # 파일명에서 경로 제거
            stem = Path(link).stem if "/" in link else link
            all_linked_stems.add(stem)

    orphans = []
    for md_file in all_files:
        if is_orphan_excluded(md_file, vault):
            continue
        stem = md_file.stem
        if stem not in all_linked_stems:
            rel = md_file.relative_to(vault)
            orphans.append(str(rel))

    return sorted(orphans)


# ──────────────────────────────────────────
# 검사 2: 스테일 노트 (오래된 노트)
# ──────────────────────────────────────────

def find_stale_notes(vault: Path, all_files: list, stale_days: int) -> list:
    """updated 필드가 stale_days 이상 지난 노트 탐지"""
    today = date.today()
    stale = []

    # concept, troubleshooting, documentation 타입만 검사 (중요 문서)
    CHECK_TYPES = {"concept", "troubleshooting", "documentation", "customer"}

    for md_file in all_files:
        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        fm = get_frontmatter(content)
        note_type = fm.get("type", "").strip('"').strip("'")
        if note_type not in CHECK_TYPES:
            continue

        updated_str = fm.get("updated", "").strip('"').strip("'")
        if not updated_str:
            continue

        try:
            updated_date = datetime.strptime(updated_str, "%Y-%m-%d").date()
            delta = (today - updated_date).days
            if delta >= stale_days:
                rel = md_file.relative_to(vault)
                stale.append({
                    "path": str(rel),
                    "type": note_type,
                    "updated": updated_str,
                    "days_ago": delta
                })
        except ValueError:
            continue

    return sorted(stale, key=lambda x: x["days_ago"], reverse=True)


# ──────────────────────────────────────────
# 검사 3: 누락 교차참조
# ──────────────────────────────────────────

def find_missing_crossrefs(vault: Path, all_files: list) -> list:
    """Concept 노트가 '관련 개념' 섹션 없거나 링크 2개 미만인 경우"""
    issues = []

    for md_file in all_files:
        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        fm = get_frontmatter(content)
        note_type = fm.get("type", "").strip('"').strip("'")
        if note_type != "concept":
            continue

        links = extract_wikilinks(content)
        has_related = "## 관련 개념" in content or "## 관련 문서" in content
        link_count = len(links)

        if not has_related or link_count < 2:
            rel = md_file.relative_to(vault)
            issues.append({
                "path": str(rel),
                "has_related_section": has_related,
                "link_count": link_count
            })

    return sorted(issues, key=lambda x: x["link_count"])


# ──────────────────────────────────────────
# 출력
# ──────────────────────────────────────────

CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_section(title: str, color: str = CYAN):
    print(f"\n{color}{BOLD}{'═' * 60}{RESET}")
    print(f"{color}{BOLD}  {title}{RESET}")
    print(f"{color}{BOLD}{'═' * 60}{RESET}")


def main():
    parser = argparse.ArgumentParser(description="Obsidian 볼트 건강도 검사기")
    parser.add_argument("vault", help="볼트 루트 경로")
    parser.add_argument("--scope", help="검사할 하위 폴더 경로 (선택)")
    parser.add_argument("--stale-days", type=int, default=DEFAULT_STALE_DAYS,
                        help=f"스테일 기준 일수 (기본: {DEFAULT_STALE_DAYS}일)")
    args = parser.parse_args()

    vault = Path(args.vault).resolve()
    scope = Path(args.scope).resolve() if args.scope else None

    if not vault.exists():
        print(f"{RED}오류: 볼트 경로가 존재하지 않습니다: {vault}{RESET}")
        sys.exit(1)

    print(f"\n{BOLD}🔍 Vault Lint 실행 중...{RESET}")
    print(f"  볼트: {vault}")
    if scope:
        print(f"  범위: {scope}")
    print(f"  스테일 기준: {args.stale_days}일")

    all_files = build_all_files(vault)
    total = len(all_files)

    print(f"  검사 파일: {total}개\n")

    # ── 1. 고아 노트 ──
    print_section("1. 고아 노트 (Orphan Notes)", RED)
    print(f"  {YELLOW}아무 노트도 링크하지 않는 노트입니다.{RESET}")
    orphans = find_orphans(vault, all_files)
    if orphans:
        print(f"\n  {RED}발견: {len(orphans)}개{RESET}")
        for p in orphans[:30]:
            print(f"    📄 {p}")
        if len(orphans) > 30:
            print(f"    ... 외 {len(orphans) - 30}개")
    else:
        print(f"\n  {GREEN}✅ 고아 노트 없음{RESET}")

    # ── 2. 스테일 노트 ──
    print_section("2. 스테일 노트 (Stale Notes)", YELLOW)
    print(f"  {YELLOW}{args.stale_days}일 이상 업데이트되지 않은 중요 노트입니다.{RESET}")
    stale = find_stale_notes(vault, all_files, args.stale_days)
    if stale:
        print(f"\n  {YELLOW}발견: {len(stale)}개{RESET}")
        for item in stale[:20]:
            print(f"    🕰️  [{item['type']}] {item['path']}")
            print(f"        마지막 업데이트: {item['updated']} ({item['days_ago']}일 전)")
    else:
        print(f"\n  {GREEN}✅ 스테일 노트 없음{RESET}")

    # ── 3. 누락 교차참조 ──
    print_section("3. 연결 부족 Concept 노트", YELLOW)
    print(f"  {YELLOW}'관련 개념' 섹션이 없거나 위키링크가 2개 미만인 Concept 노트입니다.{RESET}")
    crossref_issues = find_missing_crossrefs(vault, all_files)
    if crossref_issues:
        print(f"\n  {YELLOW}발견: {len(crossref_issues)}개{RESET}")
        for item in crossref_issues[:20]:
            flags = []
            if not item["has_related_section"]:
                flags.append("관련 개념 섹션 없음")
            if item["link_count"] < 2:
                flags.append(f"링크 {item['link_count']}개")
            print(f"    🔗 {item['path']}")
            print(f"        ⚠️  {', '.join(flags)}")
    else:
        print(f"\n  {GREEN}✅ 모든 Concept 노트가 잘 연결되어 있습니다.{RESET}")

    # ── 요약 ──
    print_section("📊 요약", CYAN)
    print(f"  검사 파일      : {total}개")
    print(f"  고아 노트      : {len(orphans)}개")
    print(f"  스테일 노트    : {len(stale)}개")
    print(f"  연결 부족 노트 : {len(crossref_issues)}개")

    total_issues = len(orphans) + len(stale) + len(crossref_issues)
    if total_issues == 0:
        print(f"\n  {GREEN}{BOLD}✅ 볼트 상태 양호!{RESET}")
    else:
        print(f"\n  {YELLOW}총 {total_issues}개 항목이 개선을 필요로 합니다.{RESET}")
        print(f"  {YELLOW}/vault-lint 스킬로 Claude에게 수정을 요청하세요.{RESET}")

    print()


if __name__ == "__main__":
    main()
