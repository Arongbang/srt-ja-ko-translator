# CLAUDE.md

이 파일은 Claude Code(claude.ai/code)가 이 저장소의 코드를 작업할 때 참고할 가이드를 제공합니다.

## 프로젝트 개요

**srt-ja-ko-translator**는 일본어 SRT 자막 파일을 한국어로 자동 번역하는 Python 유틸리티입니다. 이 도구는 다음을 결합합니다:
- **DeepL API** (주 번역 엔진, 성인 영상 자막 컨텍스트 최적화)
- **로컬 LLM 폴백** (DeepL 실패 시 복원력을 위해 LM Studio 사용)
- **후처리 파이프라인** (환각 제거, 패턴 기반 치환)

## 핵심 아키텍처

### 데이터 파이프라인 (논리적 순서)
```
탐색 → 파싱 → 전처리 → 번역 → 후처리 → 출력
```

1. **탐색 단계** (`srt_processor.py::get_srt_files`)
   - 주어진 디렉토리에서 `.srt` 파일을 재귀적으로 탐색
   - 이미 번역된 `.ko.srt` 파일은 제외하여 중복 처리 방지

2. **파싱 단계** (`srt_processor.py::_parse_srt_blocks`, `_rebuild_srt`)
   - SRT 블록(인덱스, 타임스탬프, 텍스트)을 엄격한 포맷 검증과 함께 파싱
   - 병합 후 블록을 재인덱싱하여 SRT 스펙 준수

3. **전처리 단계** (`srt_processor.py`)
   - 1글자 블록을 다음 블록과 병합 (일본어 자막에서 흔함)
   - 특정 일본어 휴식 패턴 제거 (예: "少し休...")
   - 수정 전 `.bak` 백업 파일 생성

4. **번역 단계** (`translator.py`)
   - DeepL을 "AV 자막 번역가" 컨텍스트와 함께 호출
   - DeepL 실패 시 LM Studio(http://127.0.0.1:1234)로 폴백
   - `quality_optimized` 모델을 사용하여 캐주얼 일본어-한국어 변환

5. **후처리 단계** (`hallucination.py`, `apply_replacements.py`)
   - 번역 환각 제거 (5개 이상 반복 문자, 다중 문자 반복, 3회 이상 문장 반복)
   - XML 템플릿(`multiple_replace_groups.template`)에서 SubtitleEdit 방식의 정규식 규칙 적용
   - 줄 구조 및 SRT 포맷 유지

6. **출력 단계** (`srt_processor.py`)
   - 번역된 SRT를 `.ko.srt`로 저장 (예: `file.srt` → `file.ko.srt`)
   - 재실행 시 `.ko.srt.bak` 생성

### 모듈 책임

| 모듈 | 책임 | 주요 함수 |
|------|------|----------|
| `srt_merge_and_translate.py` | 오케스트레이션, CLI 인수 파싱, 진행률 추적 | `main()` |
| `srt_processor.py` | SRT 포맷 파싱/재구축, 블록 병합 로직 | `get_srt_files()`, `_parse_srt_blocks()`, `_rebuild_srt()`, `process_srt_file()` |
| `translator.py` | DeepL + LLM 폴백 번역 | `translate_ja_to_ko()`, `_translate_with_local_llm()` |
| `config.py` | 번역 엔진 전역 초기화 | `initialize()`, `refresh_usage()` |
| `hallucination.py` | 환각 제거 휴리스틱 | `remove_repeated_patterns()`, `remove_english_line()`, `clean_hallucination()` |
| `apply_replacements.py` | XML 기반 치환 규칙 (SubtitleEdit 포맷) | `load_replace_rules()`, `apply_rules()`, `process_srt()` |

### 중요 컨텍스트

- **SRT 포맷**: 인덱스(1번 줄), 타임스탐프(2번 줄), 텍스트(3번 줄 이상), 빈 줄 구분자
- **백업 전략**: 번역 전 `.bak` 파일 생성; 재실행 시 `.ko.srt.bak` 생성 (이전 번역 덮어쓰기, 누적 안 함)
- **오류 복원력**: DeepL 실패 시 조용히 로컬 LLM으로 폴백; 번역 실패 시 "[번역 실패] 원문" 형식 반환
- **DeepL 컨텍스트**: API가 캐주얼 일본어, 존댓말, AV 자막 도메인의 이모티콘 배치(♡) 처리 명시적으로 지시
- **환각 패턴**: 다단계 감지 (문자 반복 → 다중 문자 패턴 → 문장 수준 반복)

## 개발 환경 설정

### 필수 요구사항
- Python 3.7 이상
- DeepL 무료 API 계정 (월 10,000자 무료 한도)
- LM Studio가 http://127.0.0.1:1234에서 `ja-ko-vn-7b-v1` 모델과 함께 실행 중

### 설치
```bash
pip install deepl python-dotenv openai regex
```

### 환경 설정
프로젝트 루트에 `.env` 파일 생성:
```
DEEPL_API_KEY=<your-api-key>:fx
```
(`:fx` 접미사는 무료 등급 DeepL API를 나타냅니다)

### 실행
```bash
# 단일 폴더
python srt_merge_and_translate.py "C:/Subtitles"

# 템플릿 규칙 포함 (선택 사항)
# 프로젝트 루트에 multiple_replace_groups.template이 있어야 함
```

## 코드 패턴 및 컨벤션

### 전역 상태 (config.py)
- 번역 엔진은 `config.initialize()`에서 한 번만 초기화되고 모듈 수준 전역 변수로 저장됨
- `refresh_usage()`는 주기적으로 호출되어 DeepL 할당량 추적 업데이트
- 로컬 LLM 클라이언트는 OpenAI 호환 (LM Studio 경유)

### 정규식 모듈
- `re` 모듈: 표준 작업 (패턴 매칭, 역참조 변환)
- `regex` 모듈: `apply_replacements.py`의 고급 기능 (복잡한 치환 규칙에 사용)

### 파일 인코딩
- 모든 SRT 파일은 UTF-8-SIG 인코딩 사용 (BOM 있을 경우 보존)
- 경로 처리는 `pathlib.Path` 사용 (크로스 플랫폼)

## 일반적인 개발 작업

### 새로운 번역 후처리 단계 추가
1. `hallucination.py`에 `clean_hallucination(text: str) -> str` 서명을 따르는 함수 추가
2. `srt_processor.py::process_srt_file()`에서 번역 후, 치환 규칙 전에 호출
3. 알려진 환각 패턴을 포함한 샘플 `.srt` 파일로 테스트

### 번역 문제 디버깅
1. DeepL API 할당량 확인: `config.refresh_usage()`는 사용된/제한 문자 출력
2. 로컬 LLM 실행 확인: `curl http://127.0.0.1:1234/v1/models`는 사용 가능한 모델 반환해야 함
3. `translator.py`의 DeepL/LLM 호출 주변에 print 문 활성화하여 폴백 동작 추적

### DeepL 번역 컨텍스트 수정
- `translator.py::translate_ja_to_ko()`의 `context=` 파라미터 편집 (API 동작 지시)
- 또는 LLM 폴백 지시를 위해 `_translate_with_local_llm()`의 시스템 프롬프트

### 치환 규칙으로 테스트
1. `multiple_replace_groups.template` 생성 (SubtitleEdit XML 내보내기 포맷)
2. 샘플 SRT 폴더로 실행; 템플릿이 있으면 규칙이 로드됨
3. `.ko.srt` 파일에서 출력 확인 (저장 전에 규칙 적용됨)

## 테스트 접근 방식

현재 자동화된 테스트 없음. 수동 검증의 경우:
- 최소 테스트 `.srt` 생성 (5-10개 자막 블록)
- 각 단계 확인: 병합, 번역, 환각 제거, 규칙 적용
- 출력 `.ko.srt`과 예상 한국어 텍스트 비교

## 알려진 제한사항 및 향후 작업

- 비동기/병렬 처리 없음 (순차적 파일별, 블록별)
- 드라이런 모드 없음 (항상 백업 생성 및 파일 수정)
- 환각 감지는 휴리스틱 기반 (엣지 케이스 놓칠 수 있음)
- 내장 진행 상황 지속성 없음 (프로세스 중단 시 전체 폴더 재실행 필요)

## 성능 참고사항

- **병목**: DeepL API 지연 시간 (일반적으로 블록당 1-2초) 및 로컬 LLM으로의 폴백
- **메모리**: 한 번에 단일 자막 블록 메모리 보유 (효율적)
- **DeepL 할당량**: `config.refresh_usage()` 후 `config.remaining`으로 사용량 모니터링

## 참고자료

- [DeepL API 문서](https://www.deepl.com/docs-api) — context 파라미터, formality, model_type
- [LM Studio](https://lmstudio.ai) — 로컬 LLM 서버 (OpenAI 호환)
- SRT 포맷: 인덱스, 타임스탬프, 텍스트, 빈 줄 (표준 자막 포맷)
