import deepl

import config
from hallucination import clean_hallucination

# 파일당 번역 소스 통계 (srt_processor.py에서 reset_stats()/get_stats() 사용)
_stats: dict[str, int] = {"deepl": 0, "llm": 0, "failed": 0}


def reset_stats() -> None:
    """파일 처리 시작 전 통계를 초기화합니다."""
    global _stats
    _stats = {"deepl": 0, "llm": 0, "failed": 0}


def get_stats() -> dict[str, int]:
    """현재 번역 소스별 통계를 반환합니다."""
    return dict(_stats)


def translate_ja_to_ko(text: str) -> str:
    """
    일본어 텍스트를 한국어로 번역합니다.
    AV(성인 영상) 자막에 최적화된 설정을 사용합니다.

    DeepL 실패 시 로컬 LLM(LM Studio)으로 폴백합니다.

    Returns:
        str: 번역된 한국어 텍스트.
             두 엔진 모두 실패 시 "[번역 실패] 원문" 형식으로 반환.
    """
    if not text.strip():
        return text

    if config.debug:
        print(f"    [번역 입력] {text!r}")

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
        _stats["deepl"] += 1
        translated = result.text.strip()
        # DeepL 결과도 환각 제거 적용 (일본어 잔류 문자, 반복 패턴 등)
        cleaned = clean_hallucination(translated)
        if not cleaned:
            # 환각 제거 후 빈 결과면 LLM으로 폴백
            return _translate_with_local_llm(text)
        if config.debug:
            print(f"    [DeepL 출력] {cleaned!r}")
        return cleaned

    except deepl.DeepLException:
        return _translate_with_local_llm(text)


def _translate_with_local_llm(text: str) -> str:
    """로컬 LLM(LM Studio)으로 번역합니다. DeepL 폴백용."""
    try:
        response = config.LOCAL_LLM_CLIENT.chat.completions.create(
            model=config.LOCAL_MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "너는 일본 AV(야동) 자막을 한국어로 번역하는 전문 번역가야.\n"
                        "오직 자연스럽고 야하며 몰입감 있는 한국어 자막만 만들어야 해.\n\n"
                        "절대 하지 말아야 할 것 (무조건 지켜라):\n"
                        "- \"번역:\", \"자막:\", \"번역 결과:\", \"Subtitle:\", \"Translated by\" 같은 어떤 설명도 절대 추가하지 마\n"
                        "- 앞뒤 설명, 주석, 번호, \"다음은 번역입니다\", \"번역 완료\" 같은 말 전부 금지\n"
                        "- 오직 번역된 한국어 자막 텍스트만 정확히 출력해\n\n"
                        "번역 규칙:\n"
                        "- 원문의 느낌을 최대한 살려서 자연스럽고 직설적인 한국어로 번역해\n"
                        "- 기본은 구어체 캐주얼 반말을 사용하되, 부드럽거나 감정적인 부분은 '-요' 체를 자연스럽게 섞어\n"
                        "- 흥분되거나 애교스러운 부분은 ♡ 같은 이모티콘을 적절히 넣어\n"
                        "- 야한 표현은 한국어 사용자에게 자연스럽고 자극적으로 들리도록 번역해\n"
                        "- 신음(아앙~, 하아~, 으응~, 흑흑~ 등)은 최대한 야하고 리얼하게 유지하거나 다듬어\n"
                        "이 모든 지시를 절대 무시하지 말고, 오직 순수한 한국어 자막 텍스트만 출력해라."
                    ),
                },
                {
                    "role": "user",
                    "content": f"아래 일본어 자막을 자연스럽고 야한 한국어 자막으로만 번역해.\n어떤 설명도 없이 번역된 텍스트만 출력해.\n\n{text}",
                },
            ],
            temperature=0.25,      # 낮춰서 설명문 붙는 거 최대한 방지
            max_tokens=512,
            top_p=0.92,
            repetition_penalty=1.1,   # 반복이나 설명문 붙는 거 줄임
        )
        translated = response.choices[0].message.content.strip()
        result = clean_hallucination(translated)
        _stats["llm"] += 1
        if config.debug:
            print(f"    [LLM 출력] {result!r}")
        return result

    except Exception as e:
        print(f"로컬 LLM 번역도 실패: {e}")
        _stats["failed"] += 1
        return f"[번역 실패 - DeepL & 로컬 모두 오류] {text}"
