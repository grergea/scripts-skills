#!/bin/bash
#===============================================================================
# clean-note.sh - Obsidian 노트 정리 스크립트
#===============================================================================
# 용도: Gemini/ChatGPT 등에서 복사한 노트의 불필요한 요소 제거
#
# 기능:
#   1. 문장 끝 불필요한 숫자 제거 (마침표 앞, 줄 끝)
#   2. <br> 태그 제거
#   3. +숫자 라인 제거 (+1, +2 등)
#   4. 연속 빈 줄 정리 (2줄 이상 → 1줄)
#   5. Gemini cite 패턴 제거 ([cite: X], [cite: X-Y], [cite_start] 등)
#   6. 코드 블록 앞 언어 라벨 제거 (Bash, JSON, YAML 등 별도 줄)
#
# 사용법:
#   clean-note.sh <파일경로>
#   clean-note.sh <파일경로> --dry-run    # 변경사항 미리보기
#   clean-note.sh <파일경로> --backup     # 백업 후 정리
#
# 작성: 이상훈
# 버전: 1.2.0
#===============================================================================

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 사용법 출력
usage() {
    cat << EOF
사용법: $(basename "$0") <파일경로> [옵션]

옵션:
  --dry-run    변경사항 미리보기 (실제 수정 안함)
  --backup     원본 파일 백업 후 정리 (.bak 확장자)
  --verbose    상세 출력 모드
  -h, --help   도움말 출력

예시:
  $(basename "$0") "노트.md"
  $(basename "$0") "노트.md" --dry-run
  $(basename "$0") "노트.md" --backup --verbose
EOF
    exit 0
}

# 로그 함수
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }

# 연속 빈 줄 제거 함수 (macOS 호환)
squeeze_blank_lines() {
    awk '
    BEGIN { blank_count = 0 }
    /^[[:space:]]*$/ {
        blank_count++
        if (blank_count <= 1) print
        next
    }
    {
        blank_count = 0
        print
    }
    '
}

# 메인 정리 함수
clean_note() {
    local file="$1"
    local dry_run="${2:-false}"
    local backup="${3:-false}"
    local verbose="${4:-false}"

    # 파일 존재 확인
    if [[ ! -f "$file" ]]; then
        log_error "파일을 찾을 수 없습니다: $file"
        exit 1
    fi

    log_info "파일 분석 중: $file"

    # 원본 내용 읽기
    local original_lines
    original_lines=$(wc -l < "$file" | tr -d ' ')

    # 임시 파일 생성
    local tmpfile
    tmpfile=$(mktemp)

    # 정리 작업 수행
    cat "$file" | \
        # 1. Gemini cite 패턴 제거: [cite: 4], [cite: 1-5], [cite: 1, 2, 3]
        sed -E 's/\[cite:[[:space:]]*[0-9, -]+\]//g' | \
        # 2. Gemini cite_start 태그 제거: [cite_start]
        sed 's/\[cite_start\]//g' | \
        # 3. 코드 블록 앞 언어 라벨 제거 (별도 줄): Bash, JSON, YAML, Plaintext 등
        sed -E '/^[[:space:]]*(Bash|JSON|YAML|Plaintext|Python|Shell|JavaScript|TypeScript|HTML|CSS|SQL|XML|Go|Rust|Java|C\+\+|Ruby|PHP|Perl)[[:space:]]*$/d' | \
        # 4. 마침표 앞 불필요한 숫자 제거: "합니다123." → "합니다."
        sed -E 's/([가-힣])[0-9]+\./\1./g' | \
        # 5. 괄호+공백 뒤 숫자+마침표: ") 123." → ")"
        sed -E 's/\)[[:space:]]*[0-9]+\./)./g' | \
        # 6. 줄 끝 공백+숫자 제거: "내용 123" → "내용"
        sed -E 's/[[:space:]]+[0-9]+[[:space:]]*$//' | \
        # 7. 줄 끝 숫자만 (4자리 이상): "내용1234" → "내용"
        sed -E 's/[0-9]{4,}[[:space:]]*$//' | \
        # 8. <br> 태그 제거
        sed 's/<br[[:space:]]*\/*>//gi' | \
        # 9. +숫자 라인 제거
        sed '/^[[:space:]]*+[0-9][0-9]*[[:space:]]*$/d' | \
        # 10. 줄 끝 공백 제거
        sed 's/[[:space:]]*$//' | \
        # 11. 연속 빈 줄 정리 (2줄 이상 → 1줄)
        squeeze_blank_lines > "$tmpfile"

    # 결과 라인 수
    local final_lines
    final_lines=$(wc -l < "$tmpfile" | tr -d ' ')
    local removed_lines=$((original_lines - final_lines))

    # 통계 출력
    echo ""
    echo "======================================"
    echo "        정리 결과 요약"
    echo "======================================"
    printf "%-20s %s → %s (%s줄 감소)\n" "라인 수:" "$original_lines" "$final_lines" "$removed_lines"
    echo "======================================"
    echo ""

    # dry-run 모드
    if [[ "$dry_run" == "true" ]]; then
        log_warn "Dry-run 모드: 실제 파일은 수정되지 않았습니다."
        if [[ "$verbose" == "true" ]]; then
            echo ""
            echo "=== 변경된 내용 미리보기 (처음 50줄) ==="
            head -50 "$tmpfile"
        fi
        rm -f "$tmpfile"
        return 0
    fi

    # 백업
    if [[ "$backup" == "true" ]]; then
        local backup_file="${file}.bak"
        cp "$file" "$backup_file"
        log_info "백업 생성: $backup_file"
    fi

    # 파일 저장
    mv "$tmpfile" "$file"
    log_success "정리 완료: $file"
}

# 인자 파싱
main() {
    local file=""
    local dry_run=false
    local backup=false
    local verbose=false

    # 인자가 없으면 사용법 출력
    [[ $# -eq 0 ]] && usage

    # 인자 파싱
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -h|--help)
                usage
                ;;
            --dry-run)
                dry_run=true
                shift
                ;;
            --backup)
                backup=true
                shift
                ;;
            --verbose)
                verbose=true
                shift
                ;;
            -*)
                log_error "알 수 없는 옵션: $1"
                exit 1
                ;;
            *)
                if [[ -z "$file" ]]; then
                    file="$1"
                else
                    log_error "파일은 하나만 지정할 수 있습니다."
                    exit 1
                fi
                shift
                ;;
        esac
    done

    # 파일 인자 확인
    if [[ -z "$file" ]]; then
        log_error "파일 경로를 지정해주세요."
        exit 1
    fi

    # 정리 실행
    clean_note "$file" "$dry_run" "$backup" "$verbose"
}

main "$@"
