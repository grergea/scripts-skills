# Obsidian Link Health Checker

Obsidian 볼트의 위키링크 무결성을 검사하고 깨진 링크를 자동으로 탐지하는 파이썬 스크립트.

## 주요 기능

- ✅ 전체 볼트의 위키링크 검증
- 🔍 깨진 링크 탐지 및 유사 파일명 제안
- ⚠️ 모호한 링크 (동일 파일명 중복) 탐지
- 🔧 섹션 링크 오류 검증
- 📊 상세한 건강 상태 리포트

## 설치

```bash
# Python 3.7+ 필요
python3 --version

# 의존성 없음 (표준 라이브러리만 사용)
```

## 사용법

### 기본 사용

```bash
# 전체 볼트 점검
python obsidian-link-checker.py ~/mynotes
```

### 특정 폴더만 점검

```bash
# Concepts 폴더만
python obsidian-link-checker.py ~/mynotes --scope 03_Resources/Concepts_Tech/
```

### 옵션

| 옵션 | 설명 |
|------|------|
| `vault_path` | Obsidian 볼트 경로 (필수) |
| `--scope PATH` | 점검할 폴더 (상대 경로) |
| `--report-only` | 리포트만 생성 (수정 안 함) |

## 예시

```bash
# 전체 볼트 점검
python obsidian-link-checker.py /Users/shlee/leesh/mynotes

# Areas 폴더만 점검
python obsidian-link-checker.py /Users/shlee/leesh/mynotes --scope 02_Areas/

# Inbox 정리 전 빠른 점검
python obsidian-link-checker.py /Users/shlee/leesh/mynotes --scope 00_Inbox/
```

## 출력 예시

```
📂 볼트 스캔 중...
✅ 264개 파일 발견
🔗 위키링크 추출 중...
✅ 1887개 위키링크 추출
🔍 링크 검증 중...
✅ 검증 완료

================================================================================
📊 Link Health Report
================================================================================

Summary:
  검사한 파일: 264개
  총 위키링크: 1887개
  ✅ 유효한 링크: 1829개 (96.9%)
  ❌ 깨진 링크: 29개
  ⚠️  모호한 링크: 23개
  🔧 섹션 오류: 6개

✅ 볼트 링크 상태: 매우 양호 (96.9%)
================================================================================
```

## 제외 폴더

다음 폴더는 자동으로 제외됩니다:
- `04_Archive/`
- `05_Attachments/`
- `06_Metadata/Templates/`
- `.git/`, `.obsidian/`, `.trash/`, `.claude/`

## 정기 점검 권장

### 주간
```bash
# 매주 금요일 Inbox 정리 전
python obsidian-link-checker.py ~/mynotes --scope 00_Inbox/
```

### 월간
```bash
# 매월 첫째 주 전체 점검
python obsidian-link-checker.py ~/mynotes
```

## 라이선스

MIT License

## 관련 문서

자세한 사용법은 Obsidian 노트 참고:
`03_Resources/Scripts/obsidian-link-checker.py.md`
