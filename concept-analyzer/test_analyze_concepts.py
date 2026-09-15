#!/usr/bin/env python3
"""analyze_concepts.py 회귀 테스트. 고정 fixture로 ConceptAnalyzer/ConceptMiner의
핵심 판정 로직을 검증한다. 실행: python3 -m unittest test_analyze_concepts -v
"""

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).parent / "analyze_concepts.py"
_spec = importlib.util.spec_from_file_location("analyze_concepts", SCRIPT_PATH)
analyze_concepts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(analyze_concepts)

DEFAULT_FM = (
    "type: concept\n"
    "aliases: []\n"
    "author:\n"
    '  - "[[이상훈]]"\n'
    "created: 2026-09-10\n"
    "updated: 2026-09-10\n"
    "tags: []\n"
    "status: completed"
)


def write_concept(folder: Path, name: str, body: str = "", frontmatter: str = None):
    folder.mkdir(parents=True, exist_ok=True)
    fm = frontmatter if frontmatter is not None else DEFAULT_FM
    (folder / f"{name}.md").write_text(f"---\n{fm}\n---\n\n{body}", encoding="utf-8")


def write_plain(path: Path, content: str = "아무 내용"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def run_quietly(func, *args, **kwargs):
    with (
        contextlib.redirect_stdout(io.StringIO()),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        return func(*args, **kwargs)


class AnalyzerTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.vault_root = Path(self._tmpdir.name)
        (self.vault_root / ".obsidian").mkdir()
        self.concepts_tech = self.vault_root / "03_Resources" / "Concepts_Tech"
        self.concepts_personal = self.vault_root / "03_Resources" / "Concepts_Personal"

    def tearDown(self):
        self._tmpdir.cleanup()

    def analyze(self, path=None):
        analyzer = analyze_concepts.ConceptAnalyzer(str(path or self.concepts_tech))
        run_quietly(analyzer.analyze_all)
        return analyzer


class NetworkMetrics(AnalyzerTestCase):
    def test_hub_and_isolated_classification(self):
        write_concept(self.concepts_tech, "Hub")
        write_concept(self.concepts_tech, "Isolated")
        write_concept(self.concepts_tech, "Linker-A", body="[[Hub]]")
        write_concept(self.concepts_tech, "Linker-B", body="[[Hub]]")
        write_concept(self.concepts_tech, "Linker-C", body="[[Hub]]")

        analyzer = self.analyze()
        stats = run_quietly(analyzer.generate_statistics)

        isolated_names = {c["filename"] for c in stats["isolated_concepts"]}
        self.assertEqual(stats["hub_concepts"][0]["filename"], "Hub")
        self.assertIn("Isolated", isolated_names)
        self.assertNotIn("Hub", isolated_names)

    def test_weak_concept_detected(self):
        write_concept(self.concepts_tech, "Target1")
        write_concept(self.concepts_tech, "Target2")
        write_concept(self.concepts_tech, "Target3")
        write_concept(self.concepts_tech, "Weak", body="[[Target1]]")
        write_concept(
            self.concepts_tech, "Strong", body="[[Target1]] [[Target2]] [[Target3]]"
        )

        analyzer = self.analyze()
        stats = run_quietly(analyzer.generate_statistics)

        weak_names = {c["filename"] for c in stats["weak_concepts"]}
        self.assertIn("Weak", weak_names)
        self.assertNotIn("Strong", weak_names)

    def test_mermaid_usage_counted(self):
        write_concept(
            self.concepts_tech, "WithMermaid", body="```mermaid\ngraph TD; A-->B;\n```"
        )
        write_concept(self.concepts_tech, "WithoutMermaid", body="일반 본문")

        analyzer = self.analyze()
        stats = run_quietly(analyzer.generate_statistics)

        self.assertEqual(stats["mermaid_count"], 1)

    def test_malformed_tag_dict_detected(self):
        fm = DEFAULT_FM.replace("tags: []", "tags:\n  - CDN\n  - 도메인: DNS")
        write_concept(self.concepts_tech, "MalformedTag", frontmatter=fm)

        analyzer = self.analyze()
        stats = run_quietly(analyzer.generate_statistics)

        malformed_names = {item["filename"] for item in stats["malformed_tag_files"]}
        self.assertIn("MalformedTag", malformed_names)


class LinkIntegrity(AnalyzerTestCase):
    def test_dangling_link_detected(self):
        write_concept(self.concepts_tech, "A", body="[[존재하지-않는-개념]]")

        analyzer = self.analyze()
        stats = run_quietly(analyzer.generate_statistics)

        dangling_targets = {item["target"] for item in stats["dangling_links"]}
        self.assertIn("존재하지-않는-개념", dangling_targets)

    def test_malformed_wikilink_md_suffix_detected(self):
        write_concept(self.concepts_tech, "A", body="[[SomeFile.md]]")

        analyzer = self.analyze()
        stats = run_quietly(analyzer.generate_statistics)

        malformed = {item["target"] for item in stats["malformed_wikilinks"]}
        self.assertIn("SomeFile.md", malformed)

    def test_naming_mismatch_detected(self):
        write_plain(self.vault_root / "02_Areas" / "Correct-Name.md")
        write_concept(self.concepts_tech, "A", body="[[CorrectName]]")

        analyzer = self.analyze()
        stats = run_quietly(analyzer.generate_statistics)

        mismatches = {
            item["link"]: item["correct"] for item in stats["naming_mismatches"]
        }
        self.assertEqual(mismatches.get("CorrectName"), "Correct-Name")

    def test_valid_link_not_dangling(self):
        write_concept(self.concepts_tech, "A", body="[[B]]")
        write_concept(self.concepts_tech, "B")

        analyzer = self.analyze()
        stats = run_quietly(analyzer.generate_statistics)

        dangling_targets = {item["target"] for item in stats["dangling_links"]}
        self.assertNotIn("B", dangling_targets)


class CrossLinks(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.vault_root = Path(self._tmpdir.name)
        (self.vault_root / ".obsidian").mkdir()
        self.tech = self.vault_root / "03_Resources" / "Concepts_Tech"
        self.personal = self.vault_root / "03_Resources" / "Concepts_Personal"

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_crosslink_counted_both_directions(self):
        write_concept(self.tech, "T1", body="[[P1]]")
        write_concept(self.personal, "P1", body="[[T1]]")

        analyzer_a = analyze_concepts.ConceptAnalyzer(str(self.tech))
        run_quietly(analyzer_a.analyze_all)
        analyzer_b = analyze_concepts.ConceptAnalyzer(str(self.personal))
        run_quietly(analyzer_b.analyze_all)

        crosslink = run_quietly(
            analyze_concepts.analyze_crosslinks, analyzer_a, analyzer_b
        )

        self.assertEqual(crosslink["a_to_b_total"], 1)
        self.assertEqual(crosslink["b_to_a_total"], 1)
        self.assertIn(("P1", 1), crosslink["a_to_b_top"])
        self.assertIn(("T1", 1), crosslink["b_to_a_top"])


class MinerTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.vault_root = Path(self._tmpdir.name)
        (self.vault_root / ".obsidian").mkdir()
        self.areas = self.vault_root / "02_Areas" / "업무_CDN"
        self.concepts_tech = self.vault_root / "03_Resources" / "Concepts_Tech"
        self.concepts_personal = self.vault_root / "03_Resources" / "Concepts_Personal"
        self.concepts_tech.mkdir(parents=True)
        self.concepts_personal.mkdir(parents=True)

    def tearDown(self):
        self._tmpdir.cleanup()

    def mine(self, days=0):
        miner = analyze_concepts.ConceptMiner(
            str(self.vault_root), str(self.areas), days=days
        )
        return run_quietly(
            miner.mine, str(self.concepts_tech), str(self.concepts_personal)
        )

    def test_wikilink_candidate_extracted(self):
        write_plain(self.areas / "Note.md", "[[New-Concept-Candidate]] 언급")

        result = self.mine()

        self.assertIn("New-Concept-Candidate", result["candidates"])
        self.assertEqual(
            result["candidates"]["New-Concept-Candidate"]["category"], "Tech"
        )

    def test_keyword_needs_two_sources(self):
        write_plain(self.areas / "NoteA.md", "EdgeCache 개념 설명")
        write_plain(self.areas / "NoteB.md", "EdgeCache 다시 등장")
        write_plain(self.areas / "NoteC.md", "SoloMention 한 번만 등장")

        result = self.mine()

        self.assertIn("EdgeCache", result["candidates"])
        self.assertNotIn("SoloMention", result["candidates"])

    def test_blocklisted_keyword_excluded(self):
        write_plain(self.areas / "NoteA.md", "HTTP 프로토콜 설명")
        write_plain(self.areas / "NoteB.md", "HTTP 다시 등장")

        result = self.mine()

        self.assertNotIn("HTTP", result["candidates"])

    def test_keyword_duplicate_excluded(self):
        write_concept(self.concepts_tech, "Token-Bucket")
        write_plain(self.areas / "NoteA.md", "TokenBucket 알고리즘 설명")
        write_plain(self.areas / "NoteB.md", "TokenBucket 다시 등장")

        result = self.mine()

        self.assertNotIn("TokenBucket", result["candidates"])
        self.assertEqual(result["duplicates"].get("TokenBucket"), "Token-Bucket")


if __name__ == "__main__":
    unittest.main()
