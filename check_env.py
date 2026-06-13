"""
환경 진단 스크립트 — 번역 파이프라인 실행 전 의존성을 점검합니다.

실행:
    python check_env.py
"""

import importlib
import os
import sys
from pathlib import Path

# UTF-8 출력 강제 (Windows cp949 환경 대응)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# ── ANSI 색상 헬퍼 ────────────────────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"
OK = f"{GREEN}[OK]{RESET}"
FAIL = f"{RED}[NG]{RESET}"
WARN = f"{YELLOW}[!!]{RESET}"


def check(label: str, ok: bool, detail: str = "") -> bool:
    status = OK if ok else FAIL
    suffix = f"  {detail}" if detail else ""
    print(f"  {status}  {label}{suffix}")
    return ok


# ── 1. Python 버전 ───────────────────────────────────────────────────────────
print("\n[1] Python 버전")
py_ok = sys.version_info >= (3, 7)
check(f"Python {sys.version.split()[0]}", py_ok, "" if py_ok else "(3.7 이상 필요)")

# ── 2. 필수 패키지 ───────────────────────────────────────────────────────────
print("\n[2] 필수 패키지")
REQUIRED = ["deepl", "dotenv", "regex"]
OPTIONAL = ["faster_whisper"]

all_required_ok = True
for pkg in REQUIRED:
    try:
        mod = importlib.import_module(pkg)
        ver = getattr(mod, "__version__", "?")
        check(pkg, True, f"v{ver}")
    except ImportError:
        check(pkg, False, "미설치 — pip install " + pkg)
        all_required_ok = False

for pkg in OPTIONAL:
    try:
        mod = importlib.import_module(pkg)
        ver = getattr(mod, "__version__", "?")
        check(f"{pkg} (선택)", True, f"v{ver} — Whisper 자막 추출 가능")
    except ImportError:
        print(f"  {WARN}  {pkg} (선택)  미설치 — 영상→SRT 추출 불가 (번역만 할 경우 무관)")

# ── 3. .env / DEEPL_API_KEY ──────────────────────────────────────────────────
print("\n[3] DeepL API")
env_path = Path(__file__).parent / ".env"
check(".env 파일 존재", env_path.exists(), str(env_path) if not env_path.exists() else "")

try:
    from dotenv import load_dotenv
    load_dotenv(env_path)
    api_key = os.getenv("DEEPL_API_KEY", "")
    key_ok = bool(api_key)
    check("DEEPL_API_KEY 설정됨", key_ok, "(값 숨김)" if key_ok else ".env에 DEEPL_API_KEY 추가 필요")

    if key_ok:
        try:
            import deepl
            translator = deepl.Translator(api_key, server_url="https://api-free.deepl.com")
            usage = translator.get_usage()
            used = usage.character.count
            limit = usage.character.limit
            remaining = limit - used
            check(
                "DeepL API 응답",
                True,
                f"사용: {used:,} / {limit:,} 자  (남음: {remaining:,} 자)",
            )
            if remaining == 0:
                print(f"  {WARN}  DeepL 잔여 한도 0 — 번역 실패 가능")
        except Exception as e:
            check("DeepL API 응답", False, str(e))
except Exception as e:
    check("dotenv 로드", False, str(e))

# ── 요약 ──────────────────────────────────────────────────────────────────────
print("\n" + "=" * 50)
if all_required_ok:
    print(f"{OK} 필수 패키지 모두 설치됨 -- 파이프라인 실행 가능")
else:
    print(f"{FAIL} 필수 패키지 누락 -- 위 항목을 먼저 설치하세요")
print("=" * 50 + "\n")
