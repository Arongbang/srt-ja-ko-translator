import re
import shutil
import time
from datetime import datetime
from pathlib import Path

import config
from apply_replacements import apply_rules
from hallucination import remove_repeated_patterns, remove_english_line
from translator import translate_ja_to_ko, reset_stats, get_stats


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


def _parse_srt_blocks(srt_content: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current_block: list[str] = []
    for line in srt_content.strip().splitlines():
        if not line.strip():
            if current_block:
                blocks.append(current_block)
                current_block = []
            continue
        current_block.append(line)
    if current_block:
        blocks.append(current_block)
    return blocks


def _rebuild_srt(blocks: list[list[str]]) -> str:
    result_lines: list[str] = []
    for new_index, block in enumerate(blocks, start=1):
        if len(block) < 3:
            continue
        result_lines.append(str(new_index))
        result_lines.extend(block[1:])
        result_lines.append("")
    return "\n".join(result_lines).rstrip() + "\n"


def merge_single_char_captions(srt_content: str) -> str:
    """
    SRT 내용에서 '공백 제외 정확히 1글자'인 자막 블록을 다음 블록과 병합합니다.
    1글자라면 다음 블록 텍스트를 붙이고 시간은 첫 시작~두 번째 끝으로 확장합니다.
    """
    blocks = _parse_srt_blocks(srt_content)
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

    return _rebuild_srt(merged)


def merge_identical_captions(srt_content: str) -> str:
    """
    연속된 동일 텍스트 자막 블록을 하나로 병합합니다.
    시작 시간은 첫 번째 블록, 종료 시간은 마지막 블록 기준입니다.
    """
    blocks = _parse_srt_blocks(srt_content)
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
            if ' '.join(next_block[2:]).strip() != text:
                break
            end_str = next_block[1].split('-->')[1].strip()
            j += 1

        merged.append([block[0], f"{start_str} --> {end_str}"] + block[2:])
        i = j

    return _rebuild_srt(merged)


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


def _count_blocks(srt_content: str) -> int:
    """SRT 문자열에서 자막 블록 수를 셉니다."""
    return len(_parse_srt_blocks(srt_content))


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"  [{ts}] {msg}")


def process_srt_file(filepath: Path, index: int = 1, total: int = 1, replace_rules: list | None = None) -> None:
    """
    하나의 .srt 파일을 처리합니다.

    처리 순서:
    1. 백업 파일(.bak) 생성
    2. 1글자 자막 병합 → 원본 덮어쓰기 (변경 시에만)
    3. 자막 텍스트 블록 단위로 번역
    4. 번역 결과 → .ko.srt 파일로 저장

    이미 .ko.srt가 존재하면 스킵합니다.
    dry_run=True 이면 파일을 실제로 쓰지 않고 콘솔에만 출력합니다.
    """
    ts_start = time.time()
    ts_label = datetime.now().strftime("%H:%M:%S")
    print(f"\n[{ts_label}] ({index}/{total}) 처리 중: {filepath.name}")

    backup_path = filepath.with_suffix(filepath.suffix + '.bak')
    output_path = filepath.with_stem(filepath.stem + ".ko").with_suffix(".srt")

    if output_path.exists() and not config.dry_run:
        _log(f"이미 {output_path.name} 파일이 존재합니다. 스킵.")
        return

    config.refresh_usage()

    if config.usage.character.valid:
        _log(f"DeepL 잔여: {config.remaining:,} / {config.limit:,} 자")
    else:
        _log("경고: character 사용량 정보가 유효하지 않습니다. (무료 플랜 외일 수 있음)")

    if config.remaining == 0:
        _log("→ 로컬 모델 사용하여 번역 진행")

    try:
        # ── Step 1: 백업 ─────────────────────────────────────────────
        if not config.dry_run:
            shutil.copy2(filepath, backup_path)
        _log(f"{'[dry-run] ' if config.dry_run else ''}백업 생성: {backup_path.name}")

        original_content = filepath.read_text(encoding="utf-8-sig")
        orig_blocks = _count_blocks(original_content)

        # ── Step 2: 1글자 병합 ───────────────────────────────────────
        t0 = time.time()
        merged_content = merge_single_char_captions(original_content)
        after_single = _count_blocks(merged_content)

        # ── Step 3: 중복 자막 병합 ───────────────────────────────────
        merged_content = merge_identical_captions(merged_content)
        after_dup = _count_blocks(merged_content)
        _log(
            f"병합: {orig_blocks}블록 → 1글자병합 {after_single}블록 → 중복제거 {after_dup}블록 "
            f"({time.time() - t0:.1f}s)"
        )

        # ── Step 4: 반복 패턴 & 영문자 필터 ─────────────────────────
        t0 = time.time()
        filtered_lines = []
        in_text = False
        removed_lines = 0
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
                cleaned = remove_repeated_patterns(remove_english_line(line))
                if cleaned != line:
                    removed_lines += 1
                filtered_lines.append(cleaned)
            else:
                filtered_lines.append(line)
        merged_content = '\n'.join(filtered_lines) + '\n'
        _log(f"전처리 필터: {removed_lines}줄 정제됨 ({time.time() - t0:.1f}s)")

        # ── Step 5: 원본 덮어쓰기 (변경 시에만) ──────────────────────
        if merged_content.strip() != original_content.strip():
            if not config.dry_run:
                filepath.write_text(merged_content, encoding="utf-8-sig")
            _log(f"{'[dry-run] ' if config.dry_run else ''}원본 SRT 업데이트 완료")
        else:
            _log("원본 변경 사항 없음")

        # ── Step 6: 번역 ─────────────────────────────────────────────
        _log(f"번역 시작 ({after_dup}블록)...")
        reset_stats()
        t0 = time.time()
        translated_content = _translate_srt_content(merged_content)
        stats = get_stats()
        total_translated = stats["deepl"] + stats["llm"] + stats["failed"]
        elapsed = time.time() - t0
        _log(
            f"번역 완료: DeepL={stats['deepl']} / LLM폴백={stats['llm']} / 실패={stats['failed']} "
            f"(총 {total_translated}블록, {elapsed:.1f}s)"
        )

        if config.dry_run:
            _log("[dry-run] 번역 결과 미저장 — 처음 3블록 미리보기:")
            preview_blocks = _parse_srt_blocks(translated_content)[:3]
            for b in preview_blocks:
                print("    " + " | ".join(b))
            return

        # ── Step 7: .ko.srt 저장 & 백업 ─────────────────────────────
        output_path.write_text(translated_content, encoding="utf-8-sig")
        shutil.copy2(output_path, output_path.with_suffix(output_path.suffix + '.bak'))
        _log(f"저장 완료: {output_path.name}  (백업: {output_path.name}.bak)")

        # ── Step 8: 치환 규칙 적용 ───────────────────────────────────
        if replace_rules:
            t0 = time.time()
            replaced_content = apply_rules(translated_content, replace_rules)
            if replaced_content != translated_content:
                output_path.write_text(replaced_content, encoding="utf-8-sig")
                _log(f"치환 규칙 적용 완료 ({time.time() - t0:.1f}s)")
            else:
                _log(f"치환 규칙: 변경 사항 없음 ({time.time() - t0:.1f}s)")

        elapsed_total = time.time() - ts_start
        _log(f"완료 ✓  총 소요: {elapsed_total:.1f}s")

    except Exception as e:
        _log(f"!!! 오류 발생: {e}")
        if backup_path.exists():
            _log(f"(참고: 백업 파일은 생성되었습니다 — {backup_path.name})")
        raise
