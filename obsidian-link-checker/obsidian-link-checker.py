#!/usr/bin/env python3
"""
Obsidian Link Health Checker
위키링크 무결성을 검사하고 깨진 링크를 탐지하는 스크립트

사용법:
    python obsidian-link-checker.py /path/to/vault
    python obsidian-link-checker.py /path/to/vault --scope 03_Resources/
    python obsidian-link-checker.py /path/to/vault --report-only
"""

import os
import re
import argparse
from pathlib import Path
from typing import Dict, List, Tuple, Set
from collections import defaultdict
from difflib import SequenceMatcher
import sys

# ANSI 색상 코드
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

class WikiLink:
    """위키링크 정보를 담는 클래스"""
    def __init__(self, file_path: str, line_num: int, raw_link: str):
        self.file_path = file_path
        self.line_num = line_num
        self.raw_link = raw_link

        # 링크 파싱
        self._parse_link()

    def _parse_link(self):
        """위키링크 패턴 파싱: [[file#section|alias]]"""
        # [[file#section|alias]] 형식
        match = re.match(r'\[\[([^\]|#]+)(?:#([^\]|]+))?(?:\|([^\]]+))?\]\]', self.raw_link)
        if match:
            self.target_file = match.group(1).strip()
            self.section = match.group(2).strip() if match.group(2) else None
            self.alias = match.group(3).strip() if match.group(3) else None
        else:
            self.target_file = self.raw_link.replace('[[', '').replace(']]', '').strip()
            self.section = None
            self.alias = None

class LinkHealthChecker:
    """Obsidian 볼트의 링크 건강 상태를 검사하는 클래스"""

    def __init__(self, vault_path: str, scope: str = None):
        self.vault_path = Path(vault_path)
        self.scope = scope

        # 제외할 폴더
        self.excluded_dirs = {'04_Archive', '05_Attachments', '06_Metadata/Templates',
                             '.git', '.obsidian', '.trash', '.claude'}

        # 파일 인덱스에서 제외할 파일명 (설정 파일, 링크 타겟으로 부적절)
        self.excluded_files = {'CLAUDE', 'GEMINI', 'AGENTS'}

        # 결과 저장
        self.all_files: Dict[str, Path] = {}  # filename -> full_path
        self.all_links: List[WikiLink] = []
        self.valid_links: List[WikiLink] = []
        self.broken_links: List[WikiLink] = []
        self.ambiguous_links: List[WikiLink] = []
        self.section_errors: List[WikiLink] = []

    def scan_vault(self):
        """볼트의 모든 마크다운 파일 스캔 (항상 전체 볼트에서 파일 인덱스 구축)"""
        print(f"{Colors.OKBLUE}📂 볼트 스캔 중...{Colors.ENDC}")

        # 파일 인덱스는 항상 전체 볼트에서 구축
        for md_file in self.vault_path.rglob("*.md"):
            # 제외 폴더 확인
            if any(excluded in str(md_file) for excluded in self.excluded_dirs):
                continue

            # 파일명 (확장자 제외)
            filename = md_file.stem

            # 설정 파일 제외
            if filename in self.excluded_files:
                continue

            # 중복 파일명 처리
            if filename in self.all_files:
                # 이미 존재하면 리스트로 변환
                if not isinstance(self.all_files[filename], list):
                    self.all_files[filename] = [self.all_files[filename]]
                self.all_files[filename].append(md_file)
            else:
                self.all_files[filename] = md_file

        print(f"{Colors.OKGREEN}✅ {len(self.all_files)}개 파일 발견{Colors.ENDC}")

    def extract_links(self):
        """파일에서 위키링크 추출 (scope 지정 시 해당 폴더만)"""
        print(f"{Colors.OKBLUE}🔗 위키링크 추출 중...{Colors.ENDC}")

        link_pattern = re.compile(r'\[\[([^\]]+)\]\]')
        inline_code_pattern = re.compile(r'`[^`]+`')

        # scope 지정 시 해당 폴더의 파일만 처리
        scope_path = self.vault_path / self.scope if self.scope else None

        for filename, file_path in self.all_files.items():
            # 리스트인 경우 모두 처리
            paths = [file_path] if not isinstance(file_path, list) else file_path

            for path in paths:
                # scope 필터링
                if scope_path and not str(path).startswith(str(scope_path)):
                    continue
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        lines = f.readlines()

                    in_code_block = False
                    for line_num, line in enumerate(lines, 1):
                        # 멀티라인 코드 블록 상태 추적
                        if line.strip().startswith('```'):
                            in_code_block = not in_code_block
                            continue
                        if in_code_block:
                            continue

                        # 인라인 코드 제거 후 위키링크 추출
                        line_no_code = inline_code_pattern.sub('', line)

                        for match in link_pattern.finditer(line_no_code):
                            raw_link = match.group(0)

                            # 상대경로 링크 제외 (../ 포함)
                            if '../' in raw_link:
                                continue

                            wiki_link = WikiLink(str(path), line_num, raw_link)
                            self.all_links.append(wiki_link)

                except Exception as e:
                    print(f"{Colors.WARNING}⚠️  파일 읽기 오류: {path} - {e}{Colors.ENDC}")

        print(f"{Colors.OKGREEN}✅ {len(self.all_links)}개 위키링크 추출{Colors.ENDC}")

    def validate_links(self):
        """링크 유효성 검증"""
        print(f"{Colors.OKBLUE}🔍 링크 검증 중...{Colors.ENDC}")

        for link in self.all_links:
            # 파일 존재 확인
            target = link.target_file

            # .md 확장자 제거
            if target.endswith('.md'):
                target = target[:-3]

            if target in self.all_files:
                file_path = self.all_files[target]

                # 모호한 링크 (여러 파일)
                if isinstance(file_path, list):
                    self.ambiguous_links.append(link)
                    continue

                # 섹션 검증
                if link.section:
                    if not self._validate_section(file_path, link.section):
                        self.section_errors.append(link)
                        continue

                self.valid_links.append(link)
            else:
                self.broken_links.append(link)

        print(f"{Colors.OKGREEN}✅ 검증 완료{Colors.ENDC}")

    def _validate_section(self, file_path: Path, section: str) -> bool:
        """섹션 존재 여부 확인"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 헤딩 추출 (##, ###, ...)
            headings = re.findall(r'^#{1,6}\s+(.+)$', content, re.MULTILINE)

            # 섹션명 정규화 (공백, 특수문자 제거)
            normalized_section = re.sub(r'[^\w가-힣]', '', section.lower())
            normalized_headings = [re.sub(r'[^\w가-힣]', '', h.lower()) for h in headings]

            return normalized_section in normalized_headings
        except:
            return False

    def suggest_similar_files(self, target: str, threshold: float = 0.5) -> List[Tuple[str, float]]:
        """유사한 파일명 제안 (Levenshtein 거리 기반)"""
        suggestions = []

        for filename in self.all_files.keys():
            # 유사도 계산
            similarity = SequenceMatcher(None, target.lower(), filename.lower()).ratio()

            if similarity >= threshold:
                suggestions.append((filename, similarity))

        # 유사도 높은 순 정렬
        suggestions.sort(key=lambda x: x[1], reverse=True)
        return suggestions[:5]

    def generate_report(self):
        """리포트 생성"""
        total_links = len(self.all_links)
        valid_count = len(self.valid_links)
        broken_count = len(self.broken_links)
        ambiguous_count = len(self.ambiguous_links)
        section_error_count = len(self.section_errors)

        valid_pct = (valid_count / total_links * 100) if total_links > 0 else 0

        print("\n" + "="*80)
        print(f"{Colors.BOLD}{Colors.HEADER}📊 Link Health Report{Colors.ENDC}")
        print("="*80 + "\n")

        # Summary
        print(f"{Colors.BOLD}Summary:{Colors.ENDC}")
        print(f"  검사한 파일: {len(self.all_files)}개")
        print(f"  총 위키링크: {total_links}개")
        print(f"  ✅ 유효한 링크: {valid_count}개 ({valid_pct:.1f}%)")
        print(f"  ❌ 깨진 링크: {broken_count}개")
        print(f"  ⚠️  모호한 링크: {ambiguous_count}개")
        print(f"  🔧 섹션 오류: {section_error_count}개")

        # 깨진 링크 상세
        if self.broken_links:
            print(f"\n{Colors.FAIL}{Colors.BOLD}❌ Broken Links:{Colors.ENDC}")

            # 파일별로 그룹화
            broken_by_file = defaultdict(list)
            for link in self.broken_links:
                broken_by_file[link.file_path].append(link)

            for file_path, links in list(broken_by_file.items())[:10]:  # 상위 10개 파일
                rel_path = Path(file_path).relative_to(self.vault_path)
                print(f"\n  📄 {Colors.OKCYAN}{rel_path}{Colors.ENDC}")

                for link in links[:5]:  # 파일당 5개까지
                    print(f"    Line {link.line_num}: {Colors.FAIL}{link.raw_link}{Colors.ENDC}")

                    # 유사 파일 제안
                    suggestions = self.suggest_similar_files(link.target_file, threshold=0.6)
                    if suggestions:
                        best_match = suggestions[0]
                        similarity_pct = best_match[1] * 100
                        print(f"      💡 제안: [[{best_match[0]}]] (유사도: {similarity_pct:.0f}%)")

        # 모호한 링크
        if self.ambiguous_links:
            print(f"\n{Colors.WARNING}{Colors.BOLD}⚠️  Ambiguous Links (동일 파일명 중복):{Colors.ENDC}")

            # 타겟별로 그룹화
            ambiguous_targets = defaultdict(list)
            for link in self.ambiguous_links:
                ambiguous_targets[link.target_file].append(link)

            for target, links in list(ambiguous_targets.items())[:5]:  # 상위 5개
                print(f"\n  🔀 {Colors.WARNING}{target}{Colors.ENDC} (참조: {len(links)}개)")

                # 실제 파일 위치들
                file_paths = self.all_files[target]
                for path in file_paths:
                    rel_path = Path(path).relative_to(self.vault_path)
                    print(f"    📍 {rel_path}")

        # 섹션 오류
        if self.section_errors:
            print(f"\n{Colors.WARNING}{Colors.BOLD}🔧 Section Errors:{Colors.ENDC}")

            for link in self.section_errors[:10]:  # 상위 10개
                rel_path = Path(link.file_path).relative_to(self.vault_path)
                print(f"  📄 {rel_path}:{link.line_num}")
                print(f"    {link.raw_link}")
                print(f"    ❌ 섹션 없음: #{link.section}")

        print("\n" + "="*80)

        # 전체 건강 상태
        if valid_pct >= 95:
            print(f"{Colors.OKGREEN}{Colors.BOLD}✅ 볼트 링크 상태: 매우 양호 ({valid_pct:.1f}%){Colors.ENDC}")
        elif valid_pct >= 90:
            print(f"{Colors.OKGREEN}{Colors.BOLD}✅ 볼트 링크 상태: 양호 ({valid_pct:.1f}%){Colors.ENDC}")
        elif valid_pct >= 80:
            print(f"{Colors.WARNING}{Colors.BOLD}⚠️  볼트 링크 상태: 보통 ({valid_pct:.1f}%){Colors.ENDC}")
        else:
            print(f"{Colors.FAIL}{Colors.BOLD}❌ 볼트 링크 상태: 주의 필요 ({valid_pct:.1f}%){Colors.ENDC}")

        print("="*80 + "\n")

def main():
    parser = argparse.ArgumentParser(
        description='Obsidian 볼트의 위키링크 건강 상태를 점검합니다.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  전체 볼트 점검:
    python obsidian-link-checker.py /path/to/vault

  특정 폴더만 점검:
    python obsidian-link-checker.py /path/to/vault --scope 03_Resources/

  리포트만 생성:
    python obsidian-link-checker.py /path/to/vault --report-only
        """
    )

    parser.add_argument('vault_path', help='Obsidian 볼트 경로')
    parser.add_argument('--scope', help='점검할 폴더 (상대 경로)', default=None)
    parser.add_argument('--report-only', action='store_true', help='리포트만 생성 (수정 안 함)')

    args = parser.parse_args()

    # 볼트 경로 검증
    vault_path = Path(args.vault_path)
    if not vault_path.exists():
        print(f"{Colors.FAIL}❌ 볼트 경로를 찾을 수 없습니다: {vault_path}{Colors.ENDC}")
        sys.exit(1)

    # 체커 실행
    checker = LinkHealthChecker(str(vault_path), args.scope)

    try:
        checker.scan_vault()
        checker.extract_links()
        checker.validate_links()
        checker.generate_report()
    except KeyboardInterrupt:
        print(f"\n{Colors.WARNING}⚠️  사용자에 의해 중단되었습니다.{Colors.ENDC}")
        sys.exit(0)
    except Exception as e:
        print(f"{Colors.FAIL}❌ 오류 발생: {e}{Colors.ENDC}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
