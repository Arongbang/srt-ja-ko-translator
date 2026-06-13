import deepl

import config
from hallucination import clean_hallucination

# 파일당 번역 소스 통계 (srt_processor.py에서 reset_stats()/get_stats() 사용)
_stats: dict[str, int] = {"deepl": 0, "failed": 0}


def reset_stats() -> None:
    """파일 처리 시작 전 통계를 초기화합니다."""
    global _stats
    _stats = {"deepl": 0, "failed": 0}


def get_stats() -> dict[str, int]:
    """현재 번역 소스별 통계를 반환합니다."""
    return dict(_stats)


def translate_ja_to_ko(text: str) -> str:
    """
    일본어 텍스트를 한국어로 번역합니다.
    AV(성인 영상) 자막에 최적화된 설정을 사용합니다.

    DeepL 실패 또는 환각 제거 후 빈 결과 시 최대 2회 재시도합니다.

    Returns:
        str: 번역된 한국어 텍스트.
             모든 재시도 실패 시 "[번역 실패] 원문" 형식으로 반환.
    """
    if not text.strip():
        return text

    if config.debug:
        print(f"    [번역 입력] {text!r}")

    for attempt in range(1, 3):
        try:
            result = config.deepl_translator.translate_text(
                text,
                source_lang="JA",
                target_lang="KO",
                formality="prefer_less",
                model_type="quality_optimized",
                context=(
                    "너는 일본어 AV 자막을 한국어로 번역하는 전문 번역가야. "
                    "기본적으로 구어체의 캐주얼한 반말을 사용하지만, 존댓말을 사용할 때는 -요 체의 부드러운 구어체의 존댓말을 자연스럽게 번역해주세요. "
                    "♡ 같은 이모티콘을 분위기에 맞춰 적절히 추가하여 분위기를 살려주세요."
                ),
                preserve_formatting=True,
                split_sentences="1",
            )
            cleaned = clean_hallucination(result.text.strip())
            if cleaned:
                _stats["deepl"] += 1
                if config.debug:
                    print(f"    [DeepL 출력] {cleaned!r}")
                return cleaned
            # 환각 제거 후 빈 결과 → 재시도
        except deepl.DeepLException:
            pass  # 재시도

    _stats["failed"] += 1
    return f"[번역 실패] {text}"
