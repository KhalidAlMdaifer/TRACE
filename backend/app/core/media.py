"""Reading an uploaded file: probe it, hash it, decode its audio.

ffmpeg and ffprobe run on untrusted files, so: fixed argument lists, no shell, a timeout."""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

SAMPLE_RATE = 4000


class MediaError(Exception):
    """The file cannot be used; `code` is machine-readable."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class MediaInfo:
    duration_s: float
    has_audio: bool
    codec: str | None
    sample_rate: int | None
    channels: int | None
    container: str | None

    def to_dict(self) -> dict:
        return asdict(self)


# An upload is one recording. ffmpeg may open local files only (no address in a crafted file
# is ever fetched), and a file that is really a list of other files is refused at the probe.
INPUT_GUARD = ["-protocol_whitelist", "file"]
PLAYLIST_FORMATS = {"hls", "applehttp", "concat", "dash", "sdp", "rtsp", "rtp", "lavfi", "tty"}


def probe(path, timeout_s: float = 30.0) -> MediaInfo:
    """ffprobe: duration and the first audio stream. Raises MediaError when the file is not
    media or has no audio."""
    path = Path(path)
    if not path.is_file():
        raise MediaError("not_found", f"no such file: {path.name}")
    cmd = ["ffprobe", "-v", "error", *INPUT_GUARD, "-print_format", "json", "-show_format", "-show_streams", str(path)]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        raise MediaError("probe_timeout", "the file took too long to inspect") from None
    if p.returncode != 0:
        raise MediaError("not_media", "this file is not audio or video that ffmpeg can read")
    meta = json.loads(p.stdout or b"{}")
    if PLAYLIST_FORMATS & set((meta.get("format", {}).get("format_name") or "").split(",")):
        raise MediaError("not_media", "this file is a playlist, not a recording")
    audio = [s for s in meta.get("streams", []) if s.get("codec_type") == "audio"]
    if not audio:
        raise MediaError("no_audio", "this file has no audio track")
    a, fmt = audio[0], meta.get("format", {})
    dur = fmt.get("duration") or a.get("duration")
    if dur is None:
        raise MediaError("not_media", "the length of this file could not be read")
    return MediaInfo(float(dur), True, a.get("codec_name"), int(a["sample_rate"]) if a.get("sample_rate") else None,
                     a.get("channels"), fmt.get("format_name"))


def sha256_file(path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            h.update(block)
    return h.hexdigest()


def decode_audio(path, sr: int = SAMPLE_RATE, timeout_s: float = 600.0) -> tuple[np.ndarray, int]:
    """Mono float32 at `sr` Hz: the ffmpeg command of dopplertrack.audio.load_audio, run here
    because the library call has no timeout. The whole recording is held in memory, about
    58 MB per hour."""
    cmd = ["ffmpeg", "-v", "error", "-nostdin", *INPUT_GUARD, "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr),
           "-f", "f32le", "-acodec", "pcm_f32le", "-"]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        raise MediaError("decode_timeout", "decoding the audio took too long") from None
    if p.returncode != 0 or not p.stdout:
        raise MediaError("decode_failed", "the audio could not be decoded")
    return np.frombuffer(p.stdout, dtype=np.float32).copy(), sr
