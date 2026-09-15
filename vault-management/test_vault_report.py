#!/usr/bin/env python3
"""vault-report.py 회귀 테스트. 순수 함수(get_created/fm_date/section_*)는 직접 호출하고,
records가 필요한 함수(collect_clippings/count_isolated/concept_coverage)는 vault-lint의
scan_vault로 임시 볼트를 스캔해 넘긴다. CONCEPT_DIRS/OUTPUT_DIR처럼 실제 볼트를 가리키는
모듈 전역 상수는 테스트 중에만 임시 경로로 바꿔치기하고 tearDown에서 원복한다.
실행: python3 -m unittest test_vault_report -v
"""

import contextlib
import importlib.util
import io
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

REPORT_SCRIPT = Path(__file__).parent / "vault-report.py"
_report_spec = importlib.util.spec_from_file_location("vault_report", REPORT_SCRIPT)
vault_report = importlib.util.module_from_spec(_report_spec)
_report_spec.loader.exec_module(vault_report)

LINT_SCRIPT = Path(__file__).parent.parent / "vault-lint" / "vault-lint.py"
_lint_spec = importlib.util.spec_from_file_location("vault_lint", LINT_SCRIPT)
vault_lint = importlib.util.module_from_spec(_lint_spec)
_lint_spec.loader.exec_module(vault_lint)

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
    with (
        contextlib.redirect_stdout(io.StringIO()),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        return func(*args, **kwargs)


class PureFunctionTests(unittest.TestCase):
    def test_get_created_parses_valid_date(self):
        text = "---\ntype: note\ncreated: 2026-01-15\n---\n\n본문"
        self.assertEqual(vault_report.get_created(text), vault_report.date(2026, 1, 15))

    def test_get_created_returns_none_without_frontmatter(self):
        self.assertIsNone(vault_report.get_created("frontmatter가 없는 노트"))

    def test_fm_date_handles_date_object(self):
        d = vault_report.date(2026, 2, 1)
        self.assertEqual(vault_report.fm_date({"updated": d}, "updated"), d)

    def test_fm_date_handles_string(self):
        self.assertEqual(
            vault_report.fm_date({"updated": "2026-02-01"}, "updated"),
            vault_report.date(2026, 2, 1),
        )

    def test_fm_date_handles_missing_field(self):
        self.assertIsNone(vault_report.fm_date({}, "updated"))
        self.assertIsNone(vault_report.fm_date(None, "updated"))


class SectionFormattingTests(unittest.TestCase):
    def test_section_link_health_uses_current_skill_names(self):
        output = vault_report.section_link_health(2, 1)

        self.assertIn("/vault-lint fix:links", output)
        self.assertIn("/vault-concept-analyzer", output)
        self.assertNotIn("/autoresearch", output)
        self.assertNotIn("@concept-analyzer", output)

    def test_section_actions_uses_current_skill_names(self):
        output = vault_report.section_actions(
            clips=[], tech=10, personal=0, broken=1, isolated=1, unlinked=[]
        )

        self.assertIn("/vault-lint fix:links", output)
        self.assertIn("/vault-concept-analyzer", output)
        self.assertIn("/vault-ingest", output)
        self.assertNotIn("/autoresearch", output)
        self.assertNotIn("@concept-analyzer", output)
        self.assertNotIn("`/ingest`", output)

    def test_section_history_appends_new_row(self):
        prev_rows = ["| 2026-08-01 | 3 | 2 | 1 | 100/20 | 5 |"]

        output = vault_report.section_history(
            prev_rows,
            clips_n=1,
            broken=0,
            isolated=0,
            tech=101,
            personal=21,
            unlinked_n=2,
        )

        self.assertIn("2026-08-01", output)
        self.assertIn(f"| {vault_report.today} | 0 | 1 | 0 | 101/21 | 2 |", output)


class LoadHistoryTests(unittest.TestCase):
    def test_load_history_excludes_todays_row(self):
        content = (
            "## 점검 이력\n\n"
            "| 점검일 | 깨진 링크 | 미처리 클리핑 | #isolated | Tech/Personal | Concept 미연결 |\n"
            "|--------|----------|-------------|-----------|---------------|----------------|\n"
            "| 2026-08-01 | 3 | 2 | 1 | 100/20 | 5 |\n"
            f"| {vault_report.today} | 0 | 0 | 0 | 100/20 | 0 |\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "report.md"
            path.write_text(content, encoding="utf-8")

            rows = vault_report.load_history(path)

        self.assertEqual(len(rows), 1)
        self.assertIn("2026-08-01", rows[0])
        self.assertFalse(any(str(vault_report.today) in r for r in rows))


class RecordBasedTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def scan(self):
        return run_quietly(vault_lint.scan_vault, self.vault)


class ClippingTests(RecordBasedTests):
    def test_collect_clippings_filters_by_age_and_path(self):
        old_date = vault_report.today - timedelta(days=40)
        recent_date = vault_report.today - timedelta(days=5)
        old_fm = DEFAULT_FM.replace("2026-09-10", str(old_date))
        recent_fm = DEFAULT_FM.replace("2026-09-10", str(recent_date))

        write_note(self.vault, "00_Inbox/Clippings/Old-Clip.md", old_fm)
        write_note(self.vault, "00_Inbox/Clippings/Recent-Clip.md", recent_fm)
        write_note(self.vault, "00_Inbox/Scratchpad/Ignored.md", old_fm)

        clips = vault_report.collect_clippings(self.scan())

        self.assertEqual({c["name"] for c in clips}, {"Old-Clip"})


class IsolatedConceptTests(RecordBasedTests):
    def test_count_isolated_detects_tag_and_inline(self):
        tagged_fm = DEFAULT_FM.replace("type: note", "type: concept").replace(
            "tags: []", "tags:\n  - isolated"
        )
        write_note(
            self.vault, "03_Resources/Concepts_Tech/Isolated-Tagged.md", tagged_fm
        )
        write_note(
            self.vault,
            "03_Resources/Concepts_Tech/Isolated-Inline.md",
            DEFAULT_FM.replace("type: note", "type: concept"),
            "본문에 #isolated 태그가 있음",
        )
        write_note(
            self.vault,
            "03_Resources/Concepts_Tech/Connected.md",
            DEFAULT_FM.replace("type: note", "type: concept"),
            "[[Isolated-Tagged]]",
        )

        self.assertEqual(vault_report.count_isolated(self.scan()), 2)


class ConceptCoverageTests(RecordBasedTests):
    def setUp(self):
        super().setUp()
        self._orig_concept_dirs = vault_report.CONCEPT_DIRS
        vault_report.CONCEPT_DIRS = [
            self.vault / "03_Resources" / "Concepts_Tech",
            self.vault / "03_Resources" / "Concepts_Personal",
        ]

    def tearDown(self):
        vault_report.CONCEPT_DIRS = self._orig_concept_dirs
        super().tearDown()

    def test_concept_coverage_detects_unlinked_source(self):
        write_note(
            self.vault,
            "03_Resources/Concepts_Tech/Some-Concept.md",
            DEFAULT_FM.replace("type: note", "type: concept"),
        )
        write_note(
            self.vault, "02_Areas/Linked-Source.md", DEFAULT_FM, "[[Some-Concept]] 참고"
        )
        write_note(self.vault, "02_Areas/Unlinked-Source.md", DEFAULT_FM, "연결 없음")

        stats, unlinked = vault_report.concept_coverage(self.scan())

        self.assertEqual(stats["02_Areas"]["total"], 2)
        self.assertEqual(stats["02_Areas"]["linked"], 1)
        self.assertEqual({u["name"] for u in unlinked}, {"Unlinked-Source"})

    def test_concept_coverage_excludes_meeting_type(self):
        write_note(
            self.vault,
            "02_Areas/Meeting-Note.md",
            DEFAULT_FM.replace("type: note", "type: meeting"),
        )
        write_note(self.vault, "02_Areas/Regular-Note.md", DEFAULT_FM)

        stats, _ = vault_report.concept_coverage(self.scan())

        self.assertEqual(stats["02_Areas"]["total"], 1)


class ClosePreviousReportsTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self._tmpdir.name)
        self._orig_output_dir = vault_report.OUTPUT_DIR
        vault_report.OUTPUT_DIR = self.output_dir

    def tearDown(self):
        vault_report.OUTPUT_DIR = self._orig_output_dir
        self._tmpdir.cleanup()

    def test_close_previous_reports_marks_old_month_completed(self):
        old_month = (vault_report.today.replace(day=1) - timedelta(days=365)).strftime(
            "%Y-%m"
        )
        old_file = self.output_dir / f"Concept_Review_{old_month}.md"
        old_file.write_text("---\nstatus: inProgress\n---\n\n내용", encoding="utf-8")
        current_file = self.output_dir / f"Concept_Review_{vault_report.month_str}.md"
        current_file.write_text(
            "---\nstatus: inProgress\n---\n\n내용", encoding="utf-8"
        )

        run_quietly(vault_report.close_previous_reports)

        self.assertIn("status: completed", old_file.read_text(encoding="utf-8"))
        self.assertIn("status: inProgress", current_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
