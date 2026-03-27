import asyncio
import functools
import json
import logging
import shutil
import subprocess
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

# HLS segment duration in seconds
HLS_SEGMENT_TIME = 6
HLS_PLAYLIST_TYPE = "vod"

# Pre-processing caps before HLS generation
MAIN_MAX_WIDTH = 1980
MAIN_MAX_HEIGHT = 1080
LIBRAS_MAX_WIDTH = 854
LIBRAS_MAX_HEIGHT = 480

# Libras PIP defaults (bottom-right corner)
LIBRAS_SCALE = "iw*0.25"
LIBRAS_POSITION = "W-w-20:H-h-20"
LIBRAS_SCALE_OPTIONS = {"25": "iw*0.25", "35": "iw*0.35", "40": "iw*0.40"}


@functools.lru_cache(maxsize=1)
def detect_hwaccel() -> str:
    """
    Detect the best available hardware encoder.
    Returns 'nvenc', 'vaapi', or 'cpu'. Cached after first call.
    """
    try:
        r = subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "quiet",
                "-f",
                "lavfi",
                "-i",
                "nullsrc=s=64x64:d=0.1",
                "-c:v",
                "h264_nvenc",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            timeout=8,
        )
        if r.returncode == 0:
            logger.info("hwaccel: NVENC (NVIDIA GPU) detected")
            return "nvenc"
    except Exception:
        pass

    try:
        r = subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "quiet",
                "-vaapi_device",
                "/dev/dri/renderD128",
                "-f",
                "lavfi",
                "-i",
                "nullsrc=s=64x64:d=0.1",
                "-vf",
                "format=nv12,hwupload",
                "-c:v",
                "h264_vaapi",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            timeout=8,
        )
        if r.returncode == 0:
            logger.info("hwaccel: VAAPI (Intel/AMD GPU) detected")
            return "vaapi"
    except Exception:
        pass

    logger.info("hwaccel: no GPU found, using CPU (libx264)")
    return "cpu"


def _video_encode_args(hwaccel: str) -> list[str]:
    if hwaccel == "nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "23"]
    if hwaccel == "vaapi":
        return ["-c:v", "h264_vaapi", "-qp", "23"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"]


def _run(cmd: list[str], log_path: Path | None = None) -> subprocess.CompletedProcess:
    logger.debug("FFmpeg cmd: %s", " ".join(cmd))
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(result.stdout, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg failed (exit {result.returncode}):\n{result.stdout[-2000:]}")
    return result


def _hls_output_args(output_dir: Path, playlist_name: str = "index.m3u8") -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    return [
        "-hls_time",
        str(HLS_SEGMENT_TIME),
        "-hls_playlist_type",
        HLS_PLAYLIST_TYPE,
        "-hls_segment_filename",
        str(output_dir / "seg%03d.ts"),
        str(output_dir / playlist_name),
    ]


def _probe_streams(input_path: Path) -> list[dict]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        str(input_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return []
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return []
    return payload.get("streams", [])


def _has_alpha_channel(streams: list[dict]) -> bool:
    """Check if any video stream uses a pixel format with alpha."""
    alpha_fmts = {"yuva420p", "yuva444p", "yuva422p", "yuva444p10le", "rgba", "bgra", "argb", "abgr", "ya8"}
    for s in streams:
        if s.get("codec_type") == "video":
            pix_fmt = s.get("pix_fmt", "")
            if pix_fmt in alpha_fmts:
                return True
            # VP8/VP9 alpha is sometimes reported as yuv420p but with alpha side data
            codec = s.get("codec_name", "")
            if codec in ("vp8", "vp9") and "alpha" in s.get("codec_tag_string", "").lower():
                return True
    return False


def _pick_main_video_stream(streams: list[dict]) -> int:
    candidates: list[tuple[int, int, int]] = []
    for stream in streams:
        if stream.get("codec_type") != "video":
            continue
        if (stream.get("disposition") or {}).get("attached_pic") == 1:
            continue
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
        is_default = 1 if (stream.get("disposition") or {}).get("default") == 1 else 0
        candidates.append((is_default, width * height, int(stream.get("index") or 0)))
    if not candidates:
        return 0
    candidates.sort(reverse=True)
    return candidates[0][2]


def _pick_main_audio_stream(streams: list[dict]) -> int | None:
    candidates: list[tuple[int, int, int]] = []
    for stream in streams:
        if stream.get("codec_type") != "audio":
            continue
        idx = int(stream.get("index") or 0)
        is_default = 1 if (stream.get("disposition") or {}).get("default") == 1 else 0
        candidates.append((is_default, -idx, idx))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][2]


def _normalize_mp4(
    input_path: Path,
    output_path: Path,
    max_width: int,
    max_height: int,
    hw: str,
    audio_bitrate: str,
    log_path: Path | None = None,
    preserve_alpha: bool = False,
) -> None:
    # Cap dimensions, preserve aspect ratio, and force even output dimensions.
    vf = (
        f"scale={max_width}:{max_height}:force_original_aspect_ratio=decrease,"
        "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    )

    streams = _probe_streams(input_path)
    video_stream = _pick_main_video_stream(streams)
    audio_stream = _pick_main_audio_stream(streams)

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-map",
        f"0:{video_stream}",
    ]

    if audio_stream is not None:
        cmd.extend(["-map", f"0:{audio_stream}"])
    else:
        # Keep consistent output even when source has no audio track.
        cmd.extend(
            [
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-map",
                "1:a:0",
                "-shortest",
            ]
        )

    cmd.extend(
        [
            *_video_encode_args(hw),
            "-vf",
            vf,
            "-pix_fmt",
            "yuva420p" if preserve_alpha else "yuv420p",
            "-c:a",
            "aac",
            "-ac",
            "2",
            "-ar",
            "48000",
            "-b:a",
            audio_bitrate,
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    _run(cmd, log_path)


def preprocess_main_input(video_id: str, input_path: Path) -> Path:
    """
    Normalize the main source video before HLS processing.
    Output is capped to 1980x1080 while preserving aspect ratio.
    """
    output_dir = settings.video_processed_dir(video_id, "source")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "main_1080p.mp4"
    log_path = settings.video_logs_dir(video_id) / "main_norm.log"
    hw = detect_hwaccel()
    _normalize_mp4(
        input_path=input_path,
        output_path=output_path,
        max_width=MAIN_MAX_WIDTH,
        max_height=MAIN_MAX_HEIGHT,
        hw=hw,
        audio_bitrate="128k",
        log_path=log_path,
    )
    return output_path


def preprocess_libras_input(video_id: str, input_path: Path) -> Path:
    """
    Normalize Libras source before overlay to reduce processing cost.
    Preserves alpha channel if the input has one (e.g. VP9 alpha, ProRes 4444).
    """
    output_dir = settings.video_processed_dir(video_id, "source")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "libras_480p.mp4"
    log_path = settings.video_logs_dir(video_id) / "libras_norm.log"
    hw = detect_hwaccel()
    streams = _probe_streams(input_path)
    has_alpha = _has_alpha_channel(streams)
    _normalize_mp4(
        input_path=input_path,
        output_path=output_path,
        max_width=LIBRAS_MAX_WIDTH,
        max_height=LIBRAS_MAX_HEIGHT,
        hw=hw,
        audio_bitrate="96k",
        log_path=log_path,
        preserve_alpha=has_alpha,
    )
    return output_path


def extract_thumbnail(video_id: str, input_path: Path) -> Path:
    """Extract a representative frame for catalog thumbnail fallback."""
    output_dir = settings.video_covers_dir(video_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "auto-thumb.jpg"
    log_path = settings.video_logs_dir(video_id) / "thumb.log"

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        "00:00:02",
        "-i",
        str(input_path),
        "-frames:v",
        "1",
        "-q:v",
        "3",
        str(output_path),
    ]
    _run(cmd, log_path)
    return output_path


def process_original_hls(video_id: str, input_path: Path) -> Path:
    """Transcode main video to HLS, capped at 1080p."""
    output_dir = settings.video_processed_dir(video_id, "original")
    log_path = settings.video_logs_dir(video_id) / "original.log"
    hw = detect_hwaccel()

    vf_scale = "scale=-2:min(ih\\,1080)"
    if hw == "vaapi":
        cmd = [
            "ffmpeg",
            "-y",
            "-vaapi_device",
            "/dev/dri/renderD128",
            "-i",
            str(input_path),
            "-vf",
            f"{vf_scale},format=nv12,hwupload",
            *_video_encode_args(hw),
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            *_hls_output_args(output_dir),
        ]
    else:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            *_video_encode_args(hw),
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-vf",
            vf_scale,
            *_hls_output_args(output_dir),
        ]
    _run(cmd, log_path)
    return output_dir / "index.m3u8"


def process_libras_hls(
    video_id: str,
    main_input: Path,
    libras_input: Path,
    position: str = LIBRAS_POSITION,
    scale: str = LIBRAS_SCALE,
    pre_normalized: bool = False,
) -> Path:
    """
    Overlay Libras video (PIP) on main video and transcode to HLS.
    """
    output_dir = settings.video_processed_dir(video_id, "libras")
    log_path = settings.video_logs_dir(video_id) / "libras.log"
    hw = detect_hwaccel()

    if pre_normalized:
        libras_norm = libras_input
    else:
        libras_norm = libras_input.parent / (libras_input.stem + "_480p.mp4")
        if not libras_norm.exists():
            _normalize_mp4(
                input_path=libras_input,
                output_path=libras_norm,
                max_width=LIBRAS_MAX_WIDTH,
                max_height=LIBRAS_MAX_HEIGHT,
                hw=hw,
                audio_bitrate="96k",
                log_path=settings.video_logs_dir(video_id) / "libras_norm.log",
            )

    # format=auto preserves alpha channel if present in Libras input (e.g. VP9/VP8 alpha, ProRes 4444)
    filter_complex = f"[1:v]scale={scale}:-2,format=yuva420p[libras];[0:v][libras]overlay={position}:format=auto[out]"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(main_input),
        "-i",
        str(libras_norm),
        "-filter_complex",
        filter_complex,
        "-map",
        "[out]",
        "-map",
        "0:a",
        *_video_encode_args(hw),
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        *_hls_output_args(output_dir),
    ]
    _run(cmd, log_path)
    return output_dir / "index.m3u8"


def process_ad_hls(video_id: str, main_input: Path, ad_input: Path) -> Path:
    """Mix original audio with AD audio track and transcode to HLS, capped at 1080p."""
    output_dir = settings.video_processed_dir(video_id, "ad")
    log_path = settings.video_logs_dir(video_id) / "ad.log"

    filter_complex = (
        "[0:a]volume=1.0[orig];"
        "[1:a]volume=0.8[ad];"
        "[orig][ad]amix=inputs=2:duration=first:dropout_transition=2[aout]"
    )

    hw = detect_hwaccel()
    vf_scale = "scale=-2:min(ih\\,1080)"
    if hw == "vaapi":
        cmd = [
            "ffmpeg",
            "-y",
            "-vaapi_device",
            "/dev/dri/renderD128",
            "-i",
            str(main_input),
            "-i",
            str(ad_input),
            "-filter_complex",
            filter_complex,
            "-map",
            "0:v",
            "-map",
            "[aout]",
            "-vf",
            f"{vf_scale},format=nv12,hwupload",
            *_video_encode_args(hw),
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            *_hls_output_args(output_dir),
        ]
    else:
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(main_input),
            "-i",
            str(ad_input),
            "-filter_complex",
            filter_complex,
            "-map",
            "0:v",
            "-map",
            "[aout]",
            *_video_encode_args(hw),
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-vf",
            vf_scale,
            *_hls_output_args(output_dir),
        ]
    _run(cmd, log_path)
    return output_dir / "index.m3u8"


def process_subtitle_vtt(video_id: str, srt_input: Path) -> Path:
    """Convert SRT to WebVTT."""
    output_dir = settings.video_subtitles_dir(video_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "subtitle.vtt"

    if srt_input.suffix.lower() == ".vtt":
        shutil.copy2(srt_input, output_path)
        return output_path

    log_path = settings.video_logs_dir(video_id) / "subtitle.log"
    cmd = ["ffmpeg", "-y", "-i", str(srt_input), str(output_path)]
    _run(cmd, log_path)
    return output_path


async def run_processing_pipeline(
    video_id: str,
    main_input: Path,
    libras_input: Path | None,
    ad_input: Path | None,
    subtitle_input: Path | None,
    on_progress=None,
) -> dict:
    """
    Run the full processing pipeline in a thread pool.
    Returns dict with paths to generated outputs.
    """
    loop = asyncio.get_event_loop()
    results = {}

    async def run_in_thread(fn, *args):
        return await loop.run_in_executor(None, fn, *args)

    results["hls_original"] = await run_in_thread(process_original_hls, video_id, main_input)
    if on_progress:
        await on_progress("original_done")

    if libras_input:
        results["hls_libras"] = await run_in_thread(
            process_libras_hls, video_id, main_input, libras_input, LIBRAS_POSITION, LIBRAS_SCALE, True
        )
        if on_progress:
            await on_progress("libras_done")

    if ad_input:
        results["hls_ad"] = await run_in_thread(process_ad_hls, video_id, main_input, ad_input)
        if on_progress:
            await on_progress("ad_done")

    if subtitle_input:
        results["subtitle_vtt"] = await run_in_thread(process_subtitle_vtt, video_id, subtitle_input)
        if on_progress:
            await on_progress("subtitle_done")

    return results
