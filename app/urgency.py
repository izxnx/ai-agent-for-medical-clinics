from __future__ import annotations

import re

PATTERNS = [
    ('кровотеча', r'кровотеч\w*|кровит\w*|кров\s+(?:не\s+)?зупин'),
    ('раптовий набряк', r'раптов\w*.{0,35}(?:набряк|опух)|(?:набряк|опух)\w*.{0,35}раптов|ног\w*.{0,20}(?:раптов|різк).{0,20}(?:набряк|опух)|(?:набряк|опух)\w*.{0,30}(?:за\s+годин|швидко|сьогодні)'),
    ('зміна кольору ноги', r'побіл\w*|зблід\w*|посин\w*|син\w*|\bбіл(?:а|ий|е|і|ого|ою)\b'),
    ('похолодання або оніміння', r'похолод\w*|холодн\w*|онім\w*|занім\w*'),
    ('сильний або нестерпний біль', r'(?:нестерп\w*|різк\w*|сильн\w*|гостр\w*).{0,25}(?:бол|біл)\w*|(?:бол|біл)\w*.{0,25}(?:нестерп|різк|сильн|гостр)'),
    ('біль у грудях', r'(?:бол|біл)\w*.{0,25}груд|груд\w*.{0,25}(?:бол|біл)'),
    ('задишка', r'задиш\w*|важко\s+дих'),
    ('кашель із кров’ю', r'каш\w*.{0,20}кров'),
    ('непритомність або різка слабкість', r'непритом\w*|втрат\w*\s+свідом|різк\w*\s+слабк'),
    ('гострий біль у литці', r'(?:гостр\w*|різк\w*|сильн\w*|нестерп\w*).{0,25}(?:бол|біл)\w*.{0,30}лит|лит\w*.{0,30}(?:гостр|різк|сильн|нестерп)'),
    ('набряк однієї ноги', r'набряк\w*.{0,30}(?:одн\w*\s+ног|однієї\s+ног)|одн\w*\s+ног\w*.{0,30}набряк'),
    ('ознаки запалення вздовж вени', r'(?:почервон\w*|жар\w*|ущільнен\w*).{0,60}вен|вен\w*.{0,60}(?:почервон|жар|ущільнен)'),
    ('рана або виразка з ознаками інфекції', r'(?:ран\w*|вираз\w*).{0,50}(?:гно|почервон|червон)|(?:гно|почервон|червон).{0,50}(?:ран\w*|вираз\w*)'),
]


def _norm(text: str) -> str:
    text = text.lower().replace('’', "'").replace('ʼ', "'").replace('‘', "'")
    return re.sub(r'\s+', ' ', text).strip()


def find_urgent(text: str | None) -> list[str]:
    if not text:
        return []
    normalized = _norm(text)
    return [label for label, pattern in PATTERNS if re.search(pattern, normalized)]


def user_part(transcript: str | None) -> str:
    if not transcript:
        return ''
    # Vapi може надсилати репліки в одному рядку: "AI: ... User: ...".
    speaker_pattern = re.compile(r'(?im)(?<!\S)(User|Customer|Assistant|AI)\s*:\s*')
    speakers = list(speaker_pattern.finditer(transcript))
    if not speakers:
        return transcript.strip()
    selected = []
    for index, speaker in enumerate(speakers):
        if speaker.group(1).lower() not in {'user', 'customer'}:
            continue
        end = speakers[index + 1].start() if index + 1 < len(speakers) else len(transcript)
        text = transcript[speaker.end():end].strip()
        if text:
            selected.append(text)
    return '\n'.join(selected)
