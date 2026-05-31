import re
import regex
import xml.etree.ElementTree as ET
from pathlib import Path


def _convert_backrefs(replace: str) -> str:
    """SubtitleEdit 방식의 역참조 ($1, $2) 를 Python 방식 (\\1, \\2) 으로 변환합니다."""
    return re.sub(r'\$(\d+)', lambda m: '\\' + m.group(1), replace)


def load_replace_rules(template_path: Path) -> list[tuple[str, str, bool]]:
    """
    template 파일에서 활성화된 치환 규칙을 읽어 반환합니다.
    반환값: [(find, replace, is_regex), ...]
    """
    tree = ET.parse(template_path)
    root = tree.getroot()

    rules = []
    for group in root.iter("Group"):
        if group.findtext("Enabled", "True").strip().lower() != "true":
            continue
        for item in group.iter("MultipleSearchAndReplaceItem"):
            if item.findtext("Enabled", "True").strip().lower() != "true":
                continue
            find = item.findtext("FindWhat", "")
            replace = item.findtext("ReplaceWith", "")
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
