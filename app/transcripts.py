"""Utilities for extracting caller turns from Vapi transcripts."""

import re


def user_part(transcript: str | None) -> str:
    if not transcript:
        return ""
    speaker_pattern = re.compile(r"(?im)(?<!\S)(User|Customer|Assistant|AI)\s*:\s*")
    speakers = list(speaker_pattern.finditer(transcript))
    if not speakers:
        return transcript.strip()

    selected = []
    for index, speaker in enumerate(speakers):
        if speaker.group(1).lower() not in {"user", "customer"}:
            continue
        end = speakers[index + 1].start() if index + 1 < len(speakers) else len(transcript)
        text = transcript[speaker.end() : end].strip()
        if text:
            selected.append(text)
    return "\n".join(selected)
