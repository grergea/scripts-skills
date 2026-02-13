#!/usr/bin/env python3
"""
Obsidian Metadata Validator
노트의 YAML frontmatter 메타데이터를 검증하는 스크립트

사용법:
    python obsidian-metadata-validator.py /path/to/vault
    python obsidian-metadata-validator.py /path/to/vault --scope 03_Resources/
    python obsidian-metadata-validator.py /path/to/vault --fix
"""

import os
import re
import argparse
from pathlib import Path
from typing import Dict, List, Set, Optional, Any
from collections import defaultdict
from datetime import datetime
import yaml
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

class MetadataIssue:
    """메타데이터 이슈를 담는 클래스"""
    def __init__(self, file_path: str, issue_type: str, field: str, message: str, severity: str = "warning"):
        self.file_path = file_path
        self.issue_type = issue_type  # missing, invalid, incorrect_format, etc.
        self.field = field
        self.message = message
        self.severity = severity  # error, warning, info

class MetadataValidator:
    """Obsidian 볼트의 메타데이터를 검증하는 클래스"""

    # 필수 필드
    REQUIRED_FIELDS = {'type', 'author', 'created', 'updated', 'tags', 'status'}

    # 타입별 추가 필수 필드
    TYPE_REQUIRED_FIELDS = {
        'concept': set(),  # 관련 개념, 관련 문서는 본문에서 확인
        'troubleshooting': {'customer', 'responder'},
        'customer': set(),
        'people': {'organization', 'group', 'role'},
        'script': {'language'},
        'meeting': set(),
    }

    # 유효한 status 값
    VALID_STATUS = {'inProgress', 'completed', 'archived'}

    # 날짜 형식 패턴
    DATE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')

    def __init__(self, vault_path: str, scope: str = None):
        self.vault_path = Path(vault_path)
        self.scope = scope

        # 제외할 폴더
        self.excluded_dirs = {'04_Archive', '05_Attachments', '06_Metadata/Templates',
                             '.git', '.obsidian', '.trash', '.claude'}

        # 결과 저장
        self.all_files: List[Path] = []
        self.issues: List[MetadataIssue] = []
        self.files_without_frontmatter: List[Path] = []
        self.valid_files_count = 0

    def scan_vault(self):
        """볼트의 모든 마크다운 파일 스캔"""
        print(f"{Colors.OKBLUE}📂 볼트 스캔 중...{Colors.ENDC}")

        search_path = self.vault_path / self.scope if self.scope else self.vault_path

        for md_file in search_path.rglob("*.md"):
            # 제외 폴더 확인
            if any(excluded in str(md_file) for excluded in self.excluded_dirs):
                continue

            self.all_files.append(md_file)

        print(f"{Colors.OKGREEN}✅ {len(self.all_files)}개 파일 발견{Colors.ENDC}")

    def parse_frontmatter(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """파일에서 YAML frontmatter 추출"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # frontmatter 추출 (--- 사이)
            match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
            if not match:
                return None

            yaml_content = match.group(1)

            # YAML 파싱
            metadata = yaml.safe_load(yaml_content)
            return metadata if isinstance(metadata, dict) else {}

        except Exception as e:
            return None

    def validate_file(self, file_path: Path):
        """개별 파일의 메타데이터 검증"""
        metadata = self.parse_frontmatter(file_path)

        # frontmatter 없음
        if metadata is None:
            self.files_without_frontmatter.append(file_path)
            return

        # 빈 frontmatter
        if not metadata:
            self.issues.append(MetadataIssue(
                str(file_path),
                "empty",
                "frontmatter",
                "Frontmatter가 비어있습니다",
                "error"
            ))
            return

        has_issues = False

        # 1. 필수 필드 검증
        for field in self.REQUIRED_FIELDS:
            if field not in metadata:
                self.issues.append(MetadataIssue(
                    str(file_path),
                    "missing",
                    field,
                    f"필수 필드 '{field}'가 누락되었습니다",
                    "error"
                ))
                has_issues = True

        # 2. type 필드 검증
        if 'type' in metadata:
            note_type = metadata['type']

            # 타입별 추가 필수 필드
            if note_type in self.TYPE_REQUIRED_FIELDS:
                for field in self.TYPE_REQUIRED_FIELDS[note_type]:
                    if field not in metadata:
                        self.issues.append(MetadataIssue(
                            str(file_path),
                            "missing",
                            field,
                            f"type '{note_type}'에 필요한 필드 '{field}'가 누락되었습니다",
                            "error"
                        ))
                        has_issues = True

        # 3. author 필드 검증
        if 'author' in metadata:
            author = metadata['author']
            if not isinstance(author, list):
                self.issues.append(MetadataIssue(
                    str(file_path),
                    "invalid",
                    "author",
                    f"author는 리스트 형식이어야 합니다 (현재: {type(author).__name__})",
                    "error"
                ))
                has_issues = True
            elif author and not all(isinstance(a, str) and a.startswith('[[') for a in author):
                self.issues.append(MetadataIssue(
                    str(file_path),
                    "invalid",
                    "author",
                    "author는 위키링크 형식이어야 합니다 (예: [[이상훈]])",
                    "warning"
                ))
                has_issues = True

        # 4. 날짜 필드 검증
        for date_field in ['created', 'updated']:
            if date_field in metadata:
                date_value = str(metadata[date_field])
                if not self.DATE_PATTERN.match(date_value):
                    self.issues.append(MetadataIssue(
                        str(file_path),
                        "incorrect_format",
                        date_field,
                        f"날짜 형식이 올바르지 않습니다 (현재: {date_value}, 필요: YYYY-MM-DD)",
                        "error"
                    ))
                    has_issues = True
                else:
                    # 날짜 유효성 검증
                    try:
                        datetime.strptime(date_value, '%Y-%m-%d')
                    except ValueError:
                        self.issues.append(MetadataIssue(
                            str(file_path),
                            "invalid",
                            date_field,
                            f"유효하지 않은 날짜입니다: {date_value}",
                            "error"
                        ))
                        has_issues = True

        # 5. status 필드 검증
        if 'status' in metadata:
            status_value = metadata['status']
            if status_value not in self.VALID_STATUS:
                self.issues.append(MetadataIssue(
                    str(file_path),
                    "invalid",
                    "status",
                    f"유효하지 않은 status 값입니다 (현재: {status_value}, 가능: {', '.join(self.VALID_STATUS)})",
                    "error"
                ))
                has_issues = True

        # 6. tags 필드 검증
        if 'tags' in metadata:
            tags = metadata['tags']
            if tags is not None and not isinstance(tags, list):
                self.issues.append(MetadataIssue(
                    str(file_path),
                    "invalid",
                    "tags",
                    f"tags는 리스트 형식이어야 합니다 (현재: {type(tags).__name__})",
                    "error"
                ))
                has_issues = True

        # 7. aliases 필드 검증
        if 'aliases' in metadata:
            aliases = metadata['aliases']
            if aliases is not None and not isinstance(aliases, list):
                self.issues.append(MetadataIssue(
                    str(file_path),
                    "invalid",
                    "aliases",
                    f"aliases는 리스트 형식이어야 합니다 (현재: {type(aliases).__name__})",
                    "warning"
                ))
                has_issues = True

        if not has_issues:
            self.valid_files_count += 1

    def validate_all(self):
        """모든 파일 검증"""
        print(f"{Colors.OKBLUE}🔍 메타데이터 검증 중...{Colors.ENDC}")

        for file_path in self.all_files:
            self.validate_file(file_path)

        print(f"{Colors.OKGREEN}✅ 검증 완료{Colors.ENDC}")

    def generate_report(self):
        """리포트 생성"""
        total_files = len(self.all_files)
        files_with_issues = len(set(issue.file_path for issue in self.issues))
        total_issues = len(self.issues)

        print("\n" + "="*80)
        print(f"{Colors.BOLD}{Colors.HEADER}📊 Metadata Validation Report{Colors.ENDC}")
        print("="*80 + "\n")

        # Summary
        print(f"{Colors.BOLD}Summary:{Colors.ENDC}")
        print(f"  검사한 파일: {total_files}개")
        print(f"  ✅ 정상 파일: {self.valid_files_count}개 ({self.valid_files_count/total_files*100:.1f}%)")
        print(f"  ⚠️  이슈 있는 파일: {files_with_issues}개")
        print(f"  ❌ Frontmatter 없는 파일: {len(self.files_without_frontmatter)}개")
        print(f"  🔧 총 이슈 수: {total_issues}개")

        # Frontmatter 없는 파일
        if self.files_without_frontmatter:
            print(f"\n{Colors.FAIL}{Colors.BOLD}❌ Frontmatter 없는 파일:{Colors.ENDC}")
            for file_path in self.files_without_frontmatter[:10]:
                rel_path = Path(file_path).relative_to(self.vault_path)
                print(f"  📄 {Colors.OKCYAN}{rel_path}{Colors.ENDC}")
            if len(self.files_without_frontmatter) > 10:
                print(f"  ... 외 {len(self.files_without_frontmatter) - 10}개")

        # 이슈를 타입별로 그룹화
        issues_by_type = defaultdict(list)
        for issue in self.issues:
            issues_by_type[issue.issue_type].append(issue)

        # 누락된 필드
        if 'missing' in issues_by_type:
            print(f"\n{Colors.FAIL}{Colors.BOLD}❌ 누락된 필드:{Colors.ENDC}")

            # 필드별로 그룹화
            missing_by_field = defaultdict(list)
            for issue in issues_by_type['missing']:
                missing_by_field[issue.field].append(issue)

            for field, issues in sorted(missing_by_field.items(), key=lambda x: len(x[1]), reverse=True):
                print(f"\n  🔸 {Colors.WARNING}{field}{Colors.ENDC} ({len(issues)}개 파일)")
                for issue in issues[:5]:
                    rel_path = Path(issue.file_path).relative_to(self.vault_path)
                    print(f"    📄 {rel_path}")
                if len(issues) > 5:
                    print(f"    ... 외 {len(issues) - 5}개")

        # 잘못된 형식
        if 'incorrect_format' in issues_by_type:
            print(f"\n{Colors.WARNING}{Colors.BOLD}⚠️  잘못된 형식:{Colors.ENDC}")
            for issue in issues_by_type['incorrect_format'][:10]:
                rel_path = Path(issue.file_path).relative_to(self.vault_path)
                print(f"  📄 {rel_path}")
                print(f"    ❌ {issue.field}: {issue.message}")

        # 유효하지 않은 값
        if 'invalid' in issues_by_type:
            print(f"\n{Colors.WARNING}{Colors.BOLD}⚠️  유효하지 않은 값:{Colors.ENDC}")
            for issue in issues_by_type['invalid'][:10]:
                rel_path = Path(issue.file_path).relative_to(self.vault_path)
                print(f"  📄 {rel_path}")
                print(f"    ❌ {issue.field}: {issue.message}")

        print("\n" + "="*80)

        # 전체 건강 상태
        healthy_pct = self.valid_files_count / total_files * 100 if total_files > 0 else 0

        if healthy_pct >= 95:
            print(f"{Colors.OKGREEN}{Colors.BOLD}✅ 볼트 메타데이터 상태: 매우 양호 ({healthy_pct:.1f}%){Colors.ENDC}")
        elif healthy_pct >= 90:
            print(f"{Colors.OKGREEN}{Colors.BOLD}✅ 볼트 메타데이터 상태: 양호 ({healthy_pct:.1f}%){Colors.ENDC}")
        elif healthy_pct >= 80:
            print(f"{Colors.WARNING}{Colors.BOLD}⚠️  볼트 메타데이터 상태: 보통 ({healthy_pct:.1f}%){Colors.ENDC}")
        else:
            print(f"{Colors.FAIL}{Colors.BOLD}❌ 볼트 메타데이터 상태: 주의 필요 ({healthy_pct:.1f}%){Colors.ENDC}")

        print("="*80 + "\n")

def main():
    parser = argparse.ArgumentParser(
        description='Obsidian 볼트의 메타데이터를 검증합니다.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  전체 볼트 검증:
    python obsidian-metadata-validator.py /path/to/vault

  특정 폴더만 검증:
    python obsidian-metadata-validator.py /path/to/vault --scope 03_Resources/

  자동 수정:
    python obsidian-metadata-validator.py /path/to/vault --fix
        """
    )

    parser.add_argument('vault_path', help='Obsidian 볼트 경로')
    parser.add_argument('--scope', help='검증할 폴더 (상대 경로)', default=None)
    parser.add_argument('--fix', action='store_true', help='자동 수정 모드 (향후 구현)')

    args = parser.parse_args()

    # 볼트 경로 검증
    vault_path = Path(args.vault_path)
    if not vault_path.exists():
        print(f"{Colors.FAIL}❌ 볼트 경로를 찾을 수 없습니다: {vault_path}{Colors.ENDC}")
        sys.exit(1)

    # 검증기 실행
    validator = MetadataValidator(str(vault_path), args.scope)

    try:
        validator.scan_vault()
        validator.validate_all()
        validator.generate_report()
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
