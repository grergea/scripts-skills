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

    def test_dataview_indexed_note_is_not_orphan(self):
        # Index는 위키링크가 아니라 Dataview로 노트를 모은다.
        # 들어오는 링크가 없어도 Index를 통해 도달 가능하므로 고아가 아니다.
        write_note(
            self.vault,
            "03_Resources/Index/🏷 Scripts.md",
            DEFAULT_FM.replace("type: note", "type: index"),
            '```dataview\nTABLE file.link\nFROM "03_Resources/Scripts"\n'
            'WHERE type = "script"\n```',
        )
        write_note(self.vault, "03_Resources/Scripts/CDN/tool.md", DEFAULT_FM)
        write_note(self.vault, "02_Areas/Unindexed.md", DEFAULT_FM)

        summary = run_quietly(
            vault_lint.check_structure, self.scan(), None, 180, self.vault
        )

        self.assertEqual(summary["고아 노트"], 1)

    def test_personal_folders_excluded_by_prefix(self):
        for name in ("개인_보험", "개인_금융", "개인_신규영역"):
            write_note(self.vault, f"02_Areas/{name}/기록.md", DEFAULT_FM)

        summary = run_quietly(vault_lint.check_structure, self.scan(), None, 180)

        self.assertEqual(summary["고아 노트"], 0)

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

    def test_relative_link_detected_with_suggestion(self):
        write_note(self.vault, "03_Resources/Concepts_Tech/DNSSEC.md", DEFAULT_FM)
        write_note(
            self.vault,
            "02_Areas/업무_CDN/A.md",
            DEFAULT_FM,
            "[[../../03_Resources/Concepts_Tech/DNSSEC]] 참조",
        )

        summary = run_quietly(vault_lint.check_links, self.scan(), None)

        self.assertEqual(summary["상대경로 링크"], 1)
        # 상대경로는 유효/깨짐 집계에 섞이지 않는다
        self.assertEqual(summary["깨진 링크"], 0)

    def test_normalized_link_not_flagged_relative(self):
        write_note(self.vault, "03_Resources/Concepts_Tech/DNSSEC.md", DEFAULT_FM)
        write_note(self.vault, "02_Areas/업무_CDN/A.md", DEFAULT_FM, "[[DNSSEC]] 참조")

        summary = run_quietly(vault_lint.check_links, self.scan(), None)

        self.assertEqual(summary["상대경로 링크"], 0)
        self.assertEqual(summary["깨진 링크"], 0)

    def test_attachment_embed_is_not_broken(self):
        (self.vault / "05_Attachments").mkdir(parents=True, exist_ok=True)
        (self.vault / "05_Attachments" / "diagram.png").write_bytes(b"\x89PNG")
        write_note(self.vault, "02_Areas/A.md", DEFAULT_FM, "![[diagram.png]]")

        summary = run_quietly(vault_lint.check_links, self.scan(), None, self.vault)

        self.assertEqual(summary["깨진 링크"], 0)

    def test_missing_attachment_still_broken(self):
        write_note(self.vault, "02_Areas/A.md", DEFAULT_FM, "![[없는이미지.png]]")

        summary = run_quietly(vault_lint.check_links, self.scan(), None, self.vault)

        self.assertEqual(summary["깨진 링크"], 1)

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

    def test_spaced_tag_detected(self):
        fm = DEFAULT_FM.replace("tags: []", 'tags:\n  - "AI Tool"\n  - CDN')
        write_note(self.vault, "02_Areas/SpacedTag.md", fm)

        summary = run_quietly(vault_lint.check_meta, self.scan(), None)

        self.assertEqual(summary["메타데이터 이슈"], 1)

    def test_hyphenated_tag_accepted(self):
        fm = DEFAULT_FM.replace("tags: []", "tags:\n  - web-performance\n  - CDN")
        write_note(self.vault, "02_Areas/GoodTag.md", fm)

        summary = run_quietly(vault_lint.check_meta, self.scan(), None)

        self.assertEqual(summary["메타데이터 이슈"], 0)

    def test_duplicate_tags_detected(self):
        fm = DEFAULT_FM.replace("tags: []", "tags:\n  - CDN\n  - CDN")
        write_note(self.vault, "02_Areas/DupTags.md", fm)

        summary = run_quietly(vault_lint.check_meta, self.scan(), None)

        self.assertEqual(summary["메타데이터 이슈"], 1)

    def test_troubleshooting_requires_customer(self):
        fm = DEFAULT_FM.replace("type: note", "type: troubleshooting")
        fm += '\nresponder:\n  - "[[이상훈]]"'
        write_note(
            self.vault, "02_Areas/Derived.md", fm, "### 1. 장애 개요\n- 대상: A사"
        )

        summary = run_quietly(vault_lint.check_meta, self.scan(), None)

        self.assertEqual(summary["메타데이터 이슈"], 1)

    def test_base_report_exempt_from_customer(self):
        # 기준 보고서는 고객사별 파생본의 원본이라 customer를 의도적으로 비운다
        fm = DEFAULT_FM.replace("type: note", "type: troubleshooting")
        fm += '\nresponder:\n  - "[[이상훈]]"'
        write_note(
            self.vault,
            "02_Areas/Base.md",
            fm,
            "- **수신**: [고객사명 - 파생 시 기입]\n\n### 1. 장애 개요",
        )

        summary = run_quietly(vault_lint.check_meta, self.scan(), None)

        self.assertEqual(summary["메타데이터 이슈"], 0)

    def test_no_frontmatter_detected(self):
        path = self.vault / "02_Areas" / "NoFrontmatter.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("frontmatter가 없는 노트", encoding="utf-8")

        summary = run_quietly(vault_lint.check_meta, self.scan(), None)

        self.assertEqual(summary["Frontmatter 없음"], 1)


class ScanScopeChecks(VaultLintTestCase):
    """볼트 안의 코드 저장소·도구 산출물은 노트가 아니므로 스캔에서 빠져야 한다."""

    def test_vault_repos_excluded(self):
        write_note(self.vault, "02_Areas/Real-Note.md", DEFAULT_FM)
        # Claude Code 스킬 정의 — 노트 frontmatter 스키마 대상이 아님
        write_note(
            self.vault,
            "project-rorobot/solonbot/skills/foo/SKILL.md",
            "name: foo\ndescription: bar",
        )
        write_note(self.vault, "cdnw-api-tools/README.md", "name: tool")
        write_note(self.vault, "html-share/CLAUDE.md", "name: share")

        scanned = {r.rel for r in self.scan()}

        self.assertIn("02_Areas/Real-Note.md", scanned)
        self.assertNotIn("project-rorobot/solonbot/skills/foo/SKILL.md", scanned)
        self.assertNotIn("cdnw-api-tools/README.md", scanned)
        self.assertNotIn("html-share/CLAUDE.md", scanned)

    def test_tool_artifacts_excluded_at_any_depth(self):
        write_note(self.vault, ".pytest_cache/README.md", "x: 1")
        write_note(self.vault, "02_Areas/sub/.pytest_cache/README.md", "x: 1")
        write_note(self.vault, "02_Areas/sub/__pycache__/cached.md", "x: 1")
        write_note(self.vault, "02_Areas/Keep.md", DEFAULT_FM)

        scanned = {r.rel for r in self.scan()}

        self.assertEqual(scanned, {"이상훈.md", "02_Areas/Keep.md"})


class DeterminismChecks(VaultLintTestCase):
    """같은 입력 → 같은 출력. set 순회에 의존하면 실행마다 순서가 흔들렸다."""

    def _capture(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            records = vault_lint.scan_vault(self.vault)
            vault_lint.check_meta(records, None)
            vault_lint.check_tags(records, 70)
        return buf.getvalue()

    def test_output_is_identical_across_runs(self):
        for name in ("Alpha", "Beta", "Gamma"):
            write_note(self.vault, f"02_Areas/{name}.md", "type: note")
        write_note(
            self.vault,
            "02_Areas/Tagged.md",
            DEFAULT_FM.replace("tags: []", "tags:\n  - concept\n  - concepts\n  - CDN"),
        )

        self.assertEqual(self._capture(), self._capture())

    def test_missing_field_report_order_is_sorted(self):
        write_note(self.vault, "02_Areas/Bare.md", "type: note")

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            vault_lint.check_meta(self.scan(), None)
        out = buf.getvalue()

        fields = [
            f for f in ("author", "created", "status", "tags", "updated") if f in out
        ]
        self.assertEqual(fields, sorted(fields))


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

    def test_wikilink_anchor_is_not_a_tag(self):
        write_note(
            self.vault,
            "02_Areas/A.md",
            DEFAULT_FM,
            "목차 [[가이드#관련 개념]] 와 [[#0. 지원 프로토콜]] 참조",
        )

        summary = run_quietly(vault_lint.check_tags, self.scan(), 70)

        self.assertEqual(summary["드문 태그"], 0)

    def test_url_fragment_is_not_a_tag(self):
        write_note(
            self.vault,
            "02_Areas/A.md",
            DEFAULT_FM,
            "참고 https://cloud.google.com/docs/set-up#enable-api 링크",
        )

        summary = run_quietly(vault_lint.check_tags, self.scan(), 70)

        self.assertEqual(summary["드문 태그"], 0)

    def test_numeric_only_tag_rejected(self):
        write_note(
            self.vault, "02_Areas/A.md", DEFAULT_FM, "PR #15238 과 이슈 #207 참고"
        )

        summary = run_quietly(vault_lint.check_tags, self.scan(), 70)

        self.assertEqual(summary["드문 태그"], 0)

    def test_real_inline_tag_still_detected(self):
        write_note(self.vault, "02_Areas/A.md", DEFAULT_FM, "본문에 #실제태그 있음")

        summary = run_quietly(vault_lint.check_tags, self.scan(), 70)

        self.assertEqual(summary["드문 태그"], 1)

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
