import sys
import os
import deepl
from dotenv import load_dotenv
from openai import OpenAI

# .env 파일에서 환경변수 로드
load_dotenv()

# ── DeepL ────────────────────────────────────────────────────────

DEEPL_API_KEY = os.getenv("DEEPL_API_KEY")

if not DEEPL_API_KEY:
    print("오류: .env 파일에 DEEPL_API_KEY가 설정되어 있지 않습니다.")
    print("예시 .env 내용:")
    print('DEEPL_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx:fx')
    sys.exit(1)

try:
    translator = deepl.Translator(DEEPL_API_KEY, server_url="https://api-free.deepl.com")
    print("DeepL 초기화 성공")
except Exception as e:
    print(f"DeepL 초기화 실패: {e}")
    sys.exit(1)

usage = translator.get_usage()
used = usage.character.count
limit = usage.character.limit
remaining = limit - used

# ── 로컬 LLM (LM Studio) ─────────────────────────────────────────

LOCAL_LLM_CLIENT = OpenAI(
    base_url="http://127.0.0.1:1234/v1",
    api_key="lm-studio",
)

LOCAL_MODEL_NAME = "ja-ko-vn-7b-v1"
