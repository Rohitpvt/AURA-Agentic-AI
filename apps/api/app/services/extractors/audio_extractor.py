"""Deterministic Audio Header and Metadata Parser (AURA-602).

Supports:
- WAV (.wav) via Python standard library wave module
- MP3 (.mp3) via pure-Python ID3 / MPEG frame header parsing
- M4A (.m4a) via MP4 container atom/box header inspection
- Safe metadata extraction: duration, sample rate, channels, bitrate
- No STT / Speech transcription in AURA-602 (STT is explicitly deferred to Phase 7)
- Zero external binary or cloud speech dependencies ($0.00 cost)
"""

import io
from pathlib import Path
import struct
from typing import Any, Dict, List, Optional, Set
import wave

from app.core.logging import logger
from app.schemas.file import ExtractedContentItem, NormalizedExtractionResult
from app.services.extractors.base import BaseExtractor


class AudioExtractor(BaseExtractor):
    """Isolated audio metadata inspector extracting duration, sample rate, and channels without STT."""

    PARSER_NAME = "audio_extractor"
    PARSER_VERSION = "1.0.0"

    SUPPORTED_EXTENSIONS: Set[str] = {".mp3", ".wav", ".m4a"}
    SUPPORTED_MIMES: Set[str] = {
        "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/mp4", "audio/m4a"
    }

    async def extract(
        self,
        file_path: Path,
        filename: str,
        mime_type: str,
        ext: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> NormalizedExtractionResult:
        """Parse audio container headers to extract timing and format metadata."""
        options = options or {}
        max_bytes = options.get("max_text_bytes", self.MAX_EXTRACTED_BYTES)
        warnings: List[str] = []
        security_flags: List[str] = []
        content_items: List[ExtractedContentItem] = []
        metadata: Dict[str, Any] = {}

        normalized_ext = ext.lower()

        try:
            raw_bytes = file_path.read_bytes()
            if len(raw_bytes) < 12:
                return self.build_result(
                    filename=filename,
                    mime_type=mime_type,
                    ext=ext,
                    status="failed",
                    extracted_text="",
                    content_items=[],
                    error_message="Audio file is too small or header is truncated.",
                    max_bytes=max_bytes,
                )

            if normalized_ext == ".wav":
                metadata = self._parse_wav(raw_bytes)
            elif normalized_ext in [".mp3", ".mpeg"]:
                metadata = self._parse_mp3(raw_bytes)
            elif normalized_ext in [".m4a", ".mp4"]:
                metadata = self._parse_m4a(raw_bytes)
            else:
                metadata = {"format": normalized_ext.lstrip(".")}

            metadata["size_bytes"] = len(raw_bytes)

            dur = metadata.get("duration_seconds", 0.0)
            sr = metadata.get("sample_rate_hz", "unknown")
            ch = metadata.get("channels", "unknown")
            fmt = metadata.get("format", normalized_ext.lstrip(".").upper())

            summary_lines = [
                f"Audio Metadata for {filename}:",
                f"- Format: {fmt}",
                f"- Duration: {dur:.2f} seconds ({dur/60:.2f} minutes)",
                f"- Sample Rate: {sr} Hz",
                f"- Channels: {ch}",
            ]
            if "bitrate_kbps" in metadata:
                summary_lines.append(f"- Bitrate: {metadata['bitrate_kbps']} kbps")

            extracted_text = "\n".join(summary_lines)

            content_items.append(
                ExtractedContentItem(
                    index=0,
                    text=extracted_text,
                    item_type="audio_metadata",
                    source_location={"format": fmt, "duration_seconds": dur},
                )
            )

            warnings.append("Note: Speech-to-text (STT) transcription is deferred to Phase 7. Only audio metadata was extracted.")

            return self.build_result(
                filename=filename,
                mime_type=mime_type,
                ext=ext,
                status="extracted",
                extracted_text=extracted_text,
                content_items=content_items,
                metadata=metadata,
                warnings=warnings,
                security_flags=security_flags,
                max_bytes=max_bytes,
            )

        except Exception as e:
            logger.error(f"AudioExtractor: Failed to parse audio {filename}: {e}", exc_info=True)
            return self.build_result(
                filename=filename,
                mime_type=mime_type,
                ext=ext,
                status="failed",
                extracted_text="",
                content_items=[],
                error_message=f"Audio metadata parsing failure: {str(e)}",
                max_bytes=max_bytes,
            )

    def _parse_wav(self, raw_bytes: bytes) -> Dict[str, Any]:
        """Parse standard RIFF/WAVE header via wave module."""
        with wave.open(io.BytesIO(raw_bytes), "rb") as wf:
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            sample_rate = wf.getframerate()
            n_frames = wf.getnframes()
            duration = n_frames / float(sample_rate) if sample_rate > 0 else 0.0

            return {
                "format": "WAV",
                "channels": channels,
                "sample_width_bytes": sample_width,
                "sample_rate_hz": sample_rate,
                "frame_count": n_frames,
                "duration_seconds": round(duration, 3),
            }

    def _parse_mp3(self, raw_bytes: bytes) -> Dict[str, Any]:
        """Parse MP3 ID3 header and first MPEG audio frame header."""
        meta = {"format": "MP3", "channels": 2, "sample_rate_hz": 44100, "duration_seconds": 0.0}
        offset = 0

        # Skip ID3v2 tag if present
        if raw_bytes.startswith(b"ID3") and len(raw_bytes) >= 10:
            # ID3 size is encoded in bytes 6..9 as 7-bit syncsafe integers
            id3_size = (
                ((raw_bytes[6] & 0x7F) << 21)
                | ((raw_bytes[7] & 0x7F) << 14)
                | ((raw_bytes[8] & 0x7F) << 7)
                | (raw_bytes[9] & 0x7F)
            )
            offset = 10 + id3_size

        # Find first sync word 0xFFE / 0xFFF
        bitrate_table = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
        sr_table = [44100, 48000, 32000, 0]

        bitrate = 128
        sample_rate = 44100

        for i in range(offset, min(offset + 4096, len(raw_bytes) - 4)):
            if raw_bytes[i] == 0xFF and (raw_bytes[i + 1] & 0xE0) == 0xE0:
                # Found MPEG Frame Header
                b2 = raw_bytes[i + 2]
                br_idx = (b2 >> 4) & 0x0F
                sr_idx = (b2 >> 2) & 0x03
                if br_idx < len(bitrate_table) and bitrate_table[br_idx] > 0:
                    bitrate = bitrate_table[br_idx]
                if sr_idx < len(sr_table) and sr_table[sr_idx] > 0:
                    sample_rate = sr_table[sr_idx]
                break

        # Estimate duration based on bitrate and file length
        audio_data_bytes = max(len(raw_bytes) - offset, 0)
        dur = (audio_data_bytes * 8) / (bitrate * 1000) if bitrate > 0 else 0.0

        meta["sample_rate_hz"] = sample_rate
        meta["bitrate_kbps"] = bitrate
        meta["duration_seconds"] = round(dur, 2)
        return meta

    def _parse_m4a(self, raw_bytes: bytes) -> Dict[str, Any]:
        """Parse MP4/M4A container ISO atoms for 'moov' / 'mvhd' duration info."""
        meta = {"format": "M4A/AAC", "channels": 2, "sample_rate_hz": 44100, "duration_seconds": 0.0}
        offset = 0

        try:
            while offset < len(raw_bytes) - 8:
                atom_size, atom_type = struct.unpack(">I4s", raw_bytes[offset : offset + 8])
                if atom_size == 0:
                    break

                if atom_type == b"moov":
                    # Scan inside moov for mvhd
                    moov_data = raw_bytes[offset + 8 : offset + atom_size]
                    mvhd_idx = moov_data.find(b"mvhd")
                    if mvhd_idx != -1 and mvhd_idx + 24 <= len(moov_data):
                        # mvhd structure: 4 bytes version/flags, 4 bytes create, 4 bytes mod, 4 bytes timescale, 4 bytes duration
                        header_start = mvhd_idx + 4
                        version = moov_data[header_start]
                        if version == 0:
                            timescale, duration = struct.unpack(">II", moov_data[header_start + 12 : header_start + 20])
                            if timescale > 0:
                                meta["duration_seconds"] = round(duration / timescale, 2)
                                meta["sample_rate_hz"] = timescale
                    break

                offset += atom_size
        except Exception:
            pass

        return meta
