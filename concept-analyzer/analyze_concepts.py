#!/usr/bin/env python3
"""
Concept Network Analyzer
Obsidian Concept 노트의 네트워크 구조를 분석하고 통계를 생성합니다.
"""

import os
import re
import json
import yaml
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime
import argparse


class ConceptAnalyzer:
    def __init__(self, concepts_path):
        self.concepts_path = Path(concepts_path).absolute()
        self.vault_root = self._find_vault_root()
        self.concepts = {}
        self.all_links = defaultdict(set)  # 파일별 outgoing links
        self.backlinks = defaultdict(set)  # 파일별 incoming links

    def _find_vault_root(self):
        """볼트 루트 디렉토리 찾기"""
        current = self.concepts_path
        while current != current.parent:
            if (current / '.obsidian').exists():
                return current
            current = current.parent
        return self.concepts_path

    def extract_frontmatter(self, content):
        """YAML frontmatter 추출"""
        if not content.startswith('---'):
            return None, content

        parts = content.split('---', 2)
        if len(parts) < 3:
            return None, content

        try:
            frontmatter = yaml.safe_load(parts[1])
            body = parts[2]
            return frontmatter, body
        except yaml.YAMLError:
            return None, content

    def extract_wikilinks(self, content):
        """위키링크 추출 [[링크]] 또는 [[링크|표시텍스트]]"""
        # [[링크#섹션|표시]] 형식도 처리
        pattern = r'\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]'
        matches = re.findall(pattern, content)
        return set(matches)

    def has_mermaid(self, content):
        """Mermaid 다이어그램 유무 확인"""
        return bool(re.search(r'```mermaid', content, re.IGNORECASE))

    def count_words(self, content):
        """본문 단어 수 계산 (한글/영문)"""
        # 코드 블록 제거
        content = re.sub(r'```[\s\S]*?```', '', content)
        # 한글 단어 수 + 영문 단어 수
        korean_words = len(re.findall(r'[가-힣]+', content))
        english_words = len(re.findall(r'\b[a-zA-Z]+\b', content))
        return korean_words + english_words

    def count_sections(self, content):
        """섹션 수 계산 (## 으로 시작하는 헤더)"""
        return len(re.findall(r'^##\s+', content, re.MULTILINE))

    def analyze_file(self, filepath):
        """단일 파일 분석"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            print(f"Error reading {filepath}: {e}")
            return None

        frontmatter, body = self.extract_frontmatter(content)

        if not frontmatter or frontmatter.get('type') != 'concept':
            return None

        filename = filepath.stem

        # 위키링크 추출
        outlinks = self.extract_wikilinks(body)
        self.all_links[filename] = outlinks

        # 다른 파일에서 이 파일을 참조하는 링크 계산을 위해 저장
        for link in outlinks:
            self.backlinks[link].add(filename)

        # 분석 결과
        analysis = {
            'filename': filename,
            'filepath': str(filepath.relative_to(self.vault_root)),
            'type': frontmatter.get('type'),
            'tags': frontmatter.get('tags', []),
            'aliases': frontmatter.get('aliases', []),
            'created': str(frontmatter.get('created', '')),
            'updated': str(frontmatter.get('updated', '')),
            'status': frontmatter.get('status', ''),
            'outlinks': list(outlinks),
            'outlinks_count': len(outlinks),
            'has_mermaid': self.has_mermaid(body),
            'word_count': self.count_words(body),
            'section_count': self.count_sections(body),
        }

        return analysis

    def analyze_all(self):
        """전체 Concepts 폴더 분석"""
        md_files = list(self.concepts_path.glob('*.md'))

        print(f"Found {len(md_files)} markdown files in {self.concepts_path}")

        # 1차: 파일별 분석
        for filepath in md_files:
            result = self.analyze_file(filepath)
            if result:
                self.concepts[result['filename']] = result

        # 2차: inlinks 계산
        for filename, concept in self.concepts.items():
            concept['inlinks'] = list(self.backlinks.get(filename, set()))
            concept['inlinks_count'] = len(concept['inlinks'])
            concept['total_links'] = concept['inlinks_count'] + concept['outlinks_count']

        print(f"Analyzed {len(self.concepts)} concept notes")

    def generate_statistics(self):
        """통계 생성"""
        if not self.concepts:
            return {}

        total_concepts = len(self.concepts)

        # 태그별 분포
        tag_distribution = Counter()
        for concept in self.concepts.values():
            for tag in concept['tags']:
                tag_distribution[tag] += 1

        # 연결성 통계
        total_inlinks = sum(c['inlinks_count'] for c in self.concepts.values())
        total_outlinks = sum(c['outlinks_count'] for c in self.concepts.values())
        avg_inlinks = total_inlinks / total_concepts if total_concepts > 0 else 0
        avg_outlinks = total_outlinks / total_concepts if total_concepts > 0 else 0

        # Mermaid 사용률
        mermaid_count = sum(1 for c in self.concepts.values() if c['has_mermaid'])
        mermaid_rate = (mermaid_count / total_concepts * 100) if total_concepts > 0 else 0

        # 평균 단어 수 및 섹션 수
        avg_words = sum(c['word_count'] for c in self.concepts.values()) / total_concepts if total_concepts > 0 else 0
        avg_sections = sum(c['section_count'] for c in self.concepts.values()) / total_concepts if total_concepts > 0 else 0

        # 고립 개념 (inlinks < 2)
        isolated_concepts = [
            {
                'filename': c['filename'],
                'inlinks_count': c['inlinks_count'],
                'outlinks_count': c['outlinks_count']
            }
            for c in self.concepts.values()
            if c['inlinks_count'] < 2
        ]
        isolated_concepts.sort(key=lambda x: (x['inlinks_count'], x['outlinks_count']))

        # 약한 연결 개념 (outlinks < 3)
        weak_concepts = [
            {
                'filename': c['filename'],
                'inlinks_count': c['inlinks_count'],
                'outlinks_count': c['outlinks_count']
            }
            for c in self.concepts.values()
            if c['outlinks_count'] < 3
        ]
        weak_concepts.sort(key=lambda x: (x['outlinks_count'], -x['inlinks_count']))

        # 허브 개념 (total_links 상위)
        hub_concepts = sorted(
            [
                {
                    'filename': c['filename'],
                    'inlinks_count': c['inlinks_count'],
                    'outlinks_count': c['outlinks_count'],
                    'total_links': c['total_links'],
                    'tags': c['tags']
                }
                for c in self.concepts.values()
            ],
            key=lambda x: x['total_links'],
            reverse=True
        )[:15]

        statistics = {
            'total_concepts': total_concepts,
            'total_inlinks': total_inlinks,
            'total_outlinks': total_outlinks,
            'avg_inlinks': round(avg_inlinks, 2),
            'avg_outlinks': round(avg_outlinks, 2),
            'avg_total_links': round(avg_inlinks + avg_outlinks, 2),
            'mermaid_count': mermaid_count,
            'mermaid_rate': round(mermaid_rate, 1),
            'avg_words': round(avg_words, 0),
            'avg_sections': round(avg_sections, 1),
            'tag_distribution': dict(tag_distribution.most_common(20)),
            'isolated_concepts': isolated_concepts[:15],
            'weak_concepts': weak_concepts[:15],
            'hub_concepts': hub_concepts,
        }

        return statistics

    def generate_report(self):
        """전체 리포트 생성"""
        statistics = self.generate_statistics()

        report = {
            'analysis_date': datetime.now().isoformat(),
            'concepts_path': str(self.concepts_path.relative_to(self.vault_root)),
            'vault_root': str(self.vault_root),
            'statistics': statistics,
            'concepts': list(self.concepts.values()),
        }

        return report


def main():
    parser = argparse.ArgumentParser(description='Analyze Obsidian Concept notes network')
    parser.add_argument('--path', required=True, help='Path to Concepts folder')
    parser.add_argument('--output', help='Output JSON file path (optional)')
    parser.add_argument('--format', choices=['json', 'summary'], default='json',
                        help='Output format (default: json)')

    args = parser.parse_args()

    analyzer = ConceptAnalyzer(args.path)
    analyzer.analyze_all()
    report = analyzer.generate_report()

    if args.format == 'json':
        output = json.dumps(report, ensure_ascii=False, indent=2)

        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(output)
            print(f"Report saved to {args.output}")
        else:
            print(output)

    elif args.format == 'summary':
        stats = report['statistics']
        print("\n" + "="*60)
        print(f"Concept Network Analysis - {report['concepts_path']}")
        print("="*60)
        print(f"\n📊 총 개념 노트: {stats['total_concepts']}개")
        print(f"📈 평균 연결 수: {stats['avg_total_links']}개")
        print(f"   - Inlinks: {stats['avg_inlinks']}개")
        print(f"   - Outlinks: {stats['avg_outlinks']}개")
        print(f"🎨 Mermaid 사용률: {stats['mermaid_rate']}% ({stats['mermaid_count']}개)")
        print(f"📝 평균 단어 수: {stats['avg_words']}개")
        print(f"📑 평균 섹션 수: {stats['avg_sections']}개")

        print(f"\n🏷️  주요 태그 (Top 10):")
        for tag, count in list(stats['tag_distribution'].items())[:10]:
            print(f"   - {tag}: {count}개")

        print(f"\n⚠️  고립 개념 (Inlinks < 2, Top 10):")
        for concept in stats['isolated_concepts'][:10]:
            print(f"   - {concept['filename']}: In={concept['inlinks_count']}, Out={concept['outlinks_count']}")

        print(f"\n🌟 허브 개념 (Top 10):")
        for concept in stats['hub_concepts'][:10]:
            print(f"   - {concept['filename']}: In={concept['inlinks_count']}, Out={concept['outlinks_count']}, Total={concept['total_links']}")
        print()


if __name__ == '__main__':
    main()
