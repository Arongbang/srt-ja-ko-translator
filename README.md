# srt-ja-ko-translator

일본어 `.srt` 자막 파일을 한국어로 자동 번역하는 Python 스크립트입니다.

## 구성 파일

| 파일 | 설명 |
|------|------|
| `srt_merge_and_translate.py` | 메인 실행 파일 |
| `srt_processor.py` | SRT 파일 읽기, 1글자 병합, 번역 처리 |
| `translator.py` | DeepL / 로컬 LLM 번역 엔진 |
| `hallucination.py` | 번역 환각(hallucination) 제거 |
| `config.py` | DeepL 및 로컬 LLM 초기화 설정 |

## 요구사항

```bash
pip install deepl python-dotenv openai
```

## 환경 설정

프로젝트 루트에 `.env` 파일을 생성하고 DeepL API 키를 입력합니다.

```
DEEPL_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx:fx
```

로컬 LLM 폴백은 [LM Studio](https://lmstudio.ai)를 사용하며, `http://127.0.0.1:1234`에서 실행 중이어야 합니다.

## 사용법

```bash
python srt_merge_and_translate.py "자막파일이_있는_폴더경로"
```

예시:

```bash
python srt_merge_and_translate.py "C:/Subtitles"
```

## 동작 방식

1. 지정한 폴더(및 하위 폴더)에서 `.srt` 파일을 탐색합니다. (이미 번역된 `.ko.srt`는 제외)
2. 각 파일의 원본을 `.bak`으로 백업합니다.
3. 공백 제외 1글자짜리 자막 블록을 다음 블록과 병합합니다.
4. DeepL API로 블록 단위 번역을 수행하고, 실패 시 로컬 LLM으로 폴백합니다.
5. 번역 결과를 `.ko.srt` 파일로 저장합니다.
