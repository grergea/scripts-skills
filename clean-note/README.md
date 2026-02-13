# clean-note - Obsidian 노트 정리 스크립트

Gemini/ChatGPT 등에서 복사한 텍스트의 불필요한 요소를 제거하는 bash 스크립트입니다.

## Features

- **마침표 앞 숫자 제거**: `합니다123.` → `합니다.`
- **줄 끝 숫자 제거**: `내용 15` → `내용`
- **HTML 태그 제거**: `<br>` 태그 삭제
- **+숫자 라인 제거**: `+1`, `+2` 등 단독 라인 삭제
- **연속 빈 줄 정리**: 2줄 이상 빈 줄 → 1줄로 축소

## Requirements

```bash
# macOS / Linux 기본 포함
sed, awk
```

## Installation

```bash
# 저장소 클론
git clone https://github.com/grergea/scripts.git
cd scripts/clean-note

# 실행 권한 부여
chmod +x clean-note.sh

# (선택) PATH에 추가
sudo ln -s $(pwd)/clean-note.sh /usr/local/bin/clean-note
```

## Usage

```bash
./clean-note.sh <파일경로> [옵션]
```

### Options

| Option | Description |
|--------|-------------|
| `--dry-run` | 변경사항 미리보기 (실제 수정 안함) |
| `--backup` | 원본 파일 백업 후 정리 (.bak 확장자) |
| `--verbose` | 상세 출력 모드 |
| `-h, --help` | 도움말 표시 |

### Examples

```bash
# 기본 사용
./clean-note.sh "노트.md"

# 미리보기 (실제 수정 안함)
./clean-note.sh "노트.md" --dry-run

# 백업 후 정리
./clean-note.sh "노트.md" --backup

# 상세 출력
./clean-note.sh "노트.md" --backup --verbose
```

## Claude Code Integration

Claude Code Skill로 등록하여 `/clean-note` 명령으로 실행 가능:

```
/clean-note ~/mynotes/02_Areas/문서.md
/clean-note "CDN 장애 사례.md" --dry-run
```

## Sample Output

```
[INFO] 파일 분석 중: Vhost 설정 관리.md

======================================
        정리 결과 요약
======================================
라인 수:          85 → 66 (19줄 감소)
======================================

[OK] 정리 완료: Vhost 설정 관리.md
```

## Token Savings

| 방식 | 토큰 사용량 |
|------|------------|
| Claude가 직접 편집 | 높음 (전체 파일 읽기/쓰기) |
| 스크립트 실행 | 낮음 (명령어만 실행) |

약 **90% 이상** 토큰 절감 가능

## Changelog

### v1.1.0 (2026-01-06)
- 마침표 앞 숫자 패턴 추가 (`합니다123.` → `합니다.`)
- 줄 끝 공백+숫자 패턴 추가
- macOS 호환 awk 기반 빈 줄 정리

### v1.0.0 (2026-01-06)
- 초기 릴리스
