#!/usr/bin/env python3
"""
Obsidian Tag Normalizer
태그 수집, 유사 태그 탐지, 태그 계층 구조 분석 및 병합 권장

사용법:
    python obsidian-tag-normalizer.py /path/to/vault
    python obsidian-tag-normalizer.py /path/to/vault --min-similarity 80
    python obsidian-tag-normalizer.py /path/to/vault --export-report tags-report.json
"""

import os
import re
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple
from collections import defaultdict, Counter
from difflib import SequenceMatcher
import yaml

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

class TagNormalizer:
    """Obsidian 태그 정규화 클래스"""

    def __init__(self, vault_path: str, min_similarity: int = 70):
        self.vault_path = Path(vault_path)
        self.min_similarity = min_similarity / 100.0  # 퍼센트를 0~1 범위로 변환

        # 제외 폴더
        self.excluded_dirs = {'.git', '.obsidian', '.trash', '.claude', '04_Archive'}

        # 결과 저장
        self.tag_usage: Dict[str, List[Path]] = defaultdict(list)  # tag -> [files using it]
        self.tag_frequency: Counter = Counter()  # tag -> count
        self.tag_hierarchy: Dict[str, Set[str]] = defaultdict(set)  # parent -> {children}

        # 태그 패턴
        self.frontmatter_pattern = re.compile(r'^---\s*\n(.*?)\n---\s*\n', re.DOTALL)
        self.inline_tag_pattern = re.compile(r'#([a-zA-Z0-9가-힣_-]+(?:/[a-zA-Z0-9가-힣_-]+)*)')

    def scan_tags(self):
        """볼트 전체에서 태그 수집"""
        print(f"{Colors.OKBLUE}📂 볼트 스캔 중...{Colors.ENDC}")

        file_count = 0
        for md_file in self.vault_path.rglob("*.md"):
            # 제외 폴더 체크
            if any(excluded in str(md_file) for excluded in self.excluded_dirs):
                continue

            file_count += 1

            try:
                with open(md_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Frontmatter 태그
                frontmatter_tags = self._extract_frontmatter_tags(content)
                for tag in frontmatter_tags:
                    self.tag_usage[tag].append(md_file)
                    self.tag_frequency[tag] += 1
                    self._parse_hierarchy(tag)

                # 인라인 태그
                inline_tags = self._extract_inline_tags(content)
                for tag in inline_tags:
                    self.tag_usage[tag].append(md_file)
                    self.tag_frequency[tag] += 1
                    self._parse_hierarchy(tag)

            except Exception as e:
                print(f"{Colors.WARNING}⚠️  파일 읽기 오류: {md_file} - {e}{Colors.ENDC}")

        print(f"{Colors.OKGREEN}✅ {file_count}개 파일 스캔 완료{Colors.ENDC}")
        print(f"{Colors.OKGREEN}✅ {len(self.tag_frequency)}개 고유 태그 발견{Colors.ENDC}")

    def _extract_frontmatter_tags(self, content: str) -> Set[str]:
        """Frontmatter에서 태그 추출"""
        tags = set()
        match = self.frontmatter_pattern.match(content)

        if match:
            try:
                metadata = yaml.safe_load(match.group(1))
                if isinstance(metadata, dict) and 'tags' in metadata:
                    tag_list = metadata['tags']
                    if isinstance(tag_list, list):
                        for tag in tag_list:
                            if isinstance(tag, str):
                                # '#' 제거
                                tag_clean = tag.lstrip('#').strip()
                                if tag_clean:
                                    tags.add(tag_clean)
            except:
                pass

        return tags

    def _extract_inline_tags(self, content: str) -> Set[str]:
        """인라인 태그 추출 (#tag 형식)"""
        tags = set()

        # Frontmatter 제거
        content_no_fm = self.frontmatter_pattern.sub('', content)

        # 코드 블록 제거
        code_block_pattern = re.compile(r'```[\s\S]*?```|`[^`]+`')
        content_no_code = code_block_pattern.sub('', content_no_fm)

        for match in self.inline_tag_pattern.finditer(content_no_code):
            tag = match.group(1)
            tags.add(tag)

        return tags

    def _parse_hierarchy(self, tag: str):
        """태그 계층 구조 파싱 (nested/tags 형식)"""
        if '/' in tag:
            parts = tag.split('/')
            for i in range(len(parts) - 1):
                parent = '/'.join(parts[:i+1])
                child = '/'.join(parts[:i+2])
                self.tag_hierarchy[parent].add(child)

    def find_similar_tags(self) -> List[Tuple[str, str, float]]:
        """유사한 태그 탐지"""
        print(f"{Colors.OKBLUE}🔍 유사 태그 탐지 중...{Colors.ENDC}")

        similar_pairs = []
        tags = list(self.tag_frequency.keys())

        for i, tag1 in enumerate(tags):
            for tag2 in tags[i+1:]:
                # 계층 태그는 건너뛰기 (부모-자식 관계)
                if tag1.startswith(tag2 + '/') or tag2.startswith(tag1 + '/'):
                    continue

                similarity = self._calculate_similarity(tag1, tag2)
                if similarity >= self.min_similarity:
                    similar_pairs.append((tag1, tag2, similarity))

        # 유사도 순 정렬
        similar_pairs.sort(key=lambda x: x[2], reverse=True)

        print(f"{Colors.OKGREEN}✅ {len(similar_pairs)}개 유사 태그 쌍 발견{Colors.ENDC}")
        return similar_pairs

    def _calculate_similarity(self, tag1: str, tag2: str) -> float:
        """태그 유사도 계산"""
        # 대소문자 정규화
        t1 = tag1.lower()
        t2 = tag2.lower()

        # 기본 유사도 (Sequence Matcher)
        base_similarity = SequenceMatcher(None, t1, t2).ratio()

        # 보너스: 단수/복수 형태
        if (t1.endswith('s') and t1[:-1] == t2) or (t2.endswith('s') and t2[:-1] == t1):
            base_similarity += 0.1

        # 보너스: 하이픈/언더스코어 변형
        if t1.replace('-', '_') == t2.replace('-', '_'):
            base_similarity += 0.1

        return min(base_similarity, 1.0)

    def generate_report(self, similar_pairs: List[Tuple[str, str, float]]):
        """분석 리포트 생성"""
        total_tags = len(self.tag_frequency)
        total_usage = sum(self.tag_frequency.values())

        # Top 태그
        top_tags = self.tag_frequency.most_common(20)

        # 사용 빈도가 낮은 태그 (1-2회)
        rare_tags = {tag: count for tag, count in self.tag_frequency.items() if count <= 2}

        # 계층 태그 (nested tags)
        nested_tags = {tag for tag in self.tag_frequency if '/' in tag}

        print("\n" + "="*80)
        print(f"{Colors.BOLD}{Colors.HEADER}📊 Tag Normalization Report{Colors.ENDC}")
        print("="*80 + "\n")

        # Summary
        print(f"{Colors.BOLD}Summary:{Colors.ENDC}")
        print(f"  총 고유 태그: {total_tags}개")
        print(f"  총 태그 사용 횟수: {total_usage}회")
        print(f"  평균 태그/파일: {total_usage / len(list(self.vault_path.rglob('*.md'))):.1f}개")
        print(f"  🔀 유사 태그 쌍: {len(similar_pairs)}개")
        print(f"  📁 계층 태그: {len(nested_tags)}개")
        print(f"  🔸 드문 태그 (1-2회): {len(rare_tags)}개")

        # Top 태그
        print(f"\n{Colors.BOLD}{Colors.OKGREEN}🏆 Top 20 Most Used Tags:{Colors.ENDC}")
        for i, (tag, count) in enumerate(top_tags, 1):
            print(f"  {i:2d}. #{Colors.OKGREEN}{tag}{Colors.ENDC} ({count}회)")

        # 유사 태그
        if similar_pairs:
            print(f"\n{Colors.WARNING}{Colors.BOLD}🔀 Similar Tags (병합 후보):{Colors.ENDC}")
            for i, (tag1, tag2, similarity) in enumerate(similar_pairs[:20], 1):
                count1 = self.tag_frequency[tag1]
                count2 = self.tag_frequency[tag2]
                print(f"\n  {i:2d}. {Colors.WARNING}유사도: {similarity*100:.1f}%{Colors.ENDC}")
                print(f"      #{tag1} ({count1}회) ↔ #{tag2} ({count2}회)")

                # 병합 권장
                if count1 > count2:
                    print(f"      {Colors.OKCYAN}→ 권장: #{tag2} → #{tag1}{Colors.ENDC}")
                else:
                    print(f"      {Colors.OKCYAN}→ 권장: #{tag1} → #{tag2}{Colors.ENDC}")

            if len(similar_pairs) > 20:
                print(f"\n  ... 외 {len(similar_pairs) - 20}개 쌍")

        # 드문 태그
        if rare_tags:
            print(f"\n{Colors.OKBLUE}{Colors.BOLD}🔸 Rare Tags (1-2회 사용):{Colors.ENDC}")
            sorted_rare = sorted(rare_tags.items(), key=lambda x: x[1])
            for i, (tag, count) in enumerate(sorted_rare[:20], 1):
                print(f"  {i:2d}. #{Colors.OKBLUE}{tag}{Colors.ENDC} ({count}회)")
            if len(rare_tags) > 20:
                print(f"  ... 외 {len(rare_tags) - 20}개")

        # 계층 구조
        if self.tag_hierarchy:
            print(f"\n{Colors.BOLD}📁 Tag Hierarchy:{Colors.ENDC}")
            root_tags = {tag for tag in self.tag_hierarchy if '/' not in tag or tag.count('/') == 0}

            # 최상위 태그만 표시
            top_level = {tag.split('/')[0] for tag in nested_tags}
            for root in sorted(top_level)[:10]:
                children = [tag for tag in nested_tags if tag.startswith(root + '/')]
                print(f"\n  📂 #{root} ({self.tag_frequency.get(root, 0)}회)")
                for child in sorted(children)[:5]:
                    indent = '  ' * child.count('/')
                    print(f"    {indent}└─ #{child} ({self.tag_frequency[child]}회)")
                if len(children) > 5:
                    print(f"      ... 외 {len(children) - 5}개")

        print("\n" + "="*80)

        # 건강 상태
        similarity_ratio = len(similar_pairs) / total_tags * 100 if total_tags > 0 else 0

        if similarity_ratio < 5:
            print(f"{Colors.OKGREEN}{Colors.BOLD}✅ 태그 상태: 매우 양호 (유사 태그 {similarity_ratio:.1f}%){Colors.ENDC}")
        elif similarity_ratio < 10:
            print(f"{Colors.OKGREEN}{Colors.BOLD}✅ 태그 상태: 양호 (유사 태그 {similarity_ratio:.1f}%){Colors.ENDC}")
        elif similarity_ratio < 20:
            print(f"{Colors.WARNING}{Colors.BOLD}⚠️  태그 상태: 보통 (유사 태그 {similarity_ratio:.1f}%){Colors.ENDC}")
        else:
            print(f"{Colors.FAIL}{Colors.BOLD}❌ 태그 상태: 정리 필요 (유사 태그 {similarity_ratio:.1f}%){Colors.ENDC}")

        print("="*80 + "\n")

        return rare_tags

    def export_report(self, output_path: str, similar_pairs: List[Tuple[str, str, float]]):
        """리포트를 JSON으로 내보내기"""
        print(f"{Colors.OKBLUE}💾 리포트 내보내기 중...{Colors.ENDC}")

        report_data = {
            "summary": {
                "total_tags": len(self.tag_frequency),
                "total_usage": sum(self.tag_frequency.values()),
                "similar_pairs": len(similar_pairs),
                "nested_tags": len([t for t in self.tag_frequency if '/' in t]),
                "rare_tags": len([t for t, c in self.tag_frequency.items() if c <= 2])
            },
            "tag_frequency": dict(self.tag_frequency.most_common()),
            "similar_pairs": [
                {
                    "tag1": tag1,
                    "tag2": tag2,
                    "similarity": round(similarity * 100, 1),
                    "count1": self.tag_frequency[tag1],
                    "count2": self.tag_frequency[tag2],
                    "recommended_merge": tag2 + " → " + tag1 if self.tag_frequency[tag1] > self.tag_frequency[tag2] else tag1 + " → " + tag2
                }
                for tag1, tag2, similarity in similar_pairs
            ],
            "rare_tags": {tag: count for tag, count in self.tag_frequency.items() if count <= 2},
            "tag_hierarchy": {parent: list(children) for parent, children in self.tag_hierarchy.items()}
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)

        print(f"{Colors.OKGREEN}✅ 리포트 저장 완료: {output_path}{Colors.ENDC}")

def main():
    parser = argparse.ArgumentParser(
        description='Obsidian 태그를 정규화합니다.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  기본 분석:
    python obsidian-tag-normalizer.py /path/to/vault

  유사도 임계값 변경 (80%):
    python obsidian-tag-normalizer.py /path/to/vault --min-similarity 80

  리포트 내보내기:
    python obsidian-tag-normalizer.py /path/to/vault --export-report tags-report.json
        """
    )

    parser.add_argument('vault_path', help='Obsidian 볼트 경로')
    parser.add_argument('--min-similarity', type=int, default=70, help='유사 태그로 간주할 최소 유사도 (%%, 기본값: 70)')
    parser.add_argument('--export-report', help='리포트를 JSON으로 내보내기', metavar='FILE')

    args = parser.parse_args()

    # 볼트 경로 검증
    vault_path = Path(args.vault_path)
    if not vault_path.exists():
        print(f"{Colors.FAIL}❌ 볼트 경로를 찾을 수 없습니다: {vault_path}{Colors.ENDC}")
        sys.exit(1)

    # 분석기 실행
    normalizer = TagNormalizer(str(vault_path), args.min_similarity)

    try:
        normalizer.scan_tags()
        similar_pairs = normalizer.find_similar_tags()
        normalizer.generate_report(similar_pairs)

        # 리포트 내보내기
        if args.export_report:
            normalizer.export_report(args.export_report, similar_pairs)

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
