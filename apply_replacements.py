import re
import regex
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _convert_backrefs(replace: str) -> str:
    """SubtitleEdit 방식의 역참조 (\\$1, \\$2) 를 Python 방식 (\\1, \\2) 으로 변환합니다."""
    return re.sub(r'\\\$(\d+)', lambda m: '\\' + m.group(1), replace)


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
            text = regex.sub(find, replace, text)
        else:
            text = text.replace(find, replace)
    return text


def process_srt(srt_path: Path, rules: list[tuple[str, str, bool]]) -> None:
    content = srt_path.read_text(encoding="utf-8-sig")
    updated = apply_rules(content, rules)
    if updated != content:
        shutil.copy2(srt_path, srt_path.with_suffix(srt_path.suffix + '.bak'))
        srt_path.write_text(updated, encoding="utf-8-sig")
        print(f"  수정됨: {srt_path.name}")
    else:
        print(f"  변경 없음: {srt_path.name}")


def main():
    if len(sys.argv) != 3:
        print("사용법: python apply_replacements.py <template.xml> <srt_folder>")
        sys.exit(1)

    template_path = Path(sys.argv[1])
    srt_folder = Path(sys.argv[2])

    rules = load_replace_rules(template_path)
    print(f"로드된 규칙 수: {len(rules)}")

    srt_files = list(srt_folder.rglob("*.ko.srt"))
    print(f"처리할 SRT 파일 수: {len(srt_files)}\n")

    for srt_file in srt_files:
        process_srt(srt_file, rules)


if __name__ == "__main__":
    main()
