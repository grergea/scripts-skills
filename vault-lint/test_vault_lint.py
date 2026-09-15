#!/usr/bin/env python3
"""vault-lint.py 회귀 테스트. 고정 fixture로 4개 검사(structure/links/meta/tags)의
판정 로직을 개별 검증한다. 실행: python3 -m unittest test_vault_lint -v
"""

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

SCRIPT_PATH = Path(__file__).parent / "vault-lint.py"
_spec = importlib.util.spec_from_file_location("vault_lint", SCRIPT_PATH)
vault_lint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vault_lint)

DEFAULT_FM = (
    "type: note\n"
    "author:\n"
    '  - "[[이상훈]]"\n'
    "created: 2026-09-10\n"
    "updated: 2026-09-10\n"
    "tags: []\n"
    "status: completed"
)


def write_note(root: Path, rel_path: str, frontmatter: str, body: str = ""):
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{frontmatter}\n---\n\n{body}", encoding="utf-8")
    return path


def run_quietly(func, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()):
        return func(*args, **kwargs)


class VaultLintTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmpdir.name)
        # DEFAULT_FM의 author 필드가 [[이상훈]]을 링크한다.
        # 대상 노트가 없으면 매 테스트가 링크 검사에서 깨진 링크 1개를 더 갖게 되므로 스텁으로 둔다.
        write_note(self.vault, "이상훈.md", DEFAULT_FM)

    def tearDown(self):
        self._tmpdir.cleanup()

    def scan(self):
        return run_quietly(vault_lint.scan_vault, self.vault)


class StructureChecks(VaultLintTestCase):
    def test_orphan_note_detected(self):
        write_note(self.vault, "02_Areas/A.md", DEFAULT_FM, "[[B]]")
        write_note(self.vault, "02_Areas/B.md", DEFAULT_FM, "[[A]]")
        write_note(self.vault, "02_Areas/Orphan.md", DEFAULT_FM, "아무도 링크하지 않음")

        summary = run_quietly(vault_lint.check_structure, self.scan(), None, 180)

        self.assertEqual(summary["고아 노트"], 1)

    def test_concept_naming_violation(self):
        write_note(self.vault, "03_Resources/Concepts_Tech/Valid-Name.md", DEFAULT_FM)
        write_note(self.vault, "03_Resources/Concepts_Tech/잘못된 이름.md", DEFAULT_FM)

        summary = run_quietly(vault_lint.check_structure, self.scan(), None, 180)

        self.assertEqual(summary["Concept 파일명 위반"], 1)

    def test_stem_collision_detected(self):
        write_note(self.vault, "02_Areas/AreaX/Sample.md", DEFAULT_FM)
        write_note(self.vault, "03_Resources/AreaY/Sample.md", DEFAULT_FM)

        summary = run_quietly(vault_lint.check_structure, self.scan(), None, 180)

        self.assertEqual(summary["파일명 충돌"], 1)

    def test_stale_concept_detected(self):
        old_fm = DEFAULT_FM.replace("type: note", "type: concept").replace(
            "2026-09-10", "2020-01-01"
        )
        write_note(self.vault, "03_Resources/Concepts_Tech/Old-Concept.md", old_fm)

        summary = run_quietly(vault_lint.check_structure, self.scan(), None, 180)

        self.assertEqual(summary["스테일 노트"], 1)


class LinkChecks(VaultLintTestCase):
    def test_broken_link_detected(self):
        write_note(self.vault, "02_Areas/A.md", DEFAULT_FM, "[[존재하지-않는-노트]]")

        summary = run_quietly(vault_lint.check_links, self.scan(), None)

        self.assertEqual(summary["깨진 링크"], 1)

    def test_valid_link_not_counted_broken(self):
        write_note(self.vault, "02_Areas/A.md", DEFAULT_FM, "[[B]]")
        write_note(self.vault, "02_Areas/B.md", DEFAULT_FM)

        summary = run_quietly(vault_lint.check_links, self.scan(), None)

        self.assertEqual(summary["깨진 링크"], 0)

    def test_ambiguous_link_detected(self):
        write_note(self.vault, "02_Areas/AreaX/Dup.md", DEFAULT_FM)
        write_note(self.vault, "03_Resources/AreaY/Dup.md", DEFAULT_FM)
        write_note(self.vault, "02_Areas/Referrer.md", DEFAULT_FM, "[[Dup]]")

        summary = run_quietly(vault_lint.check_links, self.scan(), None)

        self.assertEqual(summary["모호한 링크"], 1)

    def test_section_error_detected(self):
        write_note(self.vault, "02_Areas/A.md", DEFAULT_FM, "[[B#없는섹션]]")
        write_note(self.vault, "02_Areas/B.md", DEFAULT_FM, "## 실제 섹션\n내용")

        summary = run_quietly(vault_lint.check_links, self.scan(), None)

        self.assertEqual(summary["섹션 오류"], 1)


class MetaChecks(VaultLintTestCase):
    def test_missing_required_field_detected(self):
        fm = 'type: note\nauthor:\n  - "[[이상훈]]"\ncreated: 2026-09-10\ntags: []\nstatus: completed'
        write_note(self.vault, "02_Areas/Incomplete.md", fm)

        summary = run_quietly(vault_lint.check_meta, self.scan(), None)

        self.assertEqual(summary["메타데이터 이슈"], 1)

    def test_invalid_date_format_detected(self):
        fm = DEFAULT_FM.replace("created: 2026-09-10", "created: 2026/09/10")
        write_note(self.vault, "02_Areas/BadDate.md", fm)

        summary = run_quietly(vault_lint.check_meta, self.scan(), None)

        self.assertEqual(summary["메타데이터 이슈"], 1)

    def test_invalid_status_detected(self):
        fm = DEFAULT_FM.replace("status: completed", "status: done")
        write_note(self.vault, "02_Areas/BadStatus.md", fm)

        summary = run_quietly(vault_lint.check_meta, self.scan(), None)

        self.assertEqual(summary["메타데이터 이슈"], 1)

    def test_duplicate_tags_detected(self):
        fm = DEFAULT_FM.replace("tags: []", "tags:\n  - CDN\n  - CDN")
        write_note(self.vault, "02_Areas/DupTags.md", fm)

        summary = run_quietly(vault_lint.check_meta, self.scan(), None)

        self.assertEqual(summary["메타데이터 이슈"], 1)

    def test_no_frontmatter_detected(self):
        path = self.vault / "02_Areas" / "NoFrontmatter.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("frontmatter가 없는 노트", encoding="utf-8")

        summary = run_quietly(vault_lint.check_meta, self.scan(), None)

        self.assertEqual(summary["Frontmatter 없음"], 1)


class TagChecks(VaultLintTestCase):
    def test_similar_tag_pair_plural_detected(self):
        write_note(
            self.vault,
            "02_Areas/A.md",
            DEFAULT_FM.replace("tags: []", "tags:\n  - concept"),
        )
        write_note(
            self.vault,
            "02_Areas/B.md",
            DEFAULT_FM.replace("tags: []", "tags:\n  - concepts"),
        )

        summary = run_quietly(vault_lint.check_tags, self.scan(), 70)

        self.assertEqual(summary["유사 태그 쌍"], 1)

    def test_similar_tag_pair_hyphen_underscore_detected(self):
        write_note(
            self.vault,
            "02_Areas/A.md",
            DEFAULT_FM.replace("tags: []", "tags:\n  - web-performance"),
        )
        write_note(
            self.vault,
            "02_Areas/B.md",
            DEFAULT_FM.replace("tags: []", "tags:\n  - web_performance"),
        )

        summary = run_quietly(vault_lint.check_tags, self.scan(), 70)

        self.assertEqual(summary["유사 태그 쌍"], 1)

    def test_dissimilar_tags_not_paired(self):
        write_note(
            self.vault,
            "02_Areas/A.md",
            DEFAULT_FM.replace("tags: []", "tags:\n  - CDN"),
        )
        write_note(
            self.vault,
            "02_Areas/B.md",
            DEFAULT_FM.replace("tags: []", "tags:\n  - DNS"),
        )

        summary = run_quietly(vault_lint.check_tags, self.scan(), 70)

        self.assertEqual(summary["유사 태그 쌍"], 0)


if __name__ == "__main__":
    unittest.main()
