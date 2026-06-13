import sys
import os
import deepl
from dotenv import load_dotenv

load_dotenv()

deepl_translator: deepl.Translator | None = None
usage = None
used = 0
limit = 0
remaining = 0

# 디버깅 / 실행 모드 플래그 (srt_merge_and_translate.py 에서 설정)
debug: bool = False
dry_run: bool = False
skip_hallucination: bool = False


def initialize() -> None:
    global deepl_translator, usage, used, limit, remaining

    DEEPL_API_KEY = os.getenv("DEEPL_API_KEY")
    if not DEEPL_API_KEY:
        print("오류: .env 파일에 DEEPL_API_KEY가 설정되어 있지 않습니다.")
        print("예시 .env 내용:")
        print('DEEPL_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx:fx')
        sys.exit(1)

    try:
        deepl_translator = deepl.Translator(DEEPL_API_KEY, server_url="https://api-free.deepl.com")
        print("DeepL 초기화 성공")
    except Exception as e:
        print(f"DeepL 초기화 실패: {e}")
        sys.exit(1)

    usage = deepl_translator.get_usage()
    used = usage.character.count
    limit = usage.character.limit
    remaining = limit - used


def refresh_usage() -> None:
    global usage, used, limit, remaining
    usage = deepl_translator.get_usage()
    used = usage.character.count
    limit = usage.character.limit
    remaining = limit - used
