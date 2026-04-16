"""
파이프라인 단위 테스트 — 실제 영상 없이 합성 SRT로 각 단계를 검증합니다.

실행:
    python test_pipeline.py
    python test_pipeline.py --with-translation   # DeepL 실제 호출 포함
"""

import argparse
import sys
from pathlib import Path

# UTF-8 출력 강제 (Windows cp949 환경 대응)
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

# ── ANSI 색상 ────────────────────────────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def passed(label: str, detail: str = "") -> None:
    suffix = f"  {detail}" if detail else ""
    print(f"  {GREEN}PASS{RESET}  {label}{suffix}")


def failed(label: str, detail: str = "") -> None:
    suffix = f"  {detail}" if detail else ""
    print(f"  {RED}FAIL{RESET}  {label}{suffix}")


def warn(label: str, detail: str = "") -> None:
    suffix = f"  {detail}" if detail else ""
    print(f"  {YELLOW}WARN{RESET}  {label}{suffix}")


# ── 합성 SRT 샘플 ─────────────────────────────────────────────────────────────
# 1글자 병합 테스트용 (블록 1은 '。' 1글자 → 블록 2와 병합 기대)
SAMPLE_MERGE_SINGLE = """\
1
00:00:01,000 --> 00:00:02,000
。

2
00:00:02,000 --> 00:00:04,000
お前のことが好きだ♡

3
00:00:05,000 --> 00:00:07,000
気持ちいい

"""

# 중복 자막 병합 테스트용
SAMPLE_MERGE_DUP = """\
1
00:00:01,000 --> 00:00:02,000
あああ

2
00:00:02,000 --> 00:00:03,500
あああ

3
00:00:04,000 --> 00:00:05,000
違う

"""

# 반복 패턴 환각 테스트용
SAMPLE_HALLUCINATION = """\
1
00:00:01,000 --> 00:00:03,000
あああああああああ気持ちいい

2
00:00:04,000 --> 00:00:06,000
正常なテキスト

"""

# 번역 테스트용 (실제 DeepL/LLM 호출)
SAMPLE_TRANSLATE = """\
1
00:00:01,000 --> 00:00:03,000
気持ちいい

2
00:00:04,000 --> 00:00:06,000
もっとして♡

3
00:00:07,000 --> 00:00:09,000
イキそう

"""

results: list[bool] = []


def _assert(condition: bool, label: str, detail: str = "") -> None:
    if condition:
        passed(label, detail)
    else:
        failed(label, detail)
    results.append(condition)


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: merge_single_char_captions
# ─────────────────────────────────────────────────────────────────────────────
def test_merge_single():
    print("\n[Test 1] merge_single_char_captions — 1글자 블록 병합")
    from srt_processor import merge_single_char_captions, _parse_srt_blocks

    result = merge_single_char_captions(SAMPLE_MERGE_SINGLE)
    blocks = _parse_srt_blocks(result)

    # 블록 1(1글자)이 블록 2와 병합되어 2블록이 되어야 함
    _assert(len(blocks) == 2, "1글자 블록이 다음 블록과 병합됨", f"블록 수: {len(blocks)} (기대: 2)")
    # 병합된 블록에 두 텍스트가 모두 포함되어야 함
    merged_text = " ".join(blocks[0][2:])
    _assert("好きだ" in merged_text, "병합 후 원래 텍스트 보존", f"병합 텍스트: {merged_text!r}")
    # 타임스탬프: 시작은 블록1, 종료는 블록2 기준
    ts = blocks[0][1]
    _assert("00:00:01,000" in ts and "00:00:04,000" in ts, "타임스탬프 확장됨", f"타임스탬프: {ts}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: merge_identical_captions
# ─────────────────────────────────────────────────────────────────────────────
def test_merge_identical():
    print("\n[Test 2] merge_identical_captions — 연속 동일 자막 병합")
    from srt_processor import merge_identical_captions, _parse_srt_blocks

    result = merge_identical_captions(SAMPLE_MERGE_DUP)
    blocks = _parse_srt_blocks(result)

    # 'あああ' 2개가 1개로 병합되어 총 2블록이 되어야 함
    _assert(len(blocks) == 2, "동일 자막 병합 후 블록 수 감소", f"블록 수: {len(blocks)} (기대: 2)")
    # 병합된 블록의 종료 시간 = 두 번째 블록의 종료 시간
    ts = blocks[0][1]
    _assert("00:00:03,500" in ts, "종료 타임스탬프가 마지막 블록 기준", f"타임스탬프: {ts}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: remove_repeated_patterns
# ─────────────────────────────────────────────────────────────────────────────
def test_hallucination_repeat():
    print("\n[Test 3] remove_repeated_patterns — 반복 패턴 제거")
    from hallucination import remove_repeated_patterns

    cases = [
        ("あああああああ気持ちいい", "気持ちいい", "5회+ 동일 문자 반복 제거"),
        ("お前にお前にお前に好きだ", "お前に好きだ", "다중문자 반복 제거"),
        ("正常なテキスト", "正常なテキスト", "정상 텍스트 보존"),
    ]
    for text, expected_contains, label in cases:
        result = remove_repeated_patterns(text)
        ok = expected_contains in result
        _assert(ok, label, f"입력: {text!r} → 출력: {result!r}")


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: remove_english_line
# ─────────────────────────────────────────────────────────────────────────────
def test_hallucination_english():
    print("\n[Test 4] remove_english_line — 영문 줄 제거")
    from hallucination import remove_english_line

    cases = [
        ("Translation: This is english only", "", "영문 전용 줄 제거"),
        ("こんにちは", "こんにちは", "일본어 보존"),
        ("안녕하세요", "안녕하세요", "한국어 보존"),
    ]
    for text, expected, label in cases:
        result = remove_english_line(text)
        ok = expected in result
        _assert(ok, label, f"입력: {text!r} → 출력: {result!r}")



# ─────────────────────────────────────────────────────────────────────────────
# Test 6: translate_ja_to_ko (--with-translation 옵션 시)
# ─────────────────────────────────────────────────────────────────────────────
def test_translation():
    print("\n[Test 6] translate_ja_to_ko — 실제 번역 (DeepL 호출)")
    try:
        import config
        config.initialize()
    except SystemExit:
        _assert(False, "config.initialize()", "DeepL 초기화 실패 (.env 확인)")
        return

    from translator import translate_ja_to_ko

    cases = [
        ("気持ちいい", "기분", "단순 감정 번역"),
        ("もっとして♡", None, "이모티콘 포함 번역 (출력만 확인)"),
        ("", "", "빈 문자열 처리"),
    ]
    for text, expected_contains, label in cases:
        try:
            result = translate_ja_to_ko(text)
            if expected_contains is None:
                _assert(bool(result) or text == "", label, f"→ {result!r}")
            elif expected_contains == "":
                _assert(result == "", label, f"→ {result!r}")
            else:
                _assert(expected_contains in result, label, f"→ {result!r}")
        except Exception as e:
            _assert(False, label, str(e))


# ─────────────────────────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="파이프라인 단위 테스트")
    parser.add_argument(
        "--with-translation",
        action="store_true",
        help="DeepL 실제 호출 테스트 포함 (API 키 필요, 문자 소비)",
    )
    args = parser.parse_args()

    print("=" * 55)
    print("  srt-ja-ko-translator 파이프라인 단위 테스트")
    print("=" * 55)

    test_merge_single()
    test_merge_identical()
    test_hallucination_repeat()
    test_hallucination_english()
    if args.with_translation:
        test_translation()
    else:
        print("\n[Test 6] translate_ja_to_ko — 스킵 (--with-translation 옵션으로 실행)")

    # 결과 요약
    passed_count = sum(results)
    total_count = len(results)
    print("\n" + "=" * 55)
    if passed_count == total_count:
        print(f"  {GREEN}모든 테스트 통과: {passed_count}/{total_count}{RESET}")
    else:
        print(f"  {RED}실패: {total_count - passed_count}개 / 전체 {total_count}개{RESET}")
    print("=" * 55 + "\n")
    sys.exit(0 if passed_count == total_count else 1)
