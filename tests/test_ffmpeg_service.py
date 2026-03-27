import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.services import ffmpeg_service as ffmpeg
from app.config import settings


def make_fake_run(returncode=0, stdout="ok"):
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    return result


# ── _run ──────────────────────────────────────────────────────────────────────

def test_run_success(tmp_path):
    with patch("subprocess.run", return_value=make_fake_run(0, "all good")) as mock_sub:
        result = ffmpeg._run(["ffmpeg", "-version"])
        assert result.returncode == 0


def test_run_failure():
    with patch("subprocess.run", return_value=make_fake_run(1, "error output")):
        with pytest.raises(RuntimeError, match="FFmpeg failed"):
            ffmpeg._run(["ffmpeg", "-bad"])


def test_run_writes_log(tmp_path):
    log = tmp_path / "test.log"
    with patch("subprocess.run", return_value=make_fake_run(0, "log content")):
        ffmpeg._run(["ffmpeg", "-version"], log_path=log)
    assert log.read_text() == "log content"


# ── _hls_output_args ──────────────────────────────────────────────────────────

def test_hls_output_args_creates_dir(tmp_path):
    out_dir = tmp_path / "hls_out"
    args = ffmpeg._hls_output_args(out_dir)
    assert out_dir.exists()
    assert str(out_dir / "index.m3u8") in args
    assert str(out_dir / "seg%03d.ts") in args


def test_hls_output_args_custom_playlist(tmp_path):
    out_dir = tmp_path / "hls"
    args = ffmpeg._hls_output_args(out_dir, playlist_name="custom.m3u8")
    assert str(out_dir / "custom.m3u8") in args


# ── process_original_hls ──────────────────────────────────────────────────────

def test_process_original_hls(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")
    input_path = tmp_path / "main.mp4"
    input_path.write_bytes(b"fake")

    with patch("app.services.ffmpeg_service._run") as mock_run:
        mock_run.return_value = make_fake_run()
        result = ffmpeg.process_original_hls("vid1", input_path)

    assert result.name == "index.m3u8"
    assert "original" in str(result)
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "ffmpeg" in cmd
    assert str(input_path) in cmd


# ── process_libras_hls ────────────────────────────────────────────────────────

def test_process_libras_hls(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")
    main = tmp_path / "main.mp4"
    libras = tmp_path / "libras.mp4"
    main.write_bytes(b"fake")
    libras.write_bytes(b"fake")

    with patch("app.services.ffmpeg_service._run") as mock_run:
        mock_run.return_value = make_fake_run()
        result = ffmpeg.process_libras_hls("vid1", main, libras)

    assert result.name == "index.m3u8"
    assert "libras" in str(result)
    # Two _run calls: first normalizes libras to 480p, second does the overlay
    assert mock_run.call_count == 2
    norm_cmd, overlay_cmd = mock_run.call_args_list[0][0][0], mock_run.call_args_list[1][0][0]
    assert str(libras) in norm_cmd          # normalization uses original libras
    assert "480p" in norm_cmd[-1]           # output is the _480p.mp4 file
    assert str(main) in overlay_cmd         # overlay uses main + normalized libras
    assert "480p" in " ".join(overlay_cmd)  # overlay uses the 480p version
    assert "-filter_complex" in overlay_cmd


def test_process_libras_hls_custom_position(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")
    main = tmp_path / "main.mp4"
    libras = tmp_path / "libras.mp4"
    main.write_bytes(b"fake")
    libras.write_bytes(b"fake")

    with patch("app.services.ffmpeg_service._run") as mock_run:
        mock_run.return_value = make_fake_run()
        result = ffmpeg.process_libras_hls("vid1", main, libras, position="0:0", scale="iw*0.3")

    # call_args is the last call (overlay); check it contains position/scale
    overlay_cmd = mock_run.call_args_list[-1][0][0]
    assert "0:0" in " ".join(overlay_cmd)
    assert "iw*0.3" in " ".join(overlay_cmd)


# ── process_ad_hls ────────────────────────────────────────────────────────────

def test_process_ad_hls(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")
    main = tmp_path / "main.mp4"
    ad = tmp_path / "ad.mp3"
    main.write_bytes(b"fake")
    ad.write_bytes(b"fake")

    with patch("app.services.ffmpeg_service._run") as mock_run:
        mock_run.return_value = make_fake_run()
        result = ffmpeg.process_ad_hls("vid1", main, ad)

    assert result.name == "index.m3u8"
    assert "ad" in str(result)
    cmd = mock_run.call_args[0][0]
    assert "amix" in " ".join(cmd)


# ── process_subtitle_vtt ──────────────────────────────────────────────────────

def test_process_subtitle_vtt_from_srt(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")
    srt = tmp_path / "sub.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n")

    with patch("app.services.ffmpeg_service._run") as mock_run:
        mock_run.return_value = make_fake_run()
        result = ffmpeg.process_subtitle_vtt("vid1", srt)

    assert result.name == "subtitle.vtt"
    mock_run.assert_called_once()


def test_process_subtitle_vtt_already_vtt(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")
    vtt = tmp_path / "sub.vtt"
    vtt.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHello\n")

    with patch("app.services.ffmpeg_service._run") as mock_run:
        result = ffmpeg.process_subtitle_vtt("vid1", vtt)

    mock_run.assert_not_called()
    assert result.name == "subtitle.vtt"
    assert result.read_text().startswith("WEBVTT")


# ── run_processing_pipeline ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_processing_pipeline_all(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")

    fake_manifest = tmp_path / "index.m3u8"
    fake_vtt = tmp_path / "subtitle.vtt"

    with patch("app.services.ffmpeg_service.process_original_hls", return_value=fake_manifest), \
         patch("app.services.ffmpeg_service.process_libras_hls", return_value=fake_manifest), \
         patch("app.services.ffmpeg_service.process_ad_hls", return_value=fake_manifest), \
         patch("app.services.ffmpeg_service.process_subtitle_vtt", return_value=fake_vtt):

        results = await ffmpeg.run_processing_pipeline(
            video_id="vid1",
            main_input=tmp_path / "main.mp4",
            libras_input=tmp_path / "libras.mp4",
            ad_input=tmp_path / "ad.mp3",
            subtitle_input=tmp_path / "sub.srt",
        )

    assert "hls_original" in results
    assert "hls_libras" in results
    assert "hls_ad" in results
    assert "subtitle_vtt" in results


@pytest.mark.asyncio
async def test_run_processing_pipeline_original_only(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")
    fake_manifest = tmp_path / "index.m3u8"

    with patch("app.services.ffmpeg_service.process_original_hls", return_value=fake_manifest):
        results = await ffmpeg.run_processing_pipeline(
            video_id="vid1",
            main_input=tmp_path / "main.mp4",
            libras_input=None,
            ad_input=None,
            subtitle_input=None,
        )

    assert "hls_original" in results
    assert "hls_libras" not in results
    assert "hls_ad" not in results
    assert "subtitle_vtt" not in results


@pytest.mark.asyncio
async def test_run_processing_pipeline_with_progress_callback(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "weplayer")
    fake_manifest = tmp_path / "index.m3u8"
    progress_calls = []

    async def on_progress(event):
        progress_calls.append(event)

    with patch("app.services.ffmpeg_service.process_original_hls", return_value=fake_manifest):
        await ffmpeg.run_processing_pipeline(
            video_id="vid1",
            main_input=tmp_path / "main.mp4",
            libras_input=None,
            ad_input=None,
            subtitle_input=None,
            on_progress=on_progress,
        )

    assert "original_done" in progress_calls
