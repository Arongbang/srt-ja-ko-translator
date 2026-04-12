# CLAUDE.md

이 파일은 Claude Code(claude.ai/code)가 이 저장소의 코드를 작업할 때 참고할 가이드를 제공합니다.

## 프로젝트 개요

**srt-ja-ko-translator**는 일본어 SRT 자막 파일을 한국어로 자동 번역하는 Python 유틸리티입니다. 이 도구는 다음을 결합합니다:
- **DeepL API** (주 번역 엔진, 성인 영상 자막 컨텍스트 최적화)
- **로컬 LLM 폴백** (DeepL 실패 시 복원력을 위해 LM Studio 사용)
- **LLM 구어체 변환** (번역 후 LM Studio로 자연스러운 구어체 자막으로 2nd pass 변환)
- **후처리 파이프라인** (환각 제거, 프롬프트 누출 방어)

## 핵심 아키텍처

### 데이터 파이프라인 (논리적 순서)
```
탐색 → 파싱 → 전처리 → 번역 → 구어체 변환 → 출력
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

5. **구어체 변환 단계** (`colloquial.py`, `srt_processor.py::_apply_colloquial_to_srt`)
   - DeepL 번역 직후 `.ko.srt.bak`에 원문 번역본 저장 (복원 용도)
   - LM Studio로 블록별 구어체 변환 2nd pass 수행
   - `_is_prompt_leak()`으로 LLM 출력이 지시문 형태일 경우 원본 반환
   - LM Studio 미실행 시 원본 번역 그대로 출력 (silent fallback)

6. **출력 단계** (`srt_processor.py`)
   - 구어체 변환된 SRT를 `.ko.srt`로 저장 (예: `file.srt` → `file.ko.srt`)

### 모듈 책임

| 모듈 | 책임 | 주요 함수 |
|------|------|----------|
| `srt_merge_and_translate.py` | 오케스트레이션, CLI 인수 파싱, 진행률 추적 | `main()` |
| `srt_processor.py` | SRT 포맷 파싱/재구축, 블록 병합, 구어체 변환 적용 | `get_srt_files()`, `_parse_srt_blocks()`, `_rebuild_srt()`, `_apply_colloquial_to_srt()`, `process_srt_file()` |
| `translator.py` | DeepL + LLM 폴백 번역 | `translate_ja_to_ko()`, `_translate_with_local_llm()` |
| `colloquial.py` | LLM 구어체 변환 2nd pass, 프롬프트 누출 방어 | `make_colloquial()`, `_is_prompt_leak()` |
| `config.py` | 번역 엔진 전역 초기화 | `initialize()`, `refresh_usage()` |
| `hallucination.py` | 환각 제거 휴리스틱 | `remove_repeated_patterns()`, `remove_english_line()`, `clean_hallucination()` |

### 중요 컨텍스트

- **SRT 포맷**: 인덱스(1번 줄), 타임스탬프(2번 줄), 텍스트(3번 줄 이상), 빈 줄 구분자
- **백업 전략**: 원본 `.srt` 수정 전 `.srt.bak` 생성; DeepL 번역 직후 `.ko.srt.bak` 저장 (구어체 변환 전 원문 보존); 이후 `.ko.srt`에 구어체 변환 결과 덮어씀
- **오류 복원력**: DeepL 실패 시 조용히 로컬 LLM으로 폴백; 구어체 변환 실패 또는 프롬프트 누출 감지 시 원본 번역 반환
- **DeepL 컨텍스트**: API가 캐주얼 일본어, 존댓말, AV 자막 도메인의 이모티콘 배치(♡) 처리 명시적으로 지시
- **환각 패턴**: 다단계 감지 (문자 반복 → 다중 문자 패턴 → 문장 수준 반복)
- **프롬프트 누출**: LLM이 지시문을 출력하는 hallucination을 `_is_prompt_leak()`으로 감지, 원본 반환

## 개발 환경 설정

### 필수 요구사항
- Python 3.7 이상
- DeepL 무료 API 계정 (월 10,000자 무료 한도)
- LM Studio가 http://127.0.0.1:1234에서 `ja-ko-vn-12b-v2` 모델과 함께 실행 중

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
# 단일 폴더 (영상 추출 + 번역 + 구어체 변환)
python srt_merge_and_translate.py "C:/Subtitles"

# SRT 파일만 번역 (영상 추출 건너뜀)
python srt_merge_and_translate.py "C:/Subtitles" --skip-transcribe
```

## 코드 패턴 및 컨벤션

### 전역 상태 (config.py)
- 번역 엔진은 `config.initialize()`에서 한 번만 초기화되고 모듈 수준 전역 변수로 저장됨
- `refresh_usage()`는 주기적으로 호출되어 DeepL 할당량 추적 업데이트
- 로컬 LLM 클라이언트는 OpenAI 호환 (LM Studio 경유)

### 정규식 모듈
- `re` 모듈: 표준 작업 (패턴 매칭, 프롬프트 누출 감지)

### 파일 인코딩
- 모든 SRT 파일은 UTF-8-SIG 인코딩 사용 (BOM 있을 경우 보존)
- 경로 처리는 `pathlib.Path` 사용 (크로스 플랫폼)

## 일반적인 개발 작업

### 새로운 번역 후처리 단계 추가
1. `hallucination.py`에 `clean_hallucination(text: str) -> str` 서명을 따르는 함수 추가
2. `srt_processor.py::process_srt_file()`에서 번역 후 호출
3. 알려진 환각 패턴을 포함한 샘플 `.srt` 파일로 테스트

### 구어체 변환 프롬프트 수정
- `colloquial.py`의 `SYSTEM_PROMPT` 편집
- "너는 X야" 패턴은 LLM이 그대로 출력하는 hallucination을 유발하므로 직접 지시형 유지
- 새로운 누출 패턴 발견 시 `_LEAK_PATTERNS` 리스트에 정규식 추가

### 번역 문제 디버깅
1. DeepL API 할당량 확인: `config.refresh_usage()`는 사용된/제한 문자 출력
2. 로컬 LLM 실행 확인: `curl http://127.0.0.1:1234/v1/models`는 사용 가능한 모델 반환해야 함
3. `translator.py`의 DeepL/LLM 호출 주변에 print 문 활성화하여 폴백 동작 추적

### DeepL 번역 컨텍스트 수정
- `translator.py::translate_ja_to_ko()`의 `context=` 파라미터 편집 (API 동작 지시)
- 또는 LLM 폴백 지시를 위해 `_translate_with_local_llm()`의 시스템 프롬프트

## 테스트 접근 방식

현재 자동화된 테스트 없음. 수동 검증의 경우:
- 최소 테스트 `.srt` 생성 (5-10개 자막 블록)
- 각 단계 확인: 병합, 번역, 구어체 변환
- `.ko.srt.bak`(DeepL 원문)과 `.ko.srt`(구어체 변환) 비교로 변환 품질 검증
- `grep "한국어 자막\|구어체로 변환\|전문가" output.ko.srt`로 프롬프트 누출 여부 확인

## 알려진 제한사항 및 향후 작업

- 비동기/병렬 처리 없음 (순차적 파일별, 블록별)
- 드라이런 모드 없음 (항상 백업 생성 및 파일 수정)
- 환각 감지는 휴리스틱 기반 (엣지 케이스 놓칠 수 있음)
- 내장 진행 상황 지속성 없음 (프로세스 중단 시 전체 폴더 재실행 필요)

## 성능 참고사항

- **병목**: DeepL API 지연 시간 (일반적으로 블록당 1-2초) + LM Studio 구어체 변환 (블록당 약 3-5초)
- **메모리**: 한 번에 단일 자막 블록 메모리 보유 (효율적)
- **DeepL 할당량**: `config.refresh_usage()` 후 `config.remaining`으로 사용량 모니터링

## 참고자료

- [DeepL API 문서](https://www.deepl.com/docs-api) — context 파라미터, formality, model_type
- [LM Studio](https://lmstudio.ai) — 로컬 LLM 서버 (OpenAI 호환)
- SRT 포맷: 인덱스, 타임스탬프, 텍스트, 빈 줄 (표준 자막 포맷)
