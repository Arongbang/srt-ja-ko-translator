import json
import re
import regex
from pathlib import Path


def _convert_backrefs(replace: str) -> str:
    """SubtitleEdit 방식의 역참조 ($1, $2) 를 Python 방식 (\\1, \\2) 으로 변환합니다."""
    return re.sub(r'\$(\d+)', lambda m: '\\' + m.group(1), replace)


def load_replace_rules(template_path: Path) -> list[tuple[str, str, bool]]:
    """
    SE_Replace_Rules.template (JSON) 에서 활성화된 치환 규칙을 읽어 반환합니다.
    반환값: [(find, replace, is_regex), ...]
    """
    with template_path.open(encoding="utf-8") as f:
        data = json.load(f)

    rules = []
    for category in data.get("categories", []):
        for rule in category.get("rules", []):
            if not rule.get("isActive", True):
                continue
            find = rule.get("find", "")
            replace = rule.get("replaceWith", "")
            if find:
                rules.append((find, _convert_backrefs(replace), True))

    return rules


def apply_rules(text: str, rules: list[tuple[str, str, bool]]) -> str:
    """규칙 목록을 순서대로 text에 적용합니다."""
    for find, replace, is_regex in rules:
        if is_regex:
            try:
                text = regex.sub(find, replace, text)
            except Exception:
                pass
        else:
            text = text.replace(find, replace)
    return text
