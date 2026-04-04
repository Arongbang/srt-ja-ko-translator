import re
import shutil
from pathlib import Path

import config
from hallucination import remove_repeated_patterns, remove_english_line
from translator import translate_ja_to_ko


def get_srt_files(folder_path: Path) -> list[Path]:
    """
    지정한 폴더(및 하위 폴더)에서 .srt 파일을 모두 찾아 반환합니다.
    이미 번역된 파일(.ko.srt)은 제외합니다.
    """
    return [
        p for p in folder_path.rglob("*.srt")
        if not p.stem.endswith(".ko")
    ]


def remove_little_rest_phrases(line: str) -> str:
    """
    일본어 자막에서 자주 나오는 '少し休...' 같은 휴식 표현을 제거합니다.
    예: "少し休憩…" → ""
    """
    pattern = r'(\s)?少(\s)?し(\s)?休[^\.。\,\?]{1,}[\.。\,\?]{1,}'
    return re.sub(pattern, '', line)


def merge_single_char_captions(srt_content: str) -> str:
    """
    SRT 내용에서 '공백 제외 정확히 1글자'인 자막 블록을 다음 블록과 병합합니다.

    처리 흐름:
    1. SRT를 블록 단위(번호 + 시간 + 텍스트)로 분리
    2. 각 블록의 텍스트에서 모든 공백 제거 후 길이가 1인지 확인
    3. 1글자라면 다음 블록 텍스트를 붙이고 시간은 첫 시작~두 번째 끝으로 확장
    4. 최종적으로 번호를 1부터 다시 매김
    """
    lines = srt_content.strip().splitlines()
    blocks: list[list[str]] = []
    current_block: list[str] = []

    for line in lines:
        if not line.strip():
            if current_block:
                blocks.append(current_block)
                current_block = []
            continue
        current_block.append(line)

    if current_block:
        blocks.append(current_block)

    merged: list[list[str]] = []
    i = 0

    while i < len(blocks):
        block = blocks[i]

        if len(block) < 3:
            merged.append(block)
            i += 1
            continue

        num = block[0]
        time_line = block[1]

        for j in range(2, len(block)):
            block[j] = remove_little_rest_phrases(block[j])

        text_parts = block[2:]
        text = ' '.join(text_parts).strip()
        text_clean = re.sub(r'\s+', '', text)

        if i + 1 < len(blocks) and len(text_clean) == 1:
            next_block = blocks[i + 1]
            if len(next_block) < 3:
                merged.append(block)
                i += 1
                continue

            next_time_line = next_block[1]
            next_text = ' '.join(next_block[2:]).strip()

            start_str = time_line.split('-->')[0].strip()
            next_end_str = next_time_line.split('-->')[1].strip()

            merged.append([num, f"{start_str} --> {next_end_str}", text + next_text])
            i += 2
        else:
            merged.append(block)
            i += 1

    result_lines: list[str] = []
    for new_index, block in enumerate(merged, start=1):
        if len(block) < 3:
            continue
        result_lines.append(str(new_index))
        result_lines.extend(block[1:])
        result_lines.append("")

    return "\n".join(result_lines).rstrip() + "\n"


def merge_identical_captions(srt_content: str) -> str:
    """
    연속된 동일 텍스트 자막 블록을 하나로 병합합니다.

    처리 흐름:
    1. SRT를 블록 단위로 분리
    2. 현재 블록과 다음 블록의 텍스트가 동일하면 계속 확장
    3. 시작 시간은 첫 번째 블록, 종료 시간은 마지막 블록 기준
    4. 최종적으로 번호를 1부터 다시 매김
    """
    lines = srt_content.strip().splitlines()
    blocks: list[list[str]] = []
    current_block: list[str] = []

    for line in lines:
        if not line.strip():
            if current_block:
                blocks.append(current_block)
                current_block = []
            continue
        current_block.append(line)

    if current_block:
        blocks.append(current_block)

    merged: list[list[str]] = []
    i = 0

    while i < len(blocks):
        block = blocks[i]

        if len(block) < 3:
            merged.append(block)
            i += 1
            continue

        text = ' '.join(block[2:]).strip()
        start_str = block[1].split('-->')[0].strip()
        end_str = block[1].split('-->')[1].strip()

        j = i + 1
        while j < len(blocks):
            next_block = blocks[j]
            if len(next_block) < 3:
                break
            next_text = ' '.join(next_block[2:]).strip()
            if next_text != text:
                break
            end_str = next_block[1].split('-->')[1].strip()
            j += 1

        merged.append([block[0], f"{start_str} --> {end_str}"] + block[2:])
        i = j

    result_lines: list[str] = []
    for new_index, block in enumerate(merged, start=1):
        if len(block) < 3:
            continue
        result_lines.append(str(new_index))
        result_lines.extend(block[1:])
        result_lines.append("")

    return "\n".join(result_lines).rstrip() + "\n"


def _translate_srt_content(srt_content: str) -> str:
    """SRT 문자열의 텍스트 블록만 번역하여 반환합니다."""
    lines = srt_content.splitlines()
    translated_lines: list[str] = []
    in_text_block = False
    current_text: list[str] = []

    def flush_translation():
        if current_text:
            translated = translate_ja_to_ko("\n".join(current_text))
            translated_lines.extend(translated.splitlines())
            current_text.clear()

    for line in lines:
        stripped = line.strip()

        if not stripped:
            flush_translation()
            translated_lines.append("")
            in_text_block = False
            continue

        if re.match(r'^\d+$', stripped):
            flush_translation()
            translated_lines.append(line)
            in_text_block = False
            continue

        if "-->" in stripped:
            translated_lines.append(line)
            in_text_block = True
            continue

        if in_text_block:
            current_text.append(line)
        else:
            translated_lines.append(line)

    flush_translation()
    return "\n".join(translated_lines).rstrip() + "\n"


def process_srt_file(filepath: Path, index: int = 1, total: int = 1) -> None:
    """
    하나의 .srt 파일을 처리합니다.

    처리 순서:
    1. 백업 파일(.bak) 생성
    2. 1글자 자막 병합 → 원본 덮어쓰기 (변경 시에만)
    3. 자막 텍스트 블록 단위로 번역
    4. 번역 결과 → .ko.srt 파일로 저장

    이미 .ko.srt가 존재하면 스킵합니다.
    """
    print(f"({index}/{total}) 처리 중: {filepath}")

    backup_path = filepath.with_suffix(filepath.suffix + '.bak')
    output_path = filepath.with_stem(filepath.stem + ".ko").with_suffix(".srt")

    if output_path.exists():
        print(f"  → 이미 {output_path.name} 파일이 존재합니다. 스킵.")
        return

    config.refresh_usage()

    if config.usage.character.valid:
        print(f"  현재 사용: {config.used:,} / {config.limit:,} 자  (남음: {config.remaining:,} 자)")
    else:
        print("  경고: character 사용량 정보가 유효하지 않습니다.")
        print("  → 무료 플랜이 아닌 경우일 수 있으니 한도 체크 없이 진행합니다.")

    if config.remaining == 0:
        print("  → 로컬 모델 사용하여 번역 진행")

    try:
        shutil.copy2(filepath, backup_path)
        print(f"  → 백업 생성: {backup_path.name}")

        original_content = filepath.read_text(encoding="utf-8-sig")
        merged_content = merge_single_char_captions(original_content)
        merged_content = merge_identical_captions(merged_content)

        filtered_lines = []
        in_text = False
        for line in merged_content.splitlines():
            stripped = line.strip()
            if not stripped:
                in_text = False
                filtered_lines.append(line)
            elif re.match(r'^\d+$', stripped):
                in_text = False
                filtered_lines.append(line)
            elif '-->' in stripped:
                in_text = True
                filtered_lines.append(line)
            elif in_text:
                line = remove_repeated_patterns(remove_english_line(line))
                filtered_lines.append(line)
            else:
                filtered_lines.append(line)
        merged_content = '\n'.join(filtered_lines) + '\n'

        if merged_content.strip() != original_content.strip():
            filepath.write_text(merged_content, encoding="utf-8-sig")
            print("  → 1글자 병합 & 중복 자막 병합 수정 완료 (원본 덮어쓰기)")
        else:
            print("  → 1글자 병합 & 중복 자막 병합 변경 사항 없음")

        translated_content = _translate_srt_content(merged_content)
        output_path.write_text(translated_content, encoding="utf-8-sig")
        print(f"  → 한국어 자막 저장 완료: {output_path.name}")

    except Exception as e:
        print(f"  !!! 오류 발생: {e}")
        if backup_path.exists():
            print(f"  (참고: 백업 파일은 생성되었습니다 - {backup_path.name})")
