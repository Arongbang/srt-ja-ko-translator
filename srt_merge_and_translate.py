import sys
from pathlib import Path

import config
from srt_processor import get_srt_files, process_srt_file


def main():
    if len(sys.argv) != 2:
        print("사용법: python srt_merge_and_translate.py \"폴더경로\"")
        print("예시:")
        print('  python srt_merge_and_translate.py "C:/Subtitles"')
        sys.exit(1)

    config.initialize()

    folder_path = Path(sys.argv[1]).resolve()

    if not folder_path.is_dir():
        print(f"오류: {folder_path} 는 존재하지 않거나 폴더가 아닙니다.")
        sys.exit(1)

    srt_files = get_srt_files(folder_path)

    if not srt_files:
        print("해당 폴더에 처리할 .srt 파일이 없습니다.")
        return

    print(f"발견된 .srt 파일 수: {len(srt_files)}\n")

    for srt_file in srt_files:
        process_srt_file(srt_file)
        print()

    print("===== 모든 파일 처리 완료 =====")


if __name__ == "__main__":
    main()
