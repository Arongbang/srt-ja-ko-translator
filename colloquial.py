"""구어체 변환 모듈 - 번역된 한국어를 자연스러운 구어체 자막으로 변환"""
import re
import config
from hallucination import clean_hallucination, replace_japanese_phonetics

# "너는 X야" 패턴 제거 → 직접 지시형으로 변경해 프롬프트 누출 위험 감소
SYSTEM_PROMPT = """한국어 자막 구어체 변환기.

입력된 한국어 문장의 스타일만 구어체로 바꿔서 출력해. 번역 금지.

변환 규칙:
~입니다/습니다 → ~요/이에요
~한다/이다 → ~해/야
~것이다 → ~거야
딱딱한 표현 → 일상 대화체

단어 교정 (일본어 음차 오류 수정):
맨크/마크/망고/맨쿠/만코/음부 → 보지
찐찐/찐포/낑낑/틴틴/찐따 → 자지
치쿠비/치쿠미/치크베 → 젖꼭지

주의:
- 변환된 문장만 출력 (설명, 접두어, 지시문 출력 금지)
- 원문의 감정과 뉘앙스 유지
- 여러 줄은 줄바꿈 유지"""

# LLM 출력이 지시문/프롬프트 성격인지 판별하는 패턴
_LEAK_PATTERNS = [
    r'한국어 자막.{0,10}(전문가|변환)',  # "한국어 자막 편집 전문가", "한국어 자막 변환"
    r'구어체로 변환',                      # "구어체로 변환해줘/해봐"
    r'번역하지 마',                        # 시스템 프롬프트 규칙 누출
    r'스타일만 바꿔',                      # 시스템 프롬프트 규칙 누출
    r'(입력|출력)\s*:',                    # "입력:", "출력:" 형식
    r'너는.{0,10}(전문가|편집|변환)',      # "너는 X 전문가야" 패턴
    r'규칙\s*:',                           # "규칙:" 섹션 헤더
]


def _is_prompt_leak(text: str) -> bool:
    """LLM 출력이 지시문/프롬프트 누출인지 감지한다."""
    for pattern in _LEAK_PATTERNS:
        if re.search(pattern, text):
            return True
    return False


def make_colloquial(text: str) -> str:
    """번역된 한국어를 구어체로 변환한다.

    LM Studio가 실행 중이지 않거나 오류 발생 시 원본 텍스트를 그대로 반환한다.
    프롬프트 누출이 감지된 경우에도 원본을 반환한다.
    """
    if not text or not text.strip():
        return text

    # 일본어 음차 오류 교정 (LM Studio 실행 여부와 무관하게 항상 적용)
    text = replace_japanese_phonetics(text)

    if config.LOCAL_LLM_CLIENT is None:
        return text  # LM Studio 미실행 시 교정된 텍스트 반환
    try:
        response = config.LOCAL_LLM_CLIENT.chat.completions.create(
            model=config.LOCAL_MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text.strip()},
            ],
            temperature=0.3,
            max_tokens=256,
            top_p=0.92,
            repetition_penalty=1.15,  # 반복 환각(자〜〜〜 등) 억제
        )
        result = response.choices[0].message.content.strip()
        if not result or _is_prompt_leak(result):
            return text  # 누출 감지 시 원본 반환
        # 구어체 변환 결과의 환각(반복 문자, 비한글 잔류 등) 제거
        cleaned = clean_hallucination(result)
        return cleaned if cleaned else text  # 환각 제거 후 빈 결과면 원본 반환
    except Exception:
        return text  # 오류 시 원본 반환 (silent fallback)
