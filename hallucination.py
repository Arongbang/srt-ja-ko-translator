import re


def remove_repeated_patterns(text: str) -> str:
    """
    반복 패턴 환각 제거 (번역 전·후 모두 적용 가능)

    처리 순서:
    1. 동일 문자 5회 이상 연속 반복 → 해당 반복 구간만 제거
       ex) えへへへへへへへへへへへ気持ちいいんですか? → え気持ちいいんですか?
    2. 구두점 단위 구문이 3회 이상 반복 → 해당 구문 전부 제거
       ex) 気持つよくなろう。痛い。痛い。痛い。...  → 気持つよくなろう。
    """
    # 1. 단일 문자 5회 이상 연속 반복 제거
    text = re.sub(r'(.)\1{4,}', '', text)
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
