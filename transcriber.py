"""
transcriber.py — faster-whisper 기반 영상 → SRT 자막 추출 모듈

일본어 성인 영상 특화 파라미터로 환각을 최소화하면서 조용한 대화도 감지한다.
핵심 설정:
  - condition_on_previous_text=False : 이전 구간 환각이 다음 구간으로 전파되는 것 차단
  - vad_filter=True                  : 배경음악·신음 등 비대화 구간 자동 제거
  - no_speech_threshold=0.5          : 기본(0.6)보다 낮게 — 조용한 대화도 음성으로 처리
  - initial_prompt                   : 일본어 대화 힌트로 비언어 소리 오역 억제
"""
from __future__ import annotations

import os
import site
import sys
from pathlib import Path
from typing import Optional

# pip으로 설치된 nvidia CUDA DLL(cublas64_12.dll 등)을 ctranslate2가 찾을 수 있도록
# faster_whisper import 전에 Windows DLL 검색 경로에 등록
if sys.platform == "win32":
    _nvidia_bin_candidates = [
        os.path.join(sp, "nvidia", "cublas", "bin")
        for sp in (site.getsitepackages() + [site.getusersitepackages()])
    ]
    for _bin in _nvidia_bin_candidates:
        if os.path.isdir(_bin):
            try:
                os.add_dll_directory(_bin)
            except Exception:
                pass

# 런타임 import — faster-whisper 미설치 환경에서도 모듈 로드 자체는 성공
try:
    from faster_whisper import WhisperModel
    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    FASTER_WHISPER_AVAILABLE = False

# ── 상수 ──────────────────────────────────────────────────────────────────────

MODEL_ID = "large-v3-turbo"

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".ts", ".m2ts"}

# VAD 파라미터: 조용한 환경 대화 감지와 신음 필터링의 균형
# threshold 0.25 — 기본(0.5)보다 낮아 소리 작은 대화도 통과, 0.2 이하는 신음 오인 위험
# min_silence_duration_ms 600 — 0.6초 침묵이면 자막 블록 분리 (기존 2초는 뭉침 원인)
VAD_PARAMETERS = {
    "threshold": 0.25,               # 음성 감지 임계값 (기본 0.5, 0.25는 조용한 대화 감지)
    "min_speech_duration_ms": 150,   # 150ms 미만 음성 무시 (기존 200ms→짧은 발화 감지 개선)
    "min_silence_duration_ms": 600,  # 600ms 침묵이면 구간 분리 (기존 2000ms→뭉침 해소)
    "max_speech_duration_s": 8.0,    # 한 VAD 청크 최대 8초 강제 상한 (10~20초 뭉침 방지)
    "speech_pad_ms": 400,            # 음성 앞뒤 여백 400ms — 인접 청크 오디오 중복 방지
}

# Whisper initial_prompt: 일본어 대화 컨텍스트 힌트
# 비언어 소리(신음)를 일본어 글자로 오역하는 것을 억제하는 효과
INITIAL_PROMPT = "日本語の会話。"  # "일본어 회화."


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _format_timestamp(seconds: float) -> str:
    """float 초 → SRT 타임스탬프 형식(HH:MM:SS,mmm) 변환"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds % 1) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _load_model(device: str = "cuda", compute_type: str = "float16") -> Optional["WhisperModel"]:
    """
    WhisperModel 로드. GPU 실패 시 CPU + int8로 자동 폴백.
    반환 None이면 transcribe_folder에서 단계 전체를 스킵한다.
    """
    try:
        model = WhisperModel(MODEL_ID, device=device, compute_type=compute_type)
        print(f"  모델 로드 완료: {MODEL_ID} ({device.upper()}, {compute_type})")
        return model
    except Exception as e:
        if device == "cuda":
            print(f"  GPU 로드 실패 ({e}), CPU로 재시도...")
            return _load_model(device="cpu", compute_type="int8")
        print(f"  !!! 모델 로드 실패: {e}")
        return None


# ── 공개 API ──────────────────────────────────────────────────────────────────

def _collect_segments(segments) -> tuple[list[str], int]:
    """세그먼트 generator를 SRT 라인 목록으로 변환. (lines, 다음_idx) 반환."""
    lines: list[str] = []
    idx = 1
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        start_ts = _format_timestamp(seg.start)
        end_ts = _format_timestamp(seg.end)
        lines.append(f"{idx}\n{start_ts} --> {end_ts}\n{text}\n")
        idx += 1
    return lines, idx


def get_video_files(folder_path: Path) -> list[Path]:
    """폴더를 재귀 탐색해 지원 확장자 영상 파일 목록을 정렬 반환"""
    return sorted(
        p for p in folder_path.rglob("*")
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    )


def has_srt(video_path: Path) -> bool:
    """동일 stem의 .srt 파일이 이미 존재하면 True (추출 스킵 판단용)"""
    return video_path.with_suffix(".srt").exists()


def transcribe_video(video_path: Path, model: "WhisperModel") -> Optional[Path]:
    """
    단일 영상 파일을 일본어로 추출해 .srt 파일로 저장.

    Returns:
        생성된 .srt Path, 또는 유효 세그먼트 없음/오류 시 None
    """
    srt_path = video_path.with_suffix(".srt")

    try:
        segments, info = model.transcribe(
            str(video_path),
            language="ja",

            # ── 환각 억제 핵심 파라미터 ──────────────────────────────────
            condition_on_previous_text=False,  # 이전 구간 환각 전파 차단
            no_speech_threshold=0.5,           # 기본(0.6)보다 낮게 — 조용한 대화도 음성 처리
            compression_ratio_threshold=2.4,   # 반복 압축비 높으면 환각 의심

            # ── 일본어 대화 컨텍스트 힌트 ────────────────────────────────
            initial_prompt=INITIAL_PROMPT,     # 비언어 소리 오역 억제 + 대화체 인식 향상

            # ── VAD (배경음악·신음 구간 자동 제거) ───────────────────────
            vad_filter=True,
            vad_parameters=VAD_PARAMETERS,

            # ── 추론 품질 ────────────────────────────────────────────────
            beam_size=5,
            temperature=[0.0, 0.2, 0.4, 0.6],  # 불확실 구간 temperature 순차 상승
            max_new_tokens=70,                  # 세그먼트당 최대 토큰 제한 (보조 뭉침 방지)
            word_timestamps=False,              # SRT 생성에 불필요
        )

        print(f"  감지 언어: {info.language} (확률 {info.language_probability:.2f})")

        lines, idx = _collect_segments(segments)

        # VAD 필터로 세그먼트가 전혀 없으면 VAD 없이 재시도
        if not lines:
            print("  VAD 필터 결과 세그먼트 없음 → VAD 비활성화 후 재시도...")
            segments2, _ = model.transcribe(
                str(video_path),
                language="ja",
                condition_on_previous_text=False,
                no_speech_threshold=0.5,
                compression_ratio_threshold=2.4,
                initial_prompt=INITIAL_PROMPT,
                vad_filter=False,
                beam_size=5,
                temperature=[0.0, 0.2, 0.4, 0.6],
                max_new_tokens=70,
                word_timestamps=False,
            )
            lines, idx = _collect_segments(segments2)

        if not lines:
            print("  경고: 유효 세그먼트 없음, SRT 파일 미생성")
            return None

        srt_path.write_text("\n".join(lines), encoding="utf-8-sig")
        print(f"  SRT 저장: {srt_path.name} ({idx - 1}개 세그먼트)")
        return srt_path

    except Exception as e:
        print(f"  !!! 추출 오류: {e}")
        return None


def transcribe_folder(folder_path: Path, skip: bool = False) -> list[Path]:
    """
    폴더 내 영상 파일을 탐색해 .srt가 없는 것만 자막 추출.

    Args:
        folder_path: 탐색할 폴더
        skip:        True면 즉시 빈 목록 반환 (--skip-transcribe 처리)

    Returns:
        성공적으로 생성된 .srt 파일 경로 목록
    """
    if skip:
        print("  자막 추출 단계 건너뜀 (--skip-transcribe)\n")
        return []

    if not FASTER_WHISPER_AVAILABLE:
        print("  경고: faster-whisper 미설치 — 자막 추출 단계를 건너뜁니다.")
        print("  설치: pip install faster-whisper\n")
        return []

    video_files = get_video_files(folder_path)
    targets = [v for v in video_files if not has_srt(v)]

    if not targets:
        if video_files:
            print(f"  영상 {len(video_files)}개 발견, 모두 .srt 존재 → 추출 스킵\n")
        else:
            print("  영상 파일 없음\n")
        return []

    print(f"  추출 대상: {len(targets)}개 / 전체 영상: {len(video_files)}개")

    # 모델은 루프 외부에서 1회만 로드
    model = _load_model()
    if model is None:
        print("  !!! 모델 로드 실패 — 자막 추출 단계를 건너뜁니다.\n")
        return []

    extracted: list[Path] = []
    active_model = model  # GPU → CPU 전환 시 교체

    for i, video in enumerate(targets, start=1):
        print(f"  [{i}/{len(targets)}] {video.name}")
        result = transcribe_video(video, active_model)

        # GPU cuBLAS 오류 등으로 None이 반환된 경우, CPU 모델로 전환 후 재시도
        if result is None and active_model is model:
            print("  GPU 추론 실패 감지 → CPU(int8) 모델로 전환합니다...")
            cpu_model = _load_model(device="cpu", compute_type="int8")
            if cpu_model is not None:
                active_model = cpu_model  # 이후 모든 파일도 CPU 사용
                print(f"  [{i}/{len(targets)}] {video.name} (CPU 재시도)")
                result = transcribe_video(video, active_model)

        if result is not None:
            extracted.append(result)

    return extracted
