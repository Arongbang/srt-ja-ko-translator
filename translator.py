import deepl

from config import translator, LOCAL_LLM_CLIENT, LOCAL_MODEL_NAME
from hallucination import clean_hallucination


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

    try:
        result = translator.translate_text(
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
        return result.text.strip()

    except deepl.DeepLException:
        return _translate_with_local_llm(text)


def _translate_with_local_llm(text: str) -> str:
    """로컬 LLM(LM Studio)으로 번역합니다. DeepL 폴백용."""
    try:
        response = LOCAL_LLM_CLIENT.chat.completions.create(
            model=LOCAL_MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "너는 일본어 AV 자막을 한국어로 번역하는 전문 번역가야.\n"
                        "원문의 느낌을 최대한 살려서 자연스럽고 직설적인 한국어로 번역해.\n"
                        "기본은 구어체의 캐주얼 반말이지만, 부드러운 대화나 감정 표현 시 구어체의 존댓말인 '-요' 체를 자연스럽게 번역 해.\n"
                        "흥분되거나 애교스러운 부분은 ♡ 같은 이모티콘을 적절히 넣어.\n"
                        "야한 표현은 한국어 사용자에게 자연스럽게 들리도록 해.\n"
                        "번역만 출력하고 다른 설명은 넣지 마."
                    ),
                },
                {
                    "role": "user",
                    "content": f"다음 일본어 자막을 한국어로 번역해:\n\n{text}",
                },
            ],
            temperature=0.7,
            max_tokens=512,
            top_p=0.9,
        )
        translated = response.choices[0].message.content.strip()
        return clean_hallucination(translated)

    except Exception as e:
        print(f"로컬 LLM 번역도 실패: {e}")
        return f"[번역 실패 - DeepL & 로컬 모두 오류] {text}"
