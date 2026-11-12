"""Inspect MP4 tracks and decode representative video frames using OpenCV."""
import argparse
import json
import struct
from pathlib import Path


def boxes(stream, start, end):
    offset = start
    while offset + 8 <= end:
        stream.seek(offset)
        header = stream.read(8)
        if len(header) != 8:
            raise ValueError("Truncated MP4 box header")
        size, kind = struct.unpack(">I4s", header)
        header_size = 8
        if size == 1:
            size = struct.unpack(">Q", stream.read(8))[0]
            header_size = 16
        elif size == 0:
            size = end - offset
        if size < header_size or offset + size > end:
            raise ValueError("Invalid or truncated MP4 box")
        yield kind, offset + header_size, offset + size
        offset += size
    if offset != end:
        raise ValueError("Trailing incomplete MP4 box")


def inspect_tracks(path):
    tracks = []
    with path.open("rb") as stream:
        for kind, start, end in boxes(stream, 0, path.stat().st_size):
            if kind != b"moov":
                continue
            for kind, a, b in boxes(stream, start, end):
                if kind != b"trak":
                    continue
                track = {}
                for kind, c, d in boxes(stream, a, b):
                    if kind != b"mdia":
                        continue
                    for kind, e, f in boxes(stream, c, d):
                        if kind == b"hdlr":
                            stream.seek(e + 8)
                            track["type"] = stream.read(4).decode("ascii")
                        elif kind == b"mdhd":
                            stream.seek(e)
                            version = stream.read(1)[0]
                            stream.seek(e + (20 if version == 1 else 12))
                            scale = struct.unpack(">I", stream.read(4))[0]
                            duration = struct.unpack(">Q" if version == 1 else ">I", stream.read(8 if version == 1 else 4))[0]
                            track["duration_seconds"] = duration / scale
                tracks.append(track)
    if not {"soun", "vide"}.issubset({t.get("type") for t in tracks}):
        raise ValueError("A complete video and audio track pair was not found")
    return tracks


def inspect(path):
    tracks = inspect_tracks(path)
    import cv2
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValueError("Video decoder could not open the file")
        duration = next(t["duration_seconds"] for t in tracks if t.get("type") == "vide")
        samples = []
        for seconds in (0, duration / 2, max(0, duration - 2)):
            capture.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000)
            ok, frame = capture.read()
            if not ok or frame is None:
                raise ValueError(f"Video frame decode failed at {seconds:.1f}s")
            samples.append({"seconds": round(seconds, 3), "width": frame.shape[1], "height": frame.shape[0]})
    finally:
        capture.release()
    return {"file": path.name, "bytes": path.stat().st_size, "tracks": tracks, "decoded_samples": samples, "audio_decode_checked": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    report = inspect(args.file)
    args.file.with_suffix(".validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
