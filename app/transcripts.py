"""Utilities for extracting caller turns from Retell transcripts."""

import re


_SPEAKER = re.compile(r"(?im)(?<!\S)(User|Customer|Assistant|Agent|AI)\s*:\s*")


def turns(transcript: str | None) -> list[tuple[bool, str]]:
    """Репліки по черзі: (True, текст) для пацієнта, (False, текст) для асистента."""
    if not transcript:
        return []
    speakers = list(_SPEAKER.finditer(transcript))
    result = []
    for index, speaker in enumerate(speakers):
        end = speakers[index + 1].start() if index + 1 < len(speakers) else len(transcript)
        text = " ".join(transcript[speaker.end() : end].split())
        if text:
            result.append((speaker.group(1).lower() in {"user", "customer"}, text))
    return result


def user_part(transcript: str | None) -> str:
    if not transcript:
        return ""
    speakers = list(_SPEAKER.finditer(transcript))
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
