import re

# 일본어 음차 오류 교정 사전 (올바른 단어 → 잘못된 음차 변형 목록)
_PHONETIC_CORRECTIONS: dict[str, list[str]] = {
    '보지': ['맨크', '마크', '망고', '맨쿠', '마이크', '만코', '허벅지', '손주', '음부'],
    '자지': ['찐찐', '치즈', '꼬리', '신포', '찐포', '진키', '좆', '찐찐군', '오챠프',
             '진진', '전선', '낑낑', '팅팅', '버섯', '틴틴', '진저', '고추', '찐따', '첸첸'],
    '젖꼭지': ['치쿠미', '바이코', '치카리', '치크레', '치쿠비', '손목', '곰팡이',
               '징크스', '젖먹이', '치크베'],
    '정액': ['생사', '심문', '전사', '손자', '정신', '정지'],
}


def replace_japanese_phonetics(text: str) -> str:
    """일본어 음차로 잘못 변환된 단어를 올바른 한국어 속어로 교정.

    앞뒤에 한글이 이어지지 않는 경우에만 교체하여 다른 단어의 부분 일치를 방지한다.
    예: '마크가' → '보지가', '치쿠비를' → '젖꼭지를'
    """
    for correct, variants in _PHONETIC_CORRECTIONS.items():
        for variant in variants:
            pattern = rf'(?<![가-힣]){re.escape(variant)}(?![가-힣])'
            text = re.sub(pattern, correct, text)
    return text


def remove_repeated_patterns(text: str) -> str:
    """
    반복 패턴 환각 제거 (번역 전·후 모두 적용 가능)

    처리 순서:
    1. 동일 문자 5회 이상 연속 반복 → 해당 반복 구간만 제거
       ex) えへへへへへへへへへへへ気持ちいいんですか? → え気持ちいいんですか?
    2. 다중 문자 구문(2~15자) 2회 이상 연속 반복 → 첫 1회만 남김
       ex) お前にお前にお前にお前にお前に... → お前に
    3. 구두점 단위 구문이 3회 이상 반복 → 해당 구문 전부 제거
       ex) 気持つよくなろう。痛い。痛い。痛い。...  → 気持つよくなろう。
    """
    # 1. 단일 문자 5회 이상 연속 반복 제거
    text = re.sub(r'(.)\1{4,}', '', text)

    # 2. 다중 문자 구문(2~15자) 2회 이상 연속 반복 → 첫 1회만 남김
    text = re.sub(r'(.{2,15})\1+', r'\1', text)
    text = text.strip()
    if not text:
        return ''

    # 2. 구두점(。！？…、,，.) 단위로 구문 토큰화
    tokens = re.findall(r'[^。！？…、,，.]+[。！？…、,，.]*', text)
    tokens = [t for t in tokens if t.strip()]
    if not tokens:
        return ''

    # 각 구문의 등장 횟수 카운트
    counts: dict[str, int] = {}
    for t in tokens:
        key = t.strip()
        counts[key] = counts.get(key, 0) + 1

    # 3회 이상 반복된 구문이 있으면 해당 구문 모두 제거
    if any(v >= 3 for v in counts.values()):
        tokens = [t for t in tokens if counts[t.strip()] < 3]

    return ''.join(tokens).strip()


def remove_english_line(line: str) -> str:
    """영문자가 포함된 줄을 제거합니다."""
    return '' if re.search(r'[a-zA-Z]', line) else line


def clean_hallucination(text: str) -> str:
    """
    번역 결과에서 환각 텍스트를 제거합니다.

    처리 순서:
    1. 반복 패턴 제거 (단일 문자 5회+, 구문 3회+ 반복)
    2. 비한글 문자 제거 (허용 문자 외 전부)
    3. '자막'·'번역'·'영상' 포함 문장 제거
    4. 120글자 이상 줄 제거
    5. 영문자 포함 줄 제거
    6. 연속 공백·줄바꿈 정리

    참고: 일본어 음차 오류 교정은 replace_japanese_phonetics()에서 별도 처리.
    """
    text = remove_repeated_patterns(text)
    if not text:
        return ''

    # 한글 + 숫자 + 기본 구두점 + 자주 쓰이는 기호만 허용
    pattern_non_kor = r'[^\uAC00-\uD7A30-9\s~!@#$%^&*()_+\-=\[\]{}|\\;:\'",.<>/?`~♡♥!?…·\n]'
    cleaned = re.sub(pattern_non_kor, '', text)

    # '자막', '번역', '영상' 포함 문장 제거
    pattern_subtitle = r'[^.!?…]*?(자막|번역|영상)[^.!?…]*[.!?…]?[\s\n]*'
    cleaned = re.sub(pattern_subtitle, '', cleaned)

    # 연속 공백·줄바꿈 정리
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned
