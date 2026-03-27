import asyncio
import logging
import subprocess
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

# HLS segment duration in seconds
HLS_SEGMENT_TIME = 6
HLS_PLAYLIST_TYPE = "vod"

# Libras PIP defaults (bottom-right corner, 25% of video width)
LIBRAS_SCALE = "iw*0.25"
LIBRAS_POSITION = "W-w-20:H-h-20"  # 20px margin from bottom-right


def _run(cmd: list[str], log_path: Path | None = None) -> subprocess.CompletedProcess:
    """Run a subprocess command, optionally writing output to a log file."""
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
        "-hls_time", str(HLS_SEGMENT_TIME),
        "-hls_playlist_type", HLS_PLAYLIST_TYPE,
        "-hls_segment_filename", str(output_dir / "seg%03d.ts"),
        str(output_dir / playlist_name),
    ]


def process_original_hls(video_id: str, input_path: Path) -> Path:
    """Transcode main video to HLS."""
    output_dir = settings.video_processed_dir(video_id, "original")
    log_path = settings.video_logs_dir(video_id) / "original.log"

    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-vf", "scale=-2:720",
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
) -> Path:
    """Overlay Libras video (PIP) on main video and transcode to HLS."""
    output_dir = settings.video_processed_dir(video_id, "libras")
    log_path = settings.video_logs_dir(video_id) / "libras.log"

    # Scale libras to 25% width of main, then overlay bottom-right
    filter_complex = (
        f"[1:v]scale={scale}:-2[libras];"
        f"[0:v][libras]overlay={position}[out]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(main_input),
        "-i", str(libras_input),
        "-filter_complex", filter_complex,
        "-map", "[out]", "-map", "0:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        *_hls_output_args(output_dir),
    ]
    _run(cmd, log_path)
    return output_dir / "index.m3u8"


def process_ad_hls(video_id: str, main_input: Path, ad_input: Path) -> Path:
    """Mix original audio with AD audio track and transcode to HLS."""
    output_dir = settings.video_processed_dir(video_id, "ad")
    log_path = settings.video_logs_dir(video_id) / "ad.log"

    # Mix: original audio at 100% + AD at 80%
    filter_complex = (
        "[0:a]volume=1.0[orig];"
        "[1:a]volume=0.8[ad];"
        "[orig][ad]amix=inputs=2:duration=first:dropout_transition=2[aout]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(main_input),
        "-i", str(ad_input),
        "-filter_complex", filter_complex,
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-vf", "scale=-2:720",
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
        import shutil
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

    # Always process original
    results["hls_original"] = await run_in_thread(process_original_hls, video_id, main_input)
    if on_progress:
        await on_progress("original_done")

    if libras_input:
        results["hls_libras"] = await run_in_thread(
            process_libras_hls, video_id, main_input, libras_input
        )
        if on_progress:
            await on_progress("libras_done")

    if ad_input:
        results["hls_ad"] = await run_in_thread(process_ad_hls, video_id, main_input, ad_input)
        if on_progress:
            await on_progress("ad_done")

    if subtitle_input:
        results["subtitle_vtt"] = await run_in_thread(
            process_subtitle_vtt, video_id, subtitle_input
        )
        if on_progress:
            await on_progress("subtitle_done")

    return results
