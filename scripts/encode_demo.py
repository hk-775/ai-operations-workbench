"""Encode captured Workbench scenes, authored narration, captions, and chapters.

Run after record_demo.mjs. Requires ffmpeg/ffprobe; no network access.
Intermediate captures stay in ignored artifacts/demo-build/.
"""
import hashlib
import html
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "artifacts/demo-build"
MEDIA = ROOT / "web/media"


def run(*arguments):
    result = subprocess.run(arguments, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{arguments[0]} failed: {result.stderr[-2000:]}")
    return result.stdout


def probe(path):
    return json.loads(run("ffprobe", "-v", "error", "-show_format", "-show_streams",
                          "-of", "json", str(path)))


def timestamp(seconds, separator="."):
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02}{separator}{milliseconds:03}"


def narration_start(path):
    """Locate the first visible sync marker, independent of capture tail padding."""
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-an",
         "-vf", "fps=30,crop=8:8:4:4,scale=1:1:flags=area,format=rgb24",
         "-f", "rawvideo", "pipe:1"], capture_output=True, check=True)
    for index in range(0, len(result.stdout), 3):
        red, green, blue = result.stdout[index:index+3]
        if red > 180 and blue > 180 and green < 80:
            return index / 3 / 30
    raise ValueError("Capture has no synchronization marker; record it again")


def main():
    storyboard = json.loads((ROOT / "docs/demo/storyboard.json").read_text())
    capture = json.loads((BUILD / "capture.json").read_text())
    scenes = capture["scenes"]
    if [s["id"] for s in scenes] != [s["id"] for s in storyboard["scenes"]]:
        raise ValueError("A complete, ordered capture is required")
    if capture["unexpected_requests"] or capture["model_calls_during_capture"]:
        raise ValueError("Capture exceeded its evidence boundary")
    output = BUILD / "encoded"
    output.mkdir(exist_ok=True)
    chapters, captions, total = [], [], 0.0
    video_files, audio_files = [], []
    ffmpeg = ("ffmpeg", "-hide_banner", "-loglevel", "error", "-y")
    for index, (scene, story) in enumerate(zip(scenes, storyboard["scenes"], strict=True)):
        scene_id, length = scene["id"], scene["duration"]
        if not re.fullmatch(r"[a-z0-9-]+", scene_id):
            raise ValueError("Invalid scene ID")
        raw = Path(scene["raw_video"])
        raw_seconds = float(probe(raw)["format"]["duration"])
        start = narration_start(raw)
        if raw_seconds < start + length - 0.15:
            raise ValueError(f"Incomplete captured scene: {scene_id}")
        video = output / f"{index:02}-{scene_id}.mp4"
        audio = output / f"{index:02}-{scene_id}.wav"
        # Browser capture can pad its tail. Anchor to the visible start marker,
        # then cover only that temporary corner square with the header's white.
        run(*ffmpeg, "-ss", f"{start:.6f}", "-i", str(raw),
            "-an", "-vf", "setpts=PTS-STARTPTS,drawbox=x=0:y=0:w=18:h=18:color=white:t=fill,scale=1920:1080:flags=lanczos,setsar=1,fps=30,tpad=stop_mode=clone:stop_duration=0.2",
            "-frames:v", str(round(length*30)), "-c:v", "libx264", "-preset", "medium", "-crf", "22",
            "-pix_fmt", "yuv420p", "-video_track_timescale", "90000", "-threads", "4", str(video))
        run(*ffmpeg, "-i", str(MEDIA / f"narration/scene-{scene_id}.mp3"),
            "-af", "apad", "-t", str(length), "-ar", "48000", "-ac", "1",
            "-c:a", "pcm_s16le", str(audio))
        video_files.append(video.name)
        audio_files.append(audio.name)
        chapters.append({"id": scene_id, "title": scene["title"], "start": round(total, 3),
                         "end": round(total + length, 3), "text": story["text"],
                         "chapter": story["chapter"], "color": story["color"]})
        for mark_index, mark in enumerate(scene["marks"]):
            start = mark["time"] / 1000
            end = (scene["marks"][mark_index+1]["time"] / 1000
                   if mark_index + 1 < len(scene["marks"]) else scene["narration_duration"])
            text = html.unescape(re.sub(r"<[^>]*>", "", mark["value"]))
            if not 0 <= start < end <= length:
                raise ValueError(f"Invalid caption timing: {scene_id}")
            captions.append((total + start, total + end, text))
        total += length
        print(f"Encoded {scene_id}; narration starts at raw frame {round(start*30)}", flush=True)
    video_list, audio_list = output / "video.txt", output / "audio.txt"
    video_list.write_text("".join(f"file '{name}'\n" for name in video_files))
    audio_list.write_text("".join(f"file '{name}'\n" for name in audio_files))
    vtt = "WEBVTT\n\n" + "\n\n".join(
        f"{timestamp(start)} --> {timestamp(end)}\n{text}" for start, end, text in captions) + "\n"
    srt = "\n\n".join(
        f"{index}\n{timestamp(start, ',')} --> {timestamp(end, ',')}\n{text}"
        for index, (start, end, text) in enumerate(captions, 1)) + "\n"
    (MEDIA / "workbench-demo.vtt").write_text(vtt)
    (MEDIA / "workbench-demo.srt").write_text(srt)
    metadata = output / "chapters.txt"
    metadata.write_text(";FFMETADATA1\ntitle=AI Operations Workbench — narrated demo\n"
                        "comment=Fictional cases; saved model responses; synthetic narration.\n" +
                        "".join("[CHAPTER]\nTIMEBASE=1/1000\n"
                                f"START={round(chapter['start']*1000)}\n"
                                f"END={round(chapter['end']*1000)}\n"
                                f"title={chapter['title']}\n" for chapter in chapters))
    run(*ffmpeg, "-f", "concat", "-safe", "1", "-i", str(video_list),
        "-f", "concat", "-safe", "1", "-i", str(audio_list),
        "-i", str(MEDIA / "workbench-demo.srt"), "-i", str(metadata),
        "-map", "0:v:0", "-map", "1:a:0", "-map", "2:s:0", "-map_metadata", "3",
        "-map_chapters", "3", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
        "-c:s", "mov_text", "-metadata:s:s:0", "language=eng",
        "-disposition:s:0", "0", "-movflags", "+faststart", "-t", f"{total:.6f}",
        str(MEDIA / "workbench-demo.mp4"))
    run(*ffmpeg, "-f", "concat", "-safe", "1", "-i", str(audio_list),
        "-i", str(metadata), "-map_metadata", "1", "-map", "0:a:0",
        "-c:a", "libmp3lame", "-b:a", "160k", str(MEDIA / "workbench-demo.mp3"))
    run(*ffmpeg, "-ss", "3", "-i", str(MEDIA / "workbench-demo.mp4"),
        "-frames:v", "1", "-update", "1", str(MEDIA / "workbench-demo-poster.png"))
    transcript = "# AI Operations Workbench — narrated demo\n\n"
    transcript += ("Approximately four minutes. Stock synthetic narration: Amazon Polly neural, Joanna.\n"
                   "The video captures the actual local authenticated UI with fictional support cases,\n"
                   "saved model responses, and an isolated PostgreSQL workspace. No new model calls.\n"
                   "Architecture motion illustrates service relationships.\n\n")
    for chapter in chapters:
        transcript += (f"## {timestamp(chapter['start'])[:8]} · {chapter['title']}\n\n"
                       f"{chapter['text']}\n\n")
    transcript = transcript.rstrip() + "\n"
    (ROOT / "docs/demo/TRANSCRIPT.md").write_text(transcript)
    (MEDIA / "workbench-demo-transcript.txt").write_text(transcript)
    # Only portable public facts go in the shipped manifest.
    manifest = {
        "title": storyboard["title"], "duration_seconds": round(total, 3),
        "base_commit": capture["base_commit"], "dimensions": [1920, 1080], "fps": 30,
        "capture": capture["capture"], "model_calls_during_capture": 0,
        "synchronization": capture["synchronization"],
        "synthetic_voice": True, "voice": capture["voice"],
        "evidence": {"recording": "data/model-comparison.json", "tickets": 24,
                     "task_runs": 72, "captured_calls": 144,
                     "api_estimate_usd": "0.088074750",
                     "recording_sha256": hashlib.sha256(
                         (ROOT / "data/model-comparison.json").read_bytes()).hexdigest(),
                     "limits": "Saved support comparison, not current model performance or provider billing."},
        "chapters": chapters,
        "files": {name: {"sha256": hashlib.sha256((MEDIA / name).read_bytes()).hexdigest(),
                         "bytes": (MEDIA / name).stat().st_size}
                  for name in ("workbench-demo.mp4", "workbench-demo.mp3",
                               "workbench-demo.vtt", "workbench-demo.srt",
                               "workbench-demo-poster.png", "workbench-demo-transcript.txt")},
    }
    (ROOT / "docs/demo/manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    (ROOT / "web/demo-manifest.js").write_text(
        "'use strict';\nwindow.WorkbenchDemo = " +
        json.dumps({"duration": round(total, 3), "chapters": chapters}, ensure_ascii=False, indent=2) + ";\n")
    print(f"Ready: {total:.1f}s · 1080p MP4 · MP3 · captions · transcript · chapters", flush=True)


if __name__ == "__main__":
    main()
