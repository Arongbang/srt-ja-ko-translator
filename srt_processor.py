import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import config
from apply_replacements import apply_rules
from hallucination import remove_repeated_patterns
from translator import translate_ja_to_ko, reset_stats, get_stats, get_failed_texts

STATUS_DONE = "완료"
STATUS_PARTIAL = "부분 오류"
STATUS_FAILED = "처리 실패"


@dataclass
class ProcessResult:
    """process_srt_file()의 처리 결과를 담는 객체."""
    filename: str
    status: str
    error_stage: str | None = None
    error_message: str | None = None
    failed_blocks: int = 0
    total_blocks: int = 0
    failed_texts: list[str] = field(default_factory=list)


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


def normalize_alpha_kun(line: str) -> str:
    """
    영문자+君 표기(예: J君)를 영문자+K(예: JK)로 정규화합니다.
    DeepL이 'J君' 같은 혼합 표기를 잘 처리하지 못하므로 JK로 통일합니다.
    """
    return re.sub(r'([A-Za-z])\s*君', r'\1K', line)


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


def _parse_timestamp(ts: str) -> float:
    """SRT 타임스탬프(HH:MM:SS,mmm) → 초(float) 변환"""
    ts = ts.replace(',', '.')
    h, m, rest = ts.split(':')
    return int(h) * 3600 + int(m) * 60 + float(rest)


def _format_timestamp(seconds: float) -> str:
    """float 초 → SRT 타임스탬프 형식(HH:MM:SS,mmm) 변환"""
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds % 1) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"



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
            block[j] = normalize_alpha_kun(remove_little_rest_phrases(block[j]))

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


def process_srt_file(filepath: Path, index: int = 1, total: int = 1, replace_rules: list | None = None) -> ProcessResult:
    """
    하나의 .srt 파일을 처리합니다.

    처리 순서:
    1. 백업 파일(.bak) 생성
    2. 긴 자막 블록 분할 (20글자 초과 블록을 구두점/균등 기준으로 분리)
    3. 1글자 자막 병합 → 원본 덮어쓰기 (변경 시에만)
    4. 자막 텍스트 블록 단위로 번역
    5. 번역 결과 → .ko.srt 파일로 저장

    이미 .ko.srt가 존재하면 스킵합니다.
    dry_run=True 이면 파일을 실제로 쓰지 않고 콘솔에만 출력합니다.

    예외가 발생해도 이 함수는 raise하지 않고 ProcessResult(status=STATUS_FAILED)를
    반환합니다 — 한 파일의 오류가 main()의 나머지 파일 처리를 막지 않도록 하기 위함입니다.
    """
    ts_start = time.time()
    ts_label = datetime.now().strftime("%H:%M:%S")
    print(f"\n[{ts_label}] ({index}/{total}) 처리 중: {filepath.name}")

    backup_path = filepath.with_suffix(filepath.suffix + '.bak')
    output_path = filepath.with_stem(filepath.stem + ".ko").with_suffix(".srt")

    if output_path.exists() and not config.dry_run:
        _log(f"이미 {output_path.name} 파일이 존재합니다. 스킵.")
        return ProcessResult(filename=filepath.name, status=STATUS_DONE)

    current_stage = "사용량 조회"
    try:
        config.refresh_usage()

        if config.usage.character.valid:
            _log(f"DeepL 잔여: {config.remaining:,} / {config.limit:,} 자")
        else:
            _log("경고: character 사용량 정보가 유효하지 않습니다. (무료 플랜 외일 수 있음)")

        if config.remaining == 0:
            _log("경고: DeepL 잔여 한도 0 — 번역 실패 가능")

        # ── Step 1: 백업 ─────────────────────────────────────────────
        current_stage = "백업"
        if not config.dry_run:
            shutil.copy2(filepath, backup_path)
        _log(f"{'[dry-run] ' if config.dry_run else ''}백업 생성: {backup_path.name}")

        current_stage = "파일 읽기"
        original_content = filepath.read_text(encoding="utf-8-sig")
        orig_blocks = _count_blocks(original_content)

        # ── Step 3: 1글자 병합 ───────────────────────────────────────
        current_stage = "1글자 병합"
        t0 = time.time()
        merged_content = merge_single_char_captions(original_content)
        after_single = _count_blocks(merged_content)

        # ── Step 4: 중복 자막 병합 ───────────────────────────────────
        current_stage = "중복 병합"
        merged_content = merge_identical_captions(merged_content)
        after_dup = _count_blocks(merged_content)
        _log(
            f"병합: {orig_blocks}블록 → 1글자병합 {after_single}블록 → 중복제거 {after_dup}블록 "
            f"({time.time() - t0:.1f}s)"
        )

        # ── Step 5: 반복 패턴 & 영문자 필터 ─────────────────────────
        current_stage = "반복 패턴 필터"
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
                cleaned = remove_repeated_patterns(line)
                if cleaned != line:
                    removed_lines += 1
                filtered_lines.append(cleaned)
            else:
                filtered_lines.append(line)
        merged_content = '\n'.join(filtered_lines) + '\n'
        _log(f"전처리 필터: {removed_lines}줄 정제됨 ({time.time() - t0:.1f}s)")

        # ── Step 6: 원본 덮어쓰기 (변경 시에만) ──────────────────────
        current_stage = "원본 저장"
        if merged_content.strip() != original_content.strip():
            if not config.dry_run:
                filepath.write_text(merged_content, encoding="utf-8-sig")
            _log(f"{'[dry-run] ' if config.dry_run else ''}원본 SRT 업데이트 완료")
        else:
            _log("원본 변경 사항 없음")

        # ── Step 7: 번역 ─────────────────────────────────────────────
        current_stage = "번역"
        _log(f"번역 시작 ({after_dup}블록)...")
        reset_stats()
        t0 = time.time()
        translated_content = _translate_srt_content(merged_content)
        stats = get_stats()
        failed_texts = get_failed_texts()
        total_translated = stats["deepl"] + stats["failed"]
        elapsed = time.time() - t0
        _log(
            f"번역 완료: DeepL={stats['deepl']} / 실패={stats['failed']} "
            f"(총 {total_translated}블록, {elapsed:.1f}s)"
        )

        if config.dry_run:
            _log("[dry-run] 번역 결과 미저장 — 처음 3블록 미리보기:")
            preview_blocks = _parse_srt_blocks(translated_content)[:3]
            for b in preview_blocks:
                print("    " + " | ".join(b))
            status = STATUS_PARTIAL if stats["failed"] > 0 else STATUS_DONE
            return ProcessResult(
                filename=filepath.name, status=status,
                failed_blocks=stats["failed"], total_blocks=total_translated,
                failed_texts=failed_texts,
            )

        # ── Step 8: template 치환 규칙 적용 ──────────────────────────
        current_stage = "치환 규칙 적용"
        if replace_rules:
            t0 = time.time()
            ko_bak_path = output_path.with_name(output_path.name + ".bak")
            ko_bak_path.write_text(translated_content, encoding="utf-8-sig")
            _log(f"치환 전 백업 저장: {ko_bak_path.name}")
            translated_content = apply_rules(translated_content, replace_rules)
            _log(f"template 치환 완료 ({time.time() - t0:.1f}s)")

        # ── Step 9: 번역 결과 .ko.srt 저장 ──
        current_stage = "결과 저장"
        output_path.write_text(translated_content, encoding="utf-8-sig")
        _log(f"저장 완료 → {output_path.name}")

        elapsed_total = time.time() - ts_start
        _log(f"완료 ✓  총 소요: {elapsed_total:.1f}s")

        status = STATUS_PARTIAL if stats["failed"] > 0 else STATUS_DONE
        return ProcessResult(
            filename=filepath.name, status=status,
            failed_blocks=stats["failed"], total_blocks=total_translated,
            failed_texts=failed_texts,
        )

    except Exception as e:
        _log(f"!!! 오류 발생: {e}")
        if backup_path.exists():
            _log(f"(참고: 백업 파일은 생성되었습니다 — {backup_path.name})")
        return ProcessResult(
            filename=filepath.name, status=STATUS_FAILED,
            error_stage=current_stage, error_message=str(e),
        )


def print_summary(results: list[ProcessResult]) -> None:
    """
    모든 파일 처리가 끝난 후 완료/부분 오류/처리 실패 개수와
    오류가 있는 파일의 상세 목록을 출력합니다.
    """
    done = sum(1 for r in results if r.status == STATUS_DONE)
    partial = sum(1 for r in results if r.status == STATUS_PARTIAL)
    failed = sum(1 for r in results if r.status == STATUS_FAILED)

    print(f"완료: {done}/{len(results)}, 부분 오류: {partial}, 처리 실패: {failed}")

    if partial + failed == 0:
        return

    print("--- 오류 상세 ---")
    for r in results:
        if r.status == STATUS_PARTIAL:
            print(f"[부분 오류] {r.filename} — 번역 {r.failed_blocks}/{r.total_blocks}블록 실패")
            for text in r.failed_texts:
                snippet = text.replace("\n", " ").strip()
                if len(snippet) > 100:
                    snippet = snippet[:100] + "..."
                print(f"    └ {snippet}")
        elif r.status == STATUS_FAILED:
            message = r.error_message or ""
            if len(message) > 100:
                message = message[:100] + "..."
            print(f"[처리 실패] {r.filename} — {r.error_stage} 단계 — {message}")
