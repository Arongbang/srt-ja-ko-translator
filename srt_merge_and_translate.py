import argparse
import sys
from pathlib import Path

# Windows 터미널 cp949 환경에서 유니코드 출력 보장
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import config
from srt_processor import get_srt_files, process_srt_file, apply_colloquial_only
from transcriber import transcribe_folder


def main():
    parser = argparse.ArgumentParser(
        description="일본어 영상·자막 파일을 한국어 SRT로 번역합니다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "예시:\n"
            '  python srt_merge_and_translate.py "C:/Subtitles"\n'
            '  python srt_merge_and_translate.py "C:/Subtitles" --skip-transcribe'
        ),
    )
    parser.add_argument("folder", help="처리할 폴더 경로 (영상·SRT 파일 포함)")
    parser.add_argument(
        "--skip-transcribe",
        action="store_true",
        help="영상 자막 추출 단계를 건너뜁니다 (SRT 파일만 번역)",
    )
    parser.add_argument(
        "--only-transcribe",
        action="store_true",
        help="자막 추출만 수행하고 번역은 건너뜁니다",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="각 단계 입출력 상세 로그를 출력합니다",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="파일을 실제로 쓰지 않고 처리 결과만 콘솔에 출력합니다",
    )
    parser.add_argument(
        "--no-hallucination",
        action="store_true",
        help="환각 제거 단계를 건너뜁니다 (원인 분리 디버깅용)",
    )
    parser.add_argument(
        "--only-colloquial",
        action="store_true",
        help=".ko.srt.bak(DeepL 원문)을 입력으로 구어체 변환만 재실행합니다",
    )
    args = parser.parse_args()

    # 디버깅 플래그를 config 전역에 반영
    config.debug = args.debug
    config.dry_run = args.dry_run
    config.skip_hallucination = args.no_hallucination

    if config.debug:
        print("[DEBUG 모드 활성화]")
    if config.dry_run:
        print("[DRY-RUN 모드 — 파일 쓰기 없음]")
    if config.skip_hallucination:
        print("[환각 제거 건너뜀]")

    folder_path = Path(args.folder).resolve()

    if not folder_path.is_dir():
        print(f"오류: {folder_path} 는 존재하지 않거나 폴더가 아닙니다.")
        sys.exit(1)

    # ── 영상 자막 추출 단계 (SRT 탐색 전에 실행) ──────────────────────────────
    print("===== 영상 파일 자막 추출 단계 =====")
    newly_extracted = transcribe_folder(folder_path, skip=args.skip_transcribe)
    if newly_extracted:
        print(f"자막 추출 완료: {len(newly_extracted)}개 파일")
        for p in newly_extracted:
            print(f"  → {p.name}")
        print()

    if args.only_transcribe:
        print("===== --only-transcribe: 자막 추출 완료, 번역 단계 건너뜀 =====")
        return

    # ── 구어체 변환만 재실행 ─────────────────────────────────────────────────
    if args.only_colloquial:
        print("===== --only-colloquial: .ko.srt.bak → 구어체 변환 재실행 =====")
        bak_files = list(folder_path.rglob("*.ko.srt.bak"))
        if not bak_files:
            print("처리할 .ko.srt.bak 파일이 없습니다. (번역을 먼저 실행하세요)")
            sys.exit(1)
        print(f"발견된 백업 파일 수: {len(bak_files)}\n")
        for i, bak_file in enumerate(bak_files, start=1):
            apply_colloquial_only(bak_file, index=i, total=len(bak_files))
            print()
        print("===== 구어체 변환 재실행 완료 =====")
        return

    # ── 번역 단계: DeepL 초기화 ──────────────────────────────────────────────
    config.initialize()

    srt_files = get_srt_files(folder_path)

    if not srt_files:
        print("해당 폴더에 처리할 .srt 파일이 없습니다.")
        if newly_extracted == []:
            print("(영상 파일도 없거나 자막 추출에 모두 실패했을 수 있습니다)")
        return

    print(f"발견된 .srt 파일 수: {len(srt_files)}\n")

    for i, srt_file in enumerate(srt_files, start=1):
        process_srt_file(srt_file, index=i, total=len(srt_files))
        print()

    print("===== 모든 파일 처리 완료 =====")


if __name__ == "__main__":
    main()
