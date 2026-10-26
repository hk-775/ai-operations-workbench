"""Build bounded, cached narration files with Amazon Polly through the AWS CLI.

This is an explicit authoring operation. The shipped demo never calls AWS.
Requires an existing authorized AWS session, AWS CLI, ffmpeg, and ffprobe.
No credentials, account IDs, or provider response metadata are published.
"""
import argparse
import hashlib
import html
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(arguments):
    result = subprocess.run(arguments, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(f"{Path(arguments[0]).name} failed; exit {result.returncode}")
    return result.stdout


def duration(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                      "-of", "default=noprint_wrappers=1:nokey=1", str(path)]))


def speech(text):
    value = html.escape(text)
    for name, alias in (("AxonLLM", "Axon L L M"), ("Ostiari", "os tee ah ree")):
        value = value.replace(name, f'<sub alias="{alias}">{name}</sub>')
    return '<speak><prosody rate="95%">'+value+'</prosody></speak>'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthesize", action="store_true",
                        help="Explicitly authorize the bounded narration generation")
    parser.add_argument("--max-characters", type=int, default=25000)
    args = parser.parse_args()
    document = json.loads((ROOT/"docs/demo/storyboard.json").read_text())
    media = ROOT/"web/media/narration"
    build = ROOT/"artifacts/demo-build"
    media.mkdir(parents=True, exist_ok=True)
    build.mkdir(parents=True, exist_ok=True)
    entries = [(key, text, False) for key, text in document["narration"].items()]
    entries += [("scene-"+scene["id"], scene["text"], True) for scene in document["scenes"]]
    estimate = sum(len(speech(text))*(2 if marks else 1) for _, text, marks in entries)
    if estimate > args.max_characters or args.max_characters > 25000:
        raise ValueError("Narration exceeds the 25,000-character authoring limit")
    print(f"Narration plan: {len(entries)} clips; at most {estimate} submitted characters, including caption timing requests.", flush=True)
    usage_path = build/"synthesis-usage.json"
    used = json.loads(usage_path.read_text())["submitted_characters"] if usage_path.exists() else 0

    def synthesize(arguments, ssml):
        nonlocal used
        if not args.synthesize:
            raise ValueError("Missing authored audio. Review storyboard.json and run with --synthesize.")
        if used + len(ssml) > args.max_characters:
            raise ValueError("Cumulative narration authoring limit reached")
        used += len(ssml)
        usage_path.write_text(json.dumps({"submitted_characters": used}))
        return run(arguments)

    clips, manifest, speech_marks = {}, [], {}
    for key, text, need_marks in entries:
        if not re.fullmatch(r"[a-z0-9-]+", key):
            raise ValueError("Invalid narration ID")
        ssml = speech(text)
        fingerprint = hashlib.sha256(json.dumps(
            [ssml, document["voice"], document["engine"], "mp3", "24000"],
            ensure_ascii=False).encode()).hexdigest()
        target = media/(key+".mp3")
        marks_path = build/(key+".marks.jsonl")
        receipt = build/(key+".receipt.json")
        cached = receipt.exists() and json.loads(receipt.read_text()).get("input_sha256") == fingerprint
        request = build/(key+".ssml")
        request.write_text(ssml)
        common = ["aws", "polly", "synthesize-speech", "--region", document["region"],
                  "--engine", document["engine"], "--voice-id", document["voice"],
                  "--text-type", "ssml", "--text", "file://"+str(request), "--output", "json"]
        if not (cached and target.exists()):
            raw = build/(key+".raw.mp3")
            synthesize([*common, "--output-format", "mp3", "--sample-rate", "24000", str(raw)], ssml)
            run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw),
                 "-af", "loudnorm=I=-16:TP=-1.5:LRA=7", "-ar", "48000", "-ac", "1",
                 "-codec:a", "libmp3lame", "-b:a", "128k", str(target)])
            receipt.write_text(json.dumps({"input_sha256": fingerprint}))
        if need_marks and not (cached and marks_path.exists()):
            synthesize([*common, str(marks_path), "--output-format", "json",
                        "--speech-mark-types", "sentence"], ssml)
        if need_marks:
            speech_marks[key.removeprefix("scene-")] = [
                {"time": mark["time"], "type": "sentence",
                 "value": html.unescape(re.sub(r"<[^>]*>", "", mark["value"]))}
                for line in marks_path.read_text().splitlines()
                if (mark := json.loads(line))["type"] == "sentence"
            ]
        seconds = duration(target)
        if not 1 < seconds < 65:
            raise ValueError(f"Unexpected narration duration for {key}")
        item = {"src": "media/narration/"+target.name, "duration": round(seconds, 3), "text": text}
        clips[key] = item
        manifest.append({"id": key, "input_sha256": fingerprint,
                         "audio_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                         "duration_seconds": round(seconds, 3)})
        print(f"Ready: {key} ({seconds:.1f}s)", flush=True)
    (ROOT/"web/architecture-narration.js").write_text(
        "'use strict';\n// Authored narration; no runtime synthesis or cloud calls.\n"
        "window.WorkbenchNarration = "+json.dumps(clips, ensure_ascii=False, indent=2)+";\n")
    (ROOT/"docs/demo/audio-provenance.json").write_text(json.dumps({
        "service": "Amazon Polly", "voice": document["voice"], "engine": document["engine"],
        "source": "docs/demo/storyboard.json", "synthetic_voice": True,
        "clips": manifest,
    }, indent=2)+"\n")
    (ROOT/"docs/demo/speech-marks.json").write_text(
        json.dumps(speech_marks, ensure_ascii=False, indent=2)+"\n")
    print("Bundled narration and provenance are ready. Temporary requests stay under ignored artifacts/.")


if __name__ == "__main__":
    main()
