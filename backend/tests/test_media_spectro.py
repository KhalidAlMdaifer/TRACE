import numpy as np
import pytest

from app.core import media, spectro, synth


def test_probe_reads_the_wav(case3):
    info = media.probe(case3.wav)
    assert info.has_audio and info.sample_rate == synth.SAMPLE_RATE
    assert abs(info.duration_s - synth.DURATION_S) < 0.5


def test_probe_rejects_a_file_with_no_audio(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("not a recording")
    with pytest.raises(media.MediaError):
        media.probe(p)


def test_playlists_are_refused(case3, tmp_path):
    """A playlist is a text file that tells ffmpeg to open other files or addresses. An
    upload must be one recording, so anything of that kind is turned away at the probe."""
    hls = tmp_path / "clip.m3u8"
    hls.write_text(f"#EXTM3U\n#EXT-X-TARGETDURATION:1800\n#EXTINF:1800,\n{case3.wav}\n#EXT-X-ENDLIST\n")
    with pytest.raises(media.MediaError) as e:
        media.probe(hls)
    assert e.value.code == "not_media"
    concat = tmp_path / "list.wav"                                   # the name does not decide: ffmpeg looks at the content
    concat.write_text(f"ffconcat version 1.0\nfile '{case3.wav}'\n")
    with pytest.raises(media.MediaError) as e:
        media.probe(concat)
    assert e.value.code == "not_media"
    # and both commands may open local files only
    assert media.INPUT_GUARD == ["-protocol_whitelist", "file"]


def test_sha256_is_stable(case3):
    h = media.sha256_file(case3.wav)
    assert len(h) == 64 and h == media.sha256_file(case3.wav)


def test_decode_gives_mono_4k_float32(case3):
    x, sr = media.decode_audio(case3.wav)
    assert sr == 4000 and x.dtype == np.float32 and len(x) == synth.DURATION_S * 4000


def test_build_writes_plain_arrays(case3):
    for name in ("S.npy", "t.npy", "f.npy", "burst.npy"):
        assert (case3.case_dir / name).exists()
    S = np.load(case3.case_dir / "S.npy", mmap_mode="r")
    assert S.dtype == np.float32 and S.shape == (840, len(case3.sp.t))
    assert 40 <= case3.sp.f[0] < 41 and 449 < case3.sp.f[-1] <= 450


def test_load_slice_matches_the_whole(case3):
    part = spectro.load(case3.case_dir, 200.0, 400.0)
    whole = case3.sp.crop(200.0, 400.0)
    assert np.array_equal(part.t, whole.t) and np.array_equal(part.S, whole.S)
    assert part.t[0] >= 200.0 and part.t[-1] <= 400.0


def test_matrix_is_a_small_uint8_grid(case3):
    m = spectro.matrix(case3.case_dir, 200.0, 400.0, 80.0, 180.0, cols=120, rows=40)
    grid = np.frombuffer(m["data"], dtype=np.uint8).reshape(m["rows"], m["cols"])
    assert grid.shape == (40, 120)
    assert grid.max() > 100            # the flyover's tone is in this window
    assert np.median(grid) < 60        # and the noise floor stays low, so the tone stands out
    wide = spectro.matrix(case3.case_dir, 0.0, 1800.0, 40.0, 450.0, cols=180, rows=90)
    wide = np.frombuffer(wide["data"], dtype=np.uint8).reshape(90, 180)
    assert wide.max() > 150 and np.median(wide) < 70      # still true for the whole recording at once
    # zoomed right in, each cell is still averaged over two seconds, so the floor stays low
    close = spectro.matrix(case3.case_dir, 280.0, 340.0, 40.0, 450.0, cols=180, rows=120)
    close = np.frombuffer(close["data"], dtype=np.uint8).reshape(120, 180)
    assert close.max() > 240 and np.median(close) < 75 and np.quantile(close, 0.97) < 165      # before: median 97, 97th percentile near 185
    # asking for more cells than the data has still answers with the asked shape
    tiny = spectro.matrix(case3.case_dir, 300.0, 302.0, 100.0, 102.0, cols=50, rows=20)
    assert len(tiny["data"]) == 50 * 20
