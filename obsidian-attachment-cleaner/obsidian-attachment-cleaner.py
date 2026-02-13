#!/usr/bin/env python3
"""
Obsidian Attachment Cleaner
미사용 첨부파일 탐지, 중복 파일 탐지, 대용량 파일 탐지 및 리포트 생성

사용법:
    python obsidian-attachment-cleaner.py /path/to/vault
    python obsidian-attachment-cleaner.py /path/to/vault --size-threshold 10
    python obsidian-attachment-cleaner.py /path/to/vault --delete-unused
"""

import os
import re
import argparse
import hashlib
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple
from collections import defaultdict

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

class AttachmentCleaner:
    """Obsidian 첨부파일 정리 클래스"""

    def __init__(self, vault_path: str, size_threshold_mb: int = 10):
        self.vault_path = Path(vault_path)
        self.size_threshold = size_threshold_mb * 1024 * 1024  # MB to bytes

        # 첨부파일 폴더
        self.attachment_folder = self.vault_path / '05_Attachments'
        self.scripts_attachments = self.vault_path / '05_Attachments' / 'Scripts_Attachments'

        # 제외 폴더
        self.excluded_dirs = {'.git', '.obsidian', '.trash', '.claude', '04_Archive'}

        # 이미지/첨부 파일 확장자
        self.attachment_extensions = {
            '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.bmp',
            '.pdf', '.mp4', '.mov', '.avi', '.mp3', '.wav',
            '.zip', '.tar', '.gz', '.json', '.csv', '.xlsx'
        }

        # 결과 저장
        self.all_attachments: Dict[str, Path] = {}  # filename -> path
        self.referenced_files: Set[str] = set()  # 참조된 파일명
        self.file_hashes: Dict[str, List[Path]] = defaultdict(list)  # hash -> [paths]

        # 위키링크 및 마크다운 임베드 패턴
        self.wiki_embed_pattern = re.compile(r'!\[\[([^\]]+)\]\]')
        self.md_embed_pattern = re.compile(r'!\[([^\]]*)\]\(([^\)]+)\)')
        self.code_block_pattern = re.compile(r'```[\s\S]*?```|`[^`]+`')

    def scan_attachments(self):
        """첨부파일 폴더 스캔"""
        print(f"{Colors.OKBLUE}📂 첨부파일 폴더 스캔 중...{Colors.ENDC}")

        if not self.attachment_folder.exists():
            print(f"{Colors.FAIL}❌ 첨부파일 폴더를 찾을 수 없습니다: {self.attachment_folder}{Colors.ENDC}")
            return

        for file_path in self.attachment_folder.rglob("*"):
            if file_path.is_file() and file_path.suffix.lower() in self.attachment_extensions:
                filename = file_path.name
                self.all_attachments[filename] = file_path

        print(f"{Colors.OKGREEN}✅ {len(self.all_attachments)}개 첨부파일 발견{Colors.ENDC}")

    def scan_references(self):
        """마크다운 파일에서 첨부파일 참조 추출"""
        print(f"{Colors.OKBLUE}🔍 마크다운 파일에서 참조 추출 중...{Colors.ENDC}")

        for md_file in self.vault_path.rglob("*.md"):
            # 제외 폴더 체크
            if any(excluded in str(md_file) for excluded in self.excluded_dirs):
                continue

            try:
                with open(md_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                # 코드 블록 제거
                content_no_code = self.code_block_pattern.sub('', content)

                # 위키링크 임베드: ![[image.png]]
                for match in self.wiki_embed_pattern.finditer(content_no_code):
                    filename = match.group(1).strip()
                    # 섹션 링크 제거
                    if '#' in filename:
                        filename = filename.split('#')[0]
                    self.referenced_files.add(filename)

                # 마크다운 임베드: ![alt](path/to/image.png)
                for match in self.md_embed_pattern.finditer(content_no_code):
                    filepath = match.group(2).strip()
                    # 파일명만 추출
                    filename = Path(filepath).name
                    self.referenced_files.add(filename)

            except Exception as e:
                print(f"{Colors.WARNING}⚠️  파일 읽기 오류: {md_file} - {e}{Colors.ENDC}")

        print(f"{Colors.OKGREEN}✅ {len(self.referenced_files)}개 참조 발견{Colors.ENDC}")

    def calculate_file_hash(self, file_path: Path) -> str:
        """파일 해시 계산 (MD5)"""
        hash_md5 = hashlib.md5()
        try:
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            print(f"{Colors.WARNING}⚠️  해시 계산 오류: {file_path} - {e}{Colors.ENDC}")
            return ""

    def find_duplicates(self):
        """중복 파일 탐지 (해시 기반)"""
        print(f"{Colors.OKBLUE}🔎 중복 파일 탐지 중...{Colors.ENDC}")

        for filename, file_path in self.all_attachments.items():
            file_hash = self.calculate_file_hash(file_path)
            if file_hash:
                self.file_hashes[file_hash].append(file_path)

        # 중복 파일만 필터링
        duplicates = {h: paths for h, paths in self.file_hashes.items() if len(paths) > 1}

        print(f"{Colors.OKGREEN}✅ {len(duplicates)}개 중복 그룹 발견{Colors.ENDC}")
        return duplicates

    def generate_report(self, duplicates: Dict[str, List[Path]]):
        """분석 리포트 생성"""
        # 미사용 파일
        unused_files = {
            filename: path
            for filename, path in self.all_attachments.items()
            if filename not in self.referenced_files
        }

        # 대용량 파일
        large_files = {
            filename: path
            for filename, path in self.all_attachments.items()
            if path.stat().st_size >= self.size_threshold
        }

        # 통계 계산
        total_attachments = len(self.all_attachments)
        total_referenced = len(self.referenced_files)
        total_unused = len(unused_files)
        total_duplicates = sum(len(paths) - 1 for paths in duplicates.values())  # 중복 수 (원본 제외)
        total_large = len(large_files)

        # 디스크 사용량
        unused_size = sum(path.stat().st_size for path in unused_files.values())
        duplicate_size = sum(
            sum(path.stat().st_size for path in paths[1:])  # 원본 제외한 중복 파일들
            for paths in duplicates.values()
        )
        large_size = sum(path.stat().st_size for path in large_files.values())

        print("\n" + "="*80)
        print(f"{Colors.BOLD}{Colors.HEADER}📊 Attachment Cleanup Report{Colors.ENDC}")
        print("="*80 + "\n")

        # Summary
        print(f"{Colors.BOLD}Summary:{Colors.ENDC}")
        print(f"  총 첨부파일: {total_attachments}개")
        print(f"  참조된 파일: {total_referenced}개")
        print(f"  🗑️  미사용 파일: {total_unused}개 ({self._format_size(unused_size)})")
        print(f"  📋 중복 파일: {total_duplicates}개 ({self._format_size(duplicate_size)})")
        print(f"  📦 대용량 파일: {total_large}개 ({self._format_size(large_size)})")
        print(f"  💾 절감 가능 공간: {self._format_size(unused_size + duplicate_size)}")

        # 미사용 파일
        if unused_files:
            print(f"\n{Colors.WARNING}{Colors.BOLD}🗑️  Unused Attachments:{Colors.ENDC}")
            sorted_unused = sorted(unused_files.items(), key=lambda x: x[1].stat().st_size, reverse=True)
            for i, (filename, path) in enumerate(sorted_unused[:20], 1):
                size = self._format_size(path.stat().st_size)
                rel_path = path.relative_to(self.vault_path)
                print(f"  {i:2d}. {Colors.WARNING}{filename}{Colors.ENDC} ({size})")
                print(f"      {Colors.OKCYAN}{rel_path}{Colors.ENDC}")
            if len(unused_files) > 20:
                print(f"  ... 외 {len(unused_files) - 20}개")

        # 중복 파일
        if duplicates:
            print(f"\n{Colors.FAIL}{Colors.BOLD}📋 Duplicate Files:{Colors.ENDC}")
            for i, (file_hash, paths) in enumerate(list(duplicates.items())[:10], 1):
                print(f"\n  {Colors.FAIL}그룹 {i} (해시: {file_hash[:8]}...):{Colors.ENDC}")
                for path in paths:
                    size = self._format_size(path.stat().st_size)
                    rel_path = path.relative_to(self.vault_path)
                    is_referenced = "✅" if path.name in self.referenced_files else "❌"
                    print(f"    {is_referenced} {path.name} ({size})")
                    print(f"       {Colors.OKCYAN}{rel_path}{Colors.ENDC}")
            if len(duplicates) > 10:
                print(f"\n  ... 외 {len(duplicates) - 10}개 그룹")

        # 대용량 파일
        if large_files:
            print(f"\n{Colors.OKBLUE}{Colors.BOLD}📦 Large Files (>{self.size_threshold // (1024*1024)}MB):{Colors.ENDC}")
            sorted_large = sorted(large_files.items(), key=lambda x: x[1].stat().st_size, reverse=True)
            for i, (filename, path) in enumerate(sorted_large[:10], 1):
                size = self._format_size(path.stat().st_size)
                rel_path = path.relative_to(self.vault_path)
                is_used = "✅" if filename in self.referenced_files else "❌"
                print(f"  {i:2d}. {is_used} {Colors.OKBLUE}{filename}{Colors.ENDC} ({size})")
                print(f"      {Colors.OKCYAN}{rel_path}{Colors.ENDC}")
            if len(large_files) > 10:
                print(f"  ... 외 {len(large_files) - 10}개")

        print("\n" + "="*80)

        # 건강 상태
        unused_pct = (total_unused / total_attachments * 100) if total_attachments > 0 else 0

        if unused_pct < 10:
            print(f"{Colors.OKGREEN}{Colors.BOLD}✅ 첨부파일 상태: 매우 양호 (미사용 {unused_pct:.1f}%){Colors.ENDC}")
        elif unused_pct < 20:
            print(f"{Colors.OKGREEN}{Colors.BOLD}✅ 첨부파일 상태: 양호 (미사용 {unused_pct:.1f}%){Colors.ENDC}")
        elif unused_pct < 30:
            print(f"{Colors.WARNING}{Colors.BOLD}⚠️  첨부파일 상태: 보통 (미사용 {unused_pct:.1f}%){Colors.ENDC}")
        else:
            print(f"{Colors.FAIL}{Colors.BOLD}❌ 첨부파일 상태: 정리 필요 (미사용 {unused_pct:.1f}%){Colors.ENDC}")

        print("="*80 + "\n")

        return unused_files, duplicates, large_files

    def _format_size(self, size_bytes: int) -> str:
        """파일 크기를 읽기 쉬운 형식으로 변환"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f}{unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f}TB"

def main():
    parser = argparse.ArgumentParser(
        description='Obsidian 첨부파일을 정리합니다.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  기본 분석:
    python obsidian-attachment-cleaner.py /path/to/vault

  대용량 파일 기준 변경 (20MB):
    python obsidian-attachment-cleaner.py /path/to/vault --size-threshold 20

  미사용 파일 삭제 (주의!):
    python obsidian-attachment-cleaner.py /path/to/vault --delete-unused
        """
    )

    parser.add_argument('vault_path', help='Obsidian 볼트 경로')
    parser.add_argument('--size-threshold', type=int, default=10, help='대용량 파일 기준 (MB, 기본값: 10)')
    parser.add_argument('--delete-unused', action='store_true', help='미사용 파일 삭제 (주의!)')

    args = parser.parse_args()

    # 볼트 경로 검증
    vault_path = Path(args.vault_path)
    if not vault_path.exists():
        print(f"{Colors.FAIL}❌ 볼트 경로를 찾을 수 없습니다: {vault_path}{Colors.ENDC}")
        sys.exit(1)

    # 분석기 실행
    cleaner = AttachmentCleaner(str(vault_path), args.size_threshold)

    try:
        cleaner.scan_attachments()
        cleaner.scan_references()
        duplicates = cleaner.find_duplicates()
        unused_files, duplicates, large_files = cleaner.generate_report(duplicates)

        # 미사용 파일 삭제 (옵션)
        if args.delete_unused and unused_files:
            print(f"\n{Colors.WARNING}⚠️  미사용 파일 {len(unused_files)}개를 삭제하시겠습니까?{Colors.ENDC}")
            print(f"{Colors.FAIL}주의: 이 작업은 되돌릴 수 없습니다!{Colors.ENDC}")
            response = input("삭제하려면 'yes'를 입력하세요: ")

            if response.lower() == 'yes':
                deleted_count = 0
                for filename, path in unused_files.items():
                    try:
                        path.unlink()
                        deleted_count += 1
                        print(f"{Colors.OKGREEN}✅ 삭제: {path.name}{Colors.ENDC}")
                    except Exception as e:
                        print(f"{Colors.FAIL}❌ 삭제 실패: {path.name} - {e}{Colors.ENDC}")

                print(f"\n{Colors.OKGREEN}{Colors.BOLD}✅ {deleted_count}개 파일 삭제 완료{Colors.ENDC}")
            else:
                print(f"{Colors.WARNING}취소되었습니다.{Colors.ENDC}")

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
