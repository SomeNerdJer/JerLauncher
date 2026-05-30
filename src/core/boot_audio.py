from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pygame

try:
    from ffpyplayer.player import MediaPlayer
except ImportError:  # pragma: no cover
    MediaPlayer = None


class BootAudioPlayer:
    """Plays boot video audio via ffpyplayer, with mixer fallback after ffmpeg extract."""

    def __init__(self, video_path: Path, cache_dir: Path) -> None:
        self._video_path = video_path
        self._cache_dir = cache_dir
        self._ff_player: Any = None
        self._mixer_path: Path | None = None
        self._started = False
        self._initialized = False
        self._mode: str | None = None

    @property
    def available(self) -> bool:
        return self._mode is not None

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        if MediaPlayer is not None:
            self._try_ffpyplayer()
        if self._mode is None:
            self._try_mixer_extract()

    def _try_ffpyplayer(self) -> None:
        try:
            self._ff_player = MediaPlayer(
                str(self._video_path),
                {"paused": True},
            )
            self._mode = "ffpyplayer"
        except Exception:
            self._ff_player = None

    def _try_mixer_extract(self) -> None:
        if not pygame.mixer.get_init():
            try:
                pygame.mixer.init()
            except pygame.error:
                return

        audio_path = self._cache_dir / f"{self._video_path.stem}.ogg"
        if not audio_path.is_file():
            audio_path = self._extract_audio_ogg(audio_path)
        if audio_path is None or not audio_path.is_file():
            return

        self._mixer_path = audio_path
        self._mode = "mixer"

    def _extract_audio_ogg(self, output_path: Path) -> Path | None:
        try:
            import imageio_ffmpeg
        except ImportError:
            return None

        output_path.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(self._video_path),
                "-vn",
                "-acodec",
                "libvorbis",
                "-q:a",
                "6",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not output_path.is_file():
            return None
        return output_path

    def start(self) -> None:
        self._ensure_initialized()
        if self._started or self._mode is None:
            return
        self._started = True
        if self._mode == "ffpyplayer" and self._ff_player is not None:
            self._ff_player.set_pause(False)
            return
        if self._mode == "mixer" and self._mixer_path is not None:
            pygame.mixer.music.load(str(self._mixer_path))
            pygame.mixer.music.play()

    def pump(self) -> None:
        if not self._started or self._mode != "ffpyplayer" or self._ff_player is None:
            return
        self._ff_player.get_frame()

    def stop(self) -> None:
        if not self._started and self._ff_player is None and self._mixer_path is None:
            return
        self._started = False
        if self._mode == "ffpyplayer" and self._ff_player is not None:
            try:
                self._ff_player.set_pause(True)
                self._ff_player.close_player()
            except Exception:
                pass
            self._ff_player = None
        if self._mode == "mixer":
            pygame.mixer.music.stop()
        self._mode = None
        self._initialized = False
