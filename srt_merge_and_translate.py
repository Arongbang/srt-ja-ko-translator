import re
import sys
import shutil
from pathlib import Path
import deepl
from dotenv import load_dotenv
import os
from openai import OpenAI


# ────────────────────────────────────────────────────────────────
# 1. 환경 설정 및 DeepL 초기화
# ────────────────────────────────────────────────────────────────

# .env 파일에서 환경변수 로드
load_dotenv()

# DeepL API 키 가져오기
DEEPL_API_KEY = os.getenv("DEEPL_API_KEY")

# API 키가 없으면 즉시 종료 (보안 및 오류 방지)
if not DEEPL_API_KEY:
    print("오류: .env 파일에 DEEPL_API_KEY가 설정되어 있지 않습니다.")
    print("예시 .env 내용:")
    print('DEEPL_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx:fx')
    sys.exit(1)

# LM Studio OpenAI-compatible 클라이언트[](http://127.0.0.1:1234/v1)
LOCAL_LLM_CLIENT = OpenAI(
    base_url="http://127.0.0.1:1234/v1",
    api_key="lm-studio"  # LM Studio는 더미 키 사용 (아무거나 상관없음)
)

# LM Studio에서 로드한 모델 이름
LOCAL_MODEL_NAME = "ja-ko-vn-7b-v1"

# DeepL 번역기 객체 생성
try:
    # 무료 계정(api-free.deepl.com)
    translator = deepl.Translator(DEEPL_API_KEY, server_url="https://api-free.deepl.com")
    
    print("DeepL 초기화 성공")
except Exception as e:
    print(f"DeepL 초기화 실패: {e}")
    sys.exit(1)

# DeepL API 한도 확인
usage = translator.get_usage()

used = usage.character.count
limit = usage.character.limit
remaining = limit - used

# ────────────────────────────────────────────────────────────────
# 2. 일본어 → 한국어 번역 함수 (AV 자막 특화)
# ────────────────────────────────────────────────────────────────

def translate_ja_to_ko(text: str) -> str:
    """
    일본어 텍스트를 한국어로 번역합니다.
    AV(성인 영상) 자막에 최적화된 설정을 사용합니다.
    
    주요 특징:
    - 반말 중심이지만 부드러운 존댓말(-요 체)도 상황에 따라 자연스럽게 섞음
    - ♡ 같은 이모티콘은 분위기에 맞춰 적절히 추가
    - 최고 품질 모델 사용
    - 원문의 느낌(감탄사, 의성어 등) 최대한 유지
    
    Args:
        text (str): 번역할 일본어 텍스트 (한 블록 또는 여러 줄 가능)
    
    Returns:
        str: 번역된 한국어 텍스트
             실패 시 "[번역 실패] 원문" 형식으로 반환
    """
    # 빈 문자열이면 그대로 반환 (불필요한 API 호출 방지)
    if not text.strip():
        return text

    try:
        #DeepL
        result = translator.translate_text(
            text,                        # 번역 대상 텍스트
            source_lang="JA",            # 원본 언어: 일본어 고정
            target_lang="KO",            # 목표 언어: 한국어
            formality="prefer_less",     # 반말·캐주얼 톤 강하게 유도 (default보다 덜 격식)
            model_type="quality_optimized",  # 최신 고품질 모델 강제 (응답은 느릴 수 있음)
            context=(
                "너는 일본어 AV 자막을 한국어로 번역하는 전문 번역가야. "
                "기본적으로 구어체의 캐주얼한 반말을 사용하지만, 존댓말을 사용할 때는 -요 체의 부드러운 구어체의 존댓말을 자연스럽게 섞어주세요. "
                "♡ 같은 이모티콘을 분위기에 맞춰 적절히 추가하여 분위기를 살려주세요."
            ),                           # 번역 품질 향상을 위한 맥락 지시 (청구 비용 없음)
            preserve_formatting=True,    # 숫자, 공백, 기호(!?…, ♡ 등) 형식 유지
            split_sentences="1",         # 구두점 + 줄바꿈 기준으로 문장 분할 (자막에 적합)
        )

        return result.text.strip()       # 앞뒤 공백 제거 후 반환
    except deepl.DeepLException as e:
        #로컬 LLM fallback
        try:
            response = LOCAL_LLM_CLIENT.chat.completions.create(
                model=LOCAL_MODEL_NAME,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "너는 일본어 AV 자막을 한국어로 번역하는 전문 번역가야.\n"
                            "원문의 느낌을 최대한 살려서 자연스럽고 직설적인 한국어로 번역해.\n"
                            "기본은 캐주얼 반말이지만, 부드러운 대화나 감정 표현 시 -요 체 존댓말을 자연스럽게 섞어.\n"
                            "흥분되거나 애교스러운 부분은 ♡ 같은 이모티콘을 적절히 넣어.\n"
                            "야한 표현은 한국어 사용자에게 자연스럽게 들리도록 해.\n"
                            "번역만 출력하고 다른 설명은 넣지 마."
                        )
                    },
                    {
                        "role": "user",
                        "content": f"다음 일본어 자막을 한국어로 번역해:\n\n{text}"
                    }
                ],
                temperature=0.7,          # 약간 창의성 주기 (너무 딱딱하지 않게)
                max_tokens=512,           # 자막 한 블록이니 충분
                top_p=0.9,
            )

            translated = response.choices[0].message.content.strip()
            return translated
        
        except Exception as local_e:
            print(f"로컬 LLM 번역도 실패: {local_e}")
            return f"[번역 실패 - DeepL & 로컬 모두 오류] {text}"

# ────────────────────────────────────────────────────────────────
# 3. SRT 파일 목록 가져오기
# ────────────────────────────────────────────────────────────────

def get_srt_files(folder_path: Path) -> list[Path]:
    """
    지정한 폴더(및 하위 폴더)에서 .srt 파일을 모두 찾아 반환합니다.
    이미 번역된 파일(.ko.srt)은 제외합니다.
    
    Returns:
        list[Path]: 처리 대상 .srt 파일 경로 리스트
    """
    return [
        p for p in folder_path.rglob("*.srt")           # 재귀적으로 모든 .srt 찾기
        if p.suffix == ".srt" and not p.stem.endswith(".ko")  # .ko.srt 제외
    ]


# ────────────────────────────────────────────────────────────────
# 4. 특정 일본어 휴식 표현 제거 (필요 시)
# ────────────────────────────────────────────────────────────────

def remove_little_rest_phrases(line: str) -> str:
    """
    일본어 자막에서 자주 나오는 '少し休...' 같은 휴식 표현을 제거합니다.
    정규표현식으로 패턴 매칭 후 삭제.
    
    예: "少し休憩…" → ""
    """
    # 패턴 설명: (공백)? 少(공백)? し(공백)? 休 + 비구두점 문자들 + 구두점 1개 이상
    pattern = r'(\s)?少(\s)?し(\s)?休[^\.。\,\?]{1,}[\.。\,\?]{1,}'
    return re.sub(pattern, '', line)


# ────────────────────────────────────────────────────────────────
# 5. 1글자 자막 병합 핵심 함수
# ────────────────────────────────────────────────────────────────

def merge_single_char_captions(srt_content: str) -> str:
    """
    SRT 내용에서 '공백 제외 정확히 1글자'인 자막 블록을 다음 블록과 병합합니다.
    → 자막 타이밍이 너무 짧거나 1글자씩 끊겨 나오는 문제를 해결
    
    처리 흐름:
    1. SRT를 블록 단위(번호 + 시간 + 텍스트)로 분리
    2. 각 블록의 텍스트에서 모든 공백 제거 후 길이가 1인지 확인
    3. 1글자라면 다음 블록 텍스트를 붙이고 시간은 첫 시작~두 번째 끝으로 확장
    4. 최종적으로 번호를 1부터 다시 매김
    
    Returns:
        str: 병합 완료된 새로운 SRT 문자열
    """
    lines = srt_content.strip().splitlines()
    blocks = []               # SRT 블록 리스트 (번호, 시간, 텍스트들)
    current_block = []        # 현재 처리 중인 블록

    # 1. 블록 단위로 분리
    for line in lines:
        stripped = line.strip()
        if not stripped:      # 빈 줄 → 블록 종료
            if current_block:
                blocks.append(current_block)
                current_block = []
            continue
        current_block.append(line)  # 원본 줄 그대로 저장 (들여쓰기 유지)

    if current_block:
        blocks.append(current_block)

    merged = []               # 병합 결과 블록 저장
    i = 0

    while i < len(blocks):
        block = blocks[i]
        
        # 비정상 블록(3줄 미만: 번호+시간+텍스트 최소 구성 안 됨)은 그대로 유지
        if len(block) < 3:
            merged.append(block)
            i += 1
            continue

        num = block[0]              # 자막 번호 (문자열)
        time_line = block[1]        # 시간줄 ex) 00:01:23,450 --> 00:01:24,120
        text_parts = block[2:]      # 텍스트 부분 (1줄 이상 가능)

        # 휴식 표현 제거 적용
        for j in range(2, len(block)):
            block[j] = remove_little_rest_phrases(block[j])

        # 텍스트 합쳐서 공백 제거 후 길이 체크 (일본어는 띄어쓰기 거의 없음)
        text = ' '.join(text_parts).strip()
        text_clean = re.sub(r'\s+', '', text)  # 모든 공백 제거

        # 병합 조건: 현재가 1글자이고 다음 블록 존재
        if i + 1 < len(blocks) and len(text_clean) == 1:
            next_block = blocks[i + 1]
            if len(next_block) < 3:
                merged.append(block)
                i += 1
                continue

            # 다음 블록 정보 추출
            next_time_line = next_block[1]
            next_text_parts = next_block[2:]
            next_text = ' '.join(next_text_parts).strip()

            # 새 시간 범위: 현재 시작 ~ 다음 종료
            start_str = time_line.split('-->')[0].strip()
            next_end_str = next_time_line.split('-->')[1].strip()
            new_time_line = f"{start_str} --> {next_end_str}"

            # 텍스트 단순 연결 (일본어는 띄어쓰기 없이 자연스럽게 붙음)
            combined_text = text + next_text

            merged.append([num, new_time_line, combined_text])
            i += 2  # 다음 블록까지 처리했으므로 2칸 이동
        else:
            merged.append(block)
            i += 1

    # ── 최종 SRT 재구성 ──────────────────────────────────────────
    result_lines = []
    new_index = 1

    for block in merged:
        if len(block) < 3:
            continue

        result_lines.append(str(new_index))     # 새 번호
        result_lines.append(block[1])           # 시간줄
        result_lines.append(block[2])           # 병합된 텍스트 (또는 원본)

        # 원본이 여러 줄 텍스트였다면 추가 줄도 그대로 붙임
        if len(block) > 3:
            for extra in block[3:]:
                result_lines.append(extra)

        result_lines.append("")                 # SRT 블록 간 빈 줄
        new_index += 1

    # 마지막 불필요 개행 제거 후 파일 끝에 개행 하나 추가 (SRT 관례)
    return "\n".join(result_lines).rstrip() + "\n"


# ────────────────────────────────────────────────────────────────
# 6. 단일 SRT 파일 처리 (병합 → 번역 → .ko.srt 저장)
# ────────────────────────────────────────────────────────────────

def process_srt_file(filepath: Path):
    """
    하나의 .srt 파일을 처리하는 메인 함수
    
    처리 순서:
    1. 백업 파일(.bak) 생성
    2. 1글자 자막 병합 → 원본 덮어쓰기 (변경 시에만)
    3. 병합된 내용에서 자막 텍스트 블록 단위로 번역
    4. 번역 결과 → .ko.srt 파일로 저장 (원본은 그대로 유지)
    
    이미 .ko.srt가 존재하면 스킵
    """
    print(f"처리 중: {filepath}")

    backup_path = filepath.with_suffix(filepath.suffix + '.bak')
    output_path = filepath.with_stem(filepath.stem + ".ko").with_suffix(".srt")

    # 이미 번역본이 있으면 스킵 (중복 처리 방지)
    if output_path.exists():
        print(f"  → 이미 {output_path.name} 파일이 존재합니다. 스킵.")
        return
    
    

    # DeepL API 잔여량 확인
    if usage.character.valid:
        print(f"  현재 사용: {used:,} / {limit:,} 자  (남음: {remaining:,} 자)")
    else:
        print("  경고: character 사용량 정보가 유효하지 않습니다.")
        print("  → 무료 플랜이 아닌 경우일 수 있으니 한도 체크 없이 진행합니다.")

    #작업시작
    try:
        # 1. 원본 백업 (메타데이터까지 복사)
        shutil.copy2(filepath, backup_path)
        print(f"  → 백업 생성: {backup_path.name}")

        # 2. 원본 내용 읽기 (BOM付き UTF-8도 처리)
        original_content = filepath.read_text(encoding="utf-8-sig")

        # 3. 1글자 자막 병합 수행
        merged_content = merge_single_char_captions(original_content)

        # 병합으로 변경이 있었다면 원본 파일 덮어쓰기
        if merged_content.strip() != original_content.strip():
            filepath.write_text(merged_content, encoding="utf-8-sig")
            print(f"  → 1글자 병합 수정 완료 (원본 덮어쓰기)")
        else:
            print(f"  → 1글자 병합 변경 사항 없음")

        # 4. 번역 단계: 블록 단위로 처리 (번호/시간 유지, 텍스트만 번역)
        if remaining == 0:
            print(f"  → 로컬 모델 사용하여 번역 진행")

        lines = merged_content.splitlines()
        translated_lines = []
        in_text_block = False           # 현재 텍스트 블록 안에 있는지
        current_text = []               # 현재 번역 대기 중인 텍스트 줄들

        for line in lines:
            stripped = line.strip()

            # 빈 줄 → 텍스트 블록 종료 → 번역 실행
            if not stripped:
                if current_text:
                    text_to_translate = "\n".join(current_text)
                    translated = translate_ja_to_ko(text_to_translate)
                    translated_lines.extend(translated.splitlines())
                    current_text = []
                translated_lines.append("")  # 빈 줄 유지 (SRT 구조)
                in_text_block = False
                continue

            # 자막 번호 줄 (숫자만 있는 줄)
            if re.match(r'^\d+$', stripped):
                if current_text:  # 이전 블록 번역
                    text_to_translate = "\n".join(current_text)
                    translated = translate_ja_to_ko(text_to_translate)
                    translated_lines.extend(translated.splitlines())
                    current_text = []
                translated_lines.append(line)
                in_text_block = False
                continue

            # 시간 줄 (--> 포함)
            if "-->" in stripped:
                translated_lines.append(line)
                in_text_block = True
                continue

            # 실제 텍스트 줄
            if in_text_block:
                current_text.append(line)
            else:
                translated_lines.append(line)  # 번호/시간 외 기타 줄 (드물게 있음)

        # 파일 끝에 남은 마지막 텍스트 블록 번역
        if current_text:
            text_to_translate = "\n".join(current_text)
            translated = translate_ja_to_ko(text_to_translate)
            translated_lines.extend(translated.splitlines())

        # 최종 번역 내용 조합
        translated_content = "\n".join(translated_lines).rstrip() + "\n"

        # 5. 한국어 자막 파일 저장
        output_path.write_text(translated_content, encoding="utf-8-sig")
        print(f"  → 한국어 자막 저장 완료: {output_path.name}")

    except Exception as e:
        print(f"  !!! 오류 발생: {e}")
        if backup_path.exists():
            print(f"  (참고: 백업 파일은 생성되었습니다 - {backup_path.name})")


# ────────────────────────────────────────────────────────────────
# 7. 프로그램 진입점
# ────────────────────────────────────────────────────────────────

def main():
    """
    프로그램 메인 함수
    명령줄 인자로 폴더 경로를 받아 모든 .srt 파일을 순차 처리
    """
    # 사용법 안내
    if len(sys.argv) != 2:
        print("사용법: python merge_and_translate_srt.py \"폴더경로\"")
        print("예시:")
        print('  python merge_and_translate_srt.py "C:/Subtitles"')
        sys.exit(1)

    # 입력 경로 변환 및 검증
    folder_path = Path(sys.argv[1]).resolve()

    if not folder_path.is_dir():
        print(f"오류: {folder_path} 는 존재하지 않거나 폴더가 아닙니다.")
        sys.exit(1)

    # 처리 대상 파일 목록 가져오기
    srt_files = get_srt_files(folder_path)

    if not srt_files:
        print("해당 폴더에 처리할 .srt 파일이 없습니다.")
        return

    print(f"발견된 .srt 파일 수: {len(srt_files)}\n")

    # 파일 하나씩 처리
    for srt_file in srt_files:
        process_srt_file(srt_file)
        print()  # 파일 간 구분용 빈 줄

    print("===== 모든 파일 처리 완료 =====")


if __name__ == "__main__":
    main()