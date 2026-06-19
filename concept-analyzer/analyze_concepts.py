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
        self.vault_file_stems = set()  # 볼트 전체 .md 파일명 인덱스

    def _find_vault_root(self):
        """볼트 루트 디렉토리 찾기"""
        current = self.concepts_path
        while current != current.parent:
            if (current / '.obsidian').exists():
                return current
            current = current.parent
        return self.concepts_path

    def _build_vault_file_index(self):
        """볼트 전체 .md 파일명(stem) 인덱스 생성"""
        self.vault_file_stems = set()
        for md_file in self.vault_root.rglob('*.md'):
            self.vault_file_stems.add(md_file.stem)
        print(f"Built vault file index: {len(self.vault_file_stems)} files")

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

        # 태그 정규화: dict 태그({도메인: CDN}) → 값 추출, 형식 오류 기록
        raw_tags = frontmatter.get('tags', []) or []
        tags = []
        malformed_tags = []
        for tag in raw_tags:
            if isinstance(tag, str):
                tags.append(tag)
            elif isinstance(tag, dict):
                for v in tag.values():
                    if isinstance(v, str):
                        tags.append(v)
                malformed_tags.append(str(tag))
            else:
                tags.append(str(tag))

        # 분석 결과
        analysis = {
            'filename': filename,
            'filepath': str(filepath.relative_to(self.vault_root)),
            'type': frontmatter.get('type'),
            'tags': tags,
            'malformed_tags': malformed_tags,
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
        # 0차: 볼트 전체 파일명 인덱스 생성 (dangling link 탐지용)
        self._build_vault_file_index()

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

    def generate_statistics(self, additional_known_stems=None):
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

        # 태그 형식 오류 파일 (dict 태그 포함)
        malformed_tag_files = [
            {'filename': c['filename'], 'malformed_tags': c['malformed_tags']}
            for c in self.concepts.values()
            if c.get('malformed_tags')
        ]

        # Dangling links: 링크 대상이 실제 파일로 존재하지 않는 경우
        # 1차: Concepts 폴더 내 파일 + crosslink 대상 파일 + 볼트 전체 파일
        known_stems = set(self.concepts.keys())
        if additional_known_stems:
            known_stems.update(additional_known_stems)
        # 볼트 전체 파일명 추가 (다른 폴더의 파일도 포함)
        known_stems.update(self.vault_file_stems)

        # 정규화 맵: normalize(stem) → 원본 stem (naming mismatch 탐지용)
        def normalize(s):
            return re.sub(r'[\s\-_]', '', s).lower()

        normalized_to_stem = {normalize(s): s for s in known_stems}

        dangling = defaultdict(list)
        malformed_links = defaultdict(list)
        naming_mismatches = defaultdict(list)  # {link: [(source, correct_stem), ...]}
        for filename, concept in self.concepts.items():
            for link in concept['outlinks']:
                # 경로 포함(/) 또는 이모지·특수문자 시작 → Concept 대상 아님
                if '/' in link or not re.match(r'^[A-Za-z0-9가-힣]', link):
                    continue
                # .md 접미사 → malformed 위키링크
                if link.endswith('.md') or link.endswith('.md\\'):
                    malformed_links[link].append(filename)
                    continue
                # 공백 포함 → 문서/장애보고서 등 일반 노트 링크 (단, 한글 포함 시 naming mismatch 후보)
                if link in known_stems:
                    continue  # 정상 링크
                # Naming mismatch 검사: 정규화 후 일치하는 파일이 있는지 확인
                norm_link = normalize(link)
                if norm_link in normalized_to_stem:
                    correct = normalized_to_stem[norm_link]
                    naming_mismatches[link].append({'source': filename, 'correct': correct})
                elif ' ' not in link:
                    # 공백 없는 링크 중 정규화도 안 맞으면 true dangling
                    dangling[link].append(filename)

        dangling_links = [
            {'target': target, 'referenced_by': sorted(sources)}
            for target, sources in sorted(dangling.items(), key=lambda x: -len(x[1]))
        ]
        malformed_link_list = [
            {'target': target, 'referenced_by': sorted(sources)}
            for target, sources in sorted(malformed_links.items(), key=lambda x: -len(x[1]))
        ]
        naming_mismatch_list = [
            {
                'link': link,
                'correct': entries[0]['correct'],
                'referenced_by': sorted(set(e['source'] for e in entries))
            }
            for link, entries in sorted(naming_mismatches.items(), key=lambda x: -len(x[1]))
        ]

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
            'malformed_tag_files': malformed_tag_files,
            'dangling_links': dangling_links,
            'malformed_wikilinks': malformed_link_list,
            'naming_mismatches': naming_mismatch_list,
        }

        return statistics

    def generate_report(self, additional_known_stems=None):
        """전체 리포트 생성"""
        statistics = self.generate_statistics(additional_known_stems)

        report = {
            'analysis_date': datetime.now().isoformat(),
            'concepts_path': str(self.concepts_path.relative_to(self.vault_root)),
            'vault_root': str(self.vault_root),
            'statistics': statistics,
            'concepts': list(self.concepts.values()),
        }

        return report


def analyze_crosslinks(analyzer_a, analyzer_b):
    """두 카테고리 간 크로스링크 분석. (A→B, B→A)"""
    stems_a = set(analyzer_a.concepts.keys())
    stems_b = set(analyzer_b.concepts.keys())

    a_to_b = defaultdict(int)  # B 개념별 A에서 받은 링크 수
    b_to_a = defaultdict(int)  # A 개념별 B에서 받은 링크 수

    for stem, links in analyzer_a.all_links.items():
        for link in links:
            normalized = link.replace(' ', '-').lower()
            for b_stem in stems_b:
                if normalized == b_stem.lower():
                    a_to_b[b_stem] += 1

    for stem, links in analyzer_b.all_links.items():
        for link in links:
            normalized = link.replace(' ', '-').lower()
            for a_stem in stems_a:
                if normalized == a_stem.lower():
                    b_to_a[a_stem] += 1

    return {
        'a_to_b_total': sum(a_to_b.values()),
        'b_to_a_total': sum(b_to_a.values()),
        'a_to_b_top': sorted(a_to_b.items(), key=lambda x: -x[1])[:10],
        'b_to_a_top': sorted(b_to_a.items(), key=lambda x: -x[1])[:10],
        'path_a': str(analyzer_a.concepts_path.relative_to(analyzer_a.vault_root)),
        'path_b': str(analyzer_b.concepts_path.relative_to(analyzer_b.vault_root)),
    }


def print_summary(report, crosslink=None):
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

    if stats.get('malformed_tag_files'):
        print(f"\n🔧 태그 형식 오류 ({len(stats['malformed_tag_files'])}개 파일):")
        for item in stats['malformed_tag_files']:
            print(f"   - {item['filename']}: {', '.join(item['malformed_tags'])}")

    if stats.get('dangling_links'):
        print(f"\n🔴 Dangling Links ({len(stats['dangling_links'])}개 — 참조되지만 파일 없음):")
        for item in stats['dangling_links']:
            refs = ', '.join(item['referenced_by'][:3])
            more = f" 외 {len(item['referenced_by'])-3}개" if len(item['referenced_by']) > 3 else ""
            print(f"   - {item['target']} (참조: {refs}{more})")
    else:
        print(f"\n✅ Dangling Links: 없음")

    if stats.get('malformed_wikilinks'):
        print(f"\n⚠️  Malformed Wikilinks ({len(stats['malformed_wikilinks'])}개 — .md 접미사 포함):")
        for item in stats['malformed_wikilinks']:
            refs = ', '.join(item['referenced_by'][:3])
            print(f"   - {item['target']} (참조: {refs})")

    if stats.get('naming_mismatches'):
        print(f"\n🔀 Naming Mismatches ({len(stats['naming_mismatches'])}개 — 파일은 있으나 링크명 불일치):")
        for item in stats['naming_mismatches']:
            refs = ', '.join(item['referenced_by'][:3])
            more = f" 외 {len(item['referenced_by'])-3}개" if len(item['referenced_by']) > 3 else ""
            print(f"   - [[{item['link']}]] → [[{item['correct']}]] (참조: {refs}{more})")

    if crosslink:
        print(f"\n🔗 카테고리 간 크로스링크")
        print(f"   {crosslink['path_a']} → {crosslink['path_b']}: {crosslink['a_to_b_total']}개")
        if crosslink['a_to_b_top']:
            for stem, count in crosslink['a_to_b_top'][:5]:
                print(f"      └ {stem}: {count}회")
        print(f"   {crosslink['path_b']} → {crosslink['path_a']}: {crosslink['b_to_a_total']}개")
        if crosslink['b_to_a_top']:
            for stem, count in crosslink['b_to_a_top'][:5]:
                print(f"      └ {stem}: {count}회")
    print()


class ConceptMiner:
    """02_Areas/ 문서에서 신규 Concept 후보를 추출하는 마이너"""

    TECH_DIRS = {
        '업무_CDN', '업무_장애보고서', '업무_HermesStorage',
        '업무_ObjectStorage', '업무_CDN_ONS', '업무_CDN_SOP', '업무_시험'
    }
    PERSONAL_DIRS = {
        '팀관리_면담', '개인_성장', '개인_금융', '개인_홈', '개인_여행'
    }
    SKIP_TYPES = {'index', 'people', 'clipping'}

    # 개념 가치가 없는 용어 blocklist
    KEYWORD_BLOCKLIST = frozenset({
        # HTTP 메서드
        'GET', 'POST', 'PUT', 'DELETE', 'HEAD', 'PATCH', 'OPTIONS', 'TRACE', 'CONNECT',
        # SQL 키워드
        'SELECT', 'FROM', 'WHERE', 'TABLE', 'WITHOUT', 'SORT', 'TEXT', 'LIKE', 'DESC',
        'INSERT', 'UPDATE', 'DROP', 'CREATE', 'JOIN', 'INTO', 'LIMIT', 'UNION',
        'INDEX', 'GROUP', 'ORDER', 'HAVING', 'OFFSET',
        # Boolean / 상수
        'TRUE', 'FALSE', 'NULL', 'NONE', 'YES', 'NO',
        # 일반 프로그래밍 용어
        'CODE', 'DATA', 'TIME', 'NAME', 'TYPE', 'MODE', 'KEY', 'HOST', 'PATH',
        'USER', 'HOME', 'ROOT', 'FILE', 'LIST', 'INFO', 'BASE', 'CORE', 'MAIN',
        'LINK', 'PAGE', 'LINE', 'ITEM', 'RULE', 'CASE', 'PART', 'ALL', 'END',
        'ADD', 'SET', 'USE', 'RUN', 'LOG', 'MAX', 'MIN', 'NEW', 'OLD', 'FOR',
        'SOURCE', 'TARGET', 'STATUS', 'COUNT', 'FORMAT', 'LENGTH', 'SIZE', 'AND',
        'REQUEST', 'RESPONSE', 'VALUE', 'RESULT', 'ERROR', 'INPUT', 'OUTPUT',
        'CLASS', 'OPTION', 'CONFIG', 'ENABLE', 'DISABLE', 'START', 'STOP',
        'PASS', 'FAIL', 'DONE', 'ACCEPT', 'COMPARE', 'RENAME', 'WORK',
        'OBJECT', 'STRING', 'ARRAY', 'PARAM', 'FUNCTION', 'METHOD', 'UNIX',
        # 파일 확장자
        'JPG', 'JPEG', 'PNG', 'GIF', 'PDF', 'TXT', 'CSV', 'XML', 'ZIP', 'CRT',
        # 지역/시간대 코드
        'USA', 'FRA', 'KST', 'GMT', 'UTC', 'COM', 'SEA', 'MAC', 'AND',
        # 인코딩
        'UTF', 'ASCII', 'SHIFT',
        # 시험 마킹
        'CORRECT', 'INCORRECT', 'YYYY',
        # 기타 노이즈
        'DOM', 'ALT', 'TAG', 'ADD', 'END', 'PUT', 'BOT',
        # 너무 일반적인 웹/인터넷 표준 (전 세계적으로 잘 알려진 개념)
        'HTTP', 'HTTPS', 'HTML', 'JSON', 'REST',
        # 범용 프로그래밍 언어 (CDNetworks 업무 특화 개념 아님)
        'JavaScript', 'TypeScript',
        # 플랫폼/도구 이름 (개념보다 서비스 명칭)
        'GitHub',
        # QUIC는 HTTP3-QUIC.md로 이미 존재
        'QUIC',
        # 내부 시스템 코드/약어 (CDNetworks 사내 코드, 공개 개념 아님)
        'SFDC', 'LWSEA', 'CONF', 'CDNW', 'PMUSER', 'CPSC', 'CDNSP', 'NCMS',
        # 내부 설정값·필드명
        'BYPASS', 'BUST', 'WISE', 'MyConf', 'NotAfter', 'Pre-Open',
        # 인물명
        'PARK',
        # 너무 일반적이거나 맥락 없는 단어
        'LongTerm', 'LegacyService', 'MISS', 'Real-Time', 'Concept',
        # 고객사명·외부 서비스명 (개념이 아닌 고유명사)
        'NetEase', 'WeCom', 'QuickTeam',
    })

    def __init__(self, vault_root, areas_path, days=7):
        self.vault_root = Path(vault_root).absolute()
        self.areas_path = Path(areas_path).absolute()
        self.days = days
        self.vault_file_stems = set()
        self.concept_stems = set()
        self.concept_stems_normalized = {}  # normalize(stem) → 원본 stem

    def build_indexes(self, concepts_tech_path, concepts_personal_path):
        """볼트 전체 인덱스 + Concept 노트 인덱스 생성"""
        for md_file in self.vault_root.rglob('*.md'):
            self.vault_file_stems.add(md_file.stem)
        for path in [concepts_tech_path, concepts_personal_path]:
            p = Path(path)
            if p.exists():
                for md_file in p.glob('*.md'):
                    self.concept_stems.add(md_file.stem)
        # 정규화 인덱스: 구분자 제거 + 소문자 → 원본 스템 매핑
        self.concept_stems_normalized = {
            re.sub(r'[\s\-_]', '', s).lower(): s
            for s in self.concept_stems
        }
        print(f"Index: 볼트 {len(self.vault_file_stems)}개 파일, Concept {len(self.concept_stems)}개")

    def get_target_files(self):
        """스캔 대상 파일 선정 (days=0이면 전체)"""
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(days=self.days) if self.days > 0 else None
        target = []
        for md_file in self.areas_path.rglob('*.md'):
            if cutoff:
                mtime = datetime.fromtimestamp(md_file.stat().st_mtime)
                if mtime < cutoff:
                    continue
            target.append(md_file)
        return target

    def get_frontmatter_and_body(self, filepath):
        try:
            content = filepath.read_text(encoding='utf-8')
        except Exception:
            return None, ''
        if not content.startswith('---'):
            return None, content
        parts = content.split('---', 2)
        if len(parts) < 3:
            return None, content
        try:
            fm = yaml.safe_load(parts[1])
            return fm, parts[2]
        except yaml.YAMLError:
            return None, content

    def _find_duplicate(self, candidate):
        """정규화 기반 중복 Concept 검사. 중복이면 기존 스템명 반환, 아니면 None."""
        norm = re.sub(r'[\s\-_]', '', candidate).lower()
        return self.concept_stems_normalized.get(norm)

    def classify_source(self, filepath):
        for part in filepath.parts:
            if part in self.TECH_DIRS:
                return 'Tech'
            if part in self.PERSONAL_DIRS:
                return 'Personal'
        return 'Tech'

    def extract_wikilink_candidates(self, body):
        """위키링크 중 Concept 후보만 추출 (영문 PascalCase-Hyphen 패턴)"""
        pattern = r'\[\[([^\]|#/]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]'
        candidates = []
        for link in re.findall(pattern, body):
            link = link.strip()
            if link in self.vault_file_stems:
                continue
            if self._find_duplicate(link):
                continue
            if re.match(r'^\d{4}-\d{2}-\d{2}', link):
                continue
            if not re.match(r'^[A-Z][a-zA-Z0-9\-]+$', link):
                continue
            candidates.append(link)
        return candidates

    def extract_keyword_candidates(self, body):
        """본문에서 반복 영문 기술 용어 추출"""
        # 코드 블록·인라인 코드 제거 (명령어/함수명 노이즈 방지)
        clean = re.sub(r'```[\s\S]*?```', '', body)
        clean = re.sub(r'`[^`\n]+`', '', clean)

        pascal = re.findall(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b', clean)
        allcaps = re.findall(r'\b[A-Z]{4,}\b', clean)   # 3→4자로 강화
        hyphen = re.findall(r'\b[A-Z][a-zA-Z]+-[A-Z][a-zA-Z]+(?:-[A-Z][a-zA-Z]+)?\b', clean)

        return [kw for kw in pascal + allcaps + hyphen
                if kw not in self.KEYWORD_BLOCKLIST]

    def mine(self, concepts_tech_path, concepts_personal_path):
        """마이닝 실행 — 후보 딕셔너리 반환"""
        self.build_indexes(concepts_tech_path, concepts_personal_path)
        target_files = self.get_target_files()
        print(f"스캔 대상: {len(target_files)}개 파일 (days={self.days})")

        wikilink_candidates = defaultdict(lambda: {'sources': [], 'category': 'Tech', 'method': 'wikilink'})
        keyword_counter = Counter()
        keyword_sources = defaultdict(set)
        keyword_category = {}
        duplicates = {}  # candidate → 기존 Concept 스템명

        for filepath in target_files:
            fm, body = self.get_frontmatter_and_body(filepath)
            if fm and fm.get('type') in self.SKIP_TYPES:
                continue
            category = self.classify_source(filepath)
            rel = str(filepath.relative_to(self.vault_root))

            for candidate in self.extract_wikilink_candidates(body):
                wikilink_candidates[candidate]['sources'].append(rel)
                wikilink_candidates[candidate]['category'] = category

            for kw in self.extract_keyword_candidates(body):
                dup = self._find_duplicate(kw)
                if dup:
                    duplicates[kw] = dup
                elif kw not in self.vault_file_stems:
                    keyword_counter[kw] += 1
                    keyword_sources[kw].add(rel)
                    keyword_category[kw] = category

        all_candidates = dict(wikilink_candidates)
        # wikilink 후보 중 정규화 중복 재검사 (extract 시점에서 걸러지지만 명시적으로 확인)
        for candidate in list(all_candidates.keys()):
            dup = self._find_duplicate(candidate)
            if dup:
                duplicates[candidate] = dup
                del all_candidates[candidate]

        for kw, unique_files in keyword_sources.items():
            if len(unique_files) >= 2 and kw not in all_candidates:
                all_candidates[kw] = {
                    'sources': list(unique_files),
                    'category': keyword_category.get(kw, 'Tech'),
                    'method': 'keyword',
                    'count': keyword_counter[kw],
                }

        return {
            'scanned_files': len(target_files),
            'existing_concepts': len(self.concept_stems),
            'candidates': all_candidates,
            'duplicates': duplicates,
            'days': self.days,
        }


def print_mining_report(result):
    candidates = result['candidates']
    tech = {k: v for k, v in candidates.items() if v.get('category') == 'Tech'}
    personal = {k: v for k, v in candidates.items() if v.get('category') == 'Personal'}
    period = f"최근 {result['days']}일" if result['days'] > 0 else "전체"

    print("\n" + "=" * 60)
    print(f"📋 신규 개념 후보 리포트 ({datetime.now().strftime('%Y-%m-%d')})")
    print(f"스캔 기간: {period} | 스캔 파일: {result['scanned_files']}개")
    print(f"기존 Concept 수: {result['existing_concepts']}개 | 신규 후보: {len(candidates)}개")
    print("=" * 60)

    def _print_candidates(items, icon):
        for name, info in sorted(items.items(), key=lambda x: -len(x[1]['sources'])):
            srcs = info['sources']
            names = [Path(s).name for s in srcs[:3]]
            more = f" 외 {len(srcs) - 3}개" if len(srcs) > 3 else ""
            method = f"[{info.get('method', 'wikilink')}]"
            print(f"  {icon} {name:<40} {method} — {', '.join(names)}{more}")

    if tech:
        print(f"\n🔧 Tech 후보 ({len(tech)}개)")
        _print_candidates(tech, "✦")
    if personal:
        print(f"\n👤 Personal 후보 ({len(personal)}개)")
        _print_candidates(personal, "✦")
    if not candidates:
        print("\n✅ 신규 개념 후보 없음")
    else:
        print(f"\n💡 --create 플래그로 {len(candidates)}개 Concept 노트를 자동 생성할 수 있습니다.")

    duplicates = result.get('duplicates', {})
    if duplicates:
        print(f"\n🔁 중복 제외됨 ({len(duplicates)}개 — 정규화 매칭으로 기존 Concept과 동일 판정)")
        for candidate, existing in sorted(duplicates.items()):
            print(f"   ✗ {candidate:<35} → [[{existing}]]")
    print()


def create_concept_notes(candidates, vault_root, concepts_tech_path, concepts_personal_path):
    """Concept 노트 자동 생성 (stub)"""
    today = datetime.now().strftime('%Y-%m-%d')
    created, skipped = [], []

    for name, info in candidates.items():
        category = info.get('category', 'Tech')
        target_dir = Path(concepts_tech_path) if category == 'Tech' else Path(concepts_personal_path)
        filename = name.replace(' ', '-')
        filepath = target_dir / f"{filename}.md"

        if filepath.exists():
            skipped.append(name)
            continue

        sources = info.get('sources', [])
        source_links = '\n'.join(f'\t- [[{Path(s).stem}]]' for s in sources[:5])
        default_tag = 'CDN' if category == 'Tech' else ''
        tag_line = f'  - {default_tag}' if default_tag else ''

        content = (
            f"---\n"
            f"type: concept\n"
            f"aliases: []\n"
            f"author:\n"
            f"  - \"[[이상훈]]\"\n"
            f"created: {today}\n"
            f"updated: {today}\n"
            f"tags:\n"
            f"{tag_line}\n"
            f"status: inProgress\n"
            f"---\n\n"
            f"# {name}\n\n"
            f"> 자동 생성된 Concept 노트 — 내용 보강 필요\n\n"
            f"## 관련 개념\n\n"
            f"## 관련 문서\n\n"
            f"{source_links}\n"
        )
        try:
            filepath.write_text(content, encoding='utf-8')
            created.append(name)
            print(f"  ✅ 생성: {filepath.relative_to(vault_root)}")
        except Exception as e:
            print(f"  ❌ 실패: {name} — {e}")

    print(f"\n생성: {len(created)}개 | 건너뜀(중복): {len(skipped)}개")
    return created, skipped


def main():
    parser = argparse.ArgumentParser(description='Analyze Obsidian Concept notes network')
    parser.add_argument('--mode', choices=['analyze', 'mine'], default='analyze',
                        help='실행 모드: analyze(기본) 또는 mine(마이닝)')
    parser.add_argument('--path', help='Path to Concepts folder (analyze 모드 필수)')
    parser.add_argument('--crosslink-path', help='Second Concepts folder for cross-link analysis (optional)')
    parser.add_argument('--output', help='Output JSON file path (optional)')
    parser.add_argument('--format', choices=['json', 'summary'], default='json',
                        help='Output format (default: json)')
    # mine 모드 전용 옵션
    parser.add_argument('--vault', help='볼트 루트 경로 (mine 모드 필수)')
    parser.add_argument('--areas-path', help='02_Areas 경로 (기본값: vault/02_Areas)')
    parser.add_argument('--tech-path', help='Concepts_Tech 경로 (기본값: vault/03_Resources/Concepts_Tech)')
    parser.add_argument('--personal-path', help='Concepts_Personal 경로 (기본값: vault/03_Resources/Concepts_Personal)')
    parser.add_argument('--days', type=int, default=7,
                        help='최근 N일 이내 수정 파일 스캔 (0=전체, mine 모드 전용)')
    parser.add_argument('--create', action='store_true',
                        help='후보를 Concept 노트로 자동 생성 (mine 모드 전용)')

    args = parser.parse_args()

    if args.mode == 'mine':
        if not args.vault:
            print("❌ mine 모드에는 --vault 옵션이 필요합니다")
            return
        vault = Path(args.vault).absolute()
        areas_path = args.areas_path or str(vault / '02_Areas')
        tech_path = args.tech_path or str(vault / '03_Resources/Concepts_Tech')
        personal_path = args.personal_path or str(vault / '03_Resources/Concepts_Personal')

        miner = ConceptMiner(str(vault), areas_path, days=args.days)
        result = miner.mine(tech_path, personal_path)
        print_mining_report(result)

        if args.create and result['candidates']:
            print("📝 Concept 노트 생성 중...")
            create_concept_notes(result['candidates'], vault, tech_path, personal_path)
        return

    # analyze 모드 (기존 동작)
    if not args.path:
        print("❌ analyze 모드에는 --path 옵션이 필요합니다")
        return

    analyzer = ConceptAnalyzer(args.path)
    analyzer.analyze_all()

    crosslink = None
    stems_b = None
    analyzer_b = None
    if args.crosslink_path:
        analyzer_b = ConceptAnalyzer(args.crosslink_path)
        analyzer_b.analyze_all()
        crosslink = analyze_crosslinks(analyzer, analyzer_b)
        stems_b = set(analyzer_b.concepts.keys())

    # 양쪽 stems 합산으로 dangling 탐지 — 각 폴더 리포트를 독립적으로 생성
    stems_a = set(analyzer.concepts.keys())
    report = analyzer.generate_report(additional_known_stems=stems_b)
    if crosslink:
        report['crosslink'] = crosslink

    report_b = None
    if analyzer_b is not None:
        report_b = analyzer_b.generate_report(additional_known_stems=stems_a)

    if args.format == 'json':
        output = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(output)
            print(f"Report saved to {args.output}")
        else:
            print(output)

    elif args.format == 'summary':
        print_summary(report, crosslink)
        if report_b is not None:
            print_summary(report_b)


if __name__ == '__main__':
    main()
