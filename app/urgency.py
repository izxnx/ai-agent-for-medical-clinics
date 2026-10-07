from __future__ import annotations
import re
import unicodedata

PATTERNS = [
 ('сильна кровотеча',r'кровотеч\w*|кров\s+(?:не\s+)?зупин'),
 ('раптовий набряк ноги',r'(?:раптов\w*\s+)?набряк\w*'),
 ('зміна кольору ноги',r'побіл\w*|зблід\w*|посин\w*|син\w*'),
 ('похолодання або оніміння',r'похолод\w*|холодн\w*|онім\w*|занім\w*'),
 ('нестерпний біль',r'(?:нестерп\w*|різк\w*|сильн\w*)\s+бол\w*'),
 ('біль у грудях',r'бол\w*\s+(?:у|в)\s+груд'),
 ('задишка',r'задиш\w*|важко\s+дих'),
 ('кашель з кров’ю',r'кашл\w*.{0,20}кров'),
 ('непритомність або слабкість',r'непритом\w*|втрат\w*\s+свідом|різк\w*\s+слабк'),
 ('гострий біль у литці',r'(?:гостр\w*|різк\w*)\s+бол\w*.{0,30}литц|литц\w*.{0,30}бол'),
 ('набряк однієї ноги',r'набряк\w*.{0,30}(?:одн\w*\s+ног|однієї\s+ног)|одн\w*\s+ног\w*.{0,30}набряк'),
 ('почервоніння або жар уздовж вени',r'почервон\w*|жар\w*.{0,20}вен|вен\w*.{0,20}жар|ущільнен\w*.{0,30}вен'),
 ('рана або виразка з гноєм',r'ран\w*|вираз\w*.{0,50}гно|гно\w*.{0,30}ран|вираз'),
]
def _norm(text: str) -> str:
    text=text.lower().replace('’',"'").replace('ʼ',"'").replace('ё','е').replace('ґ','г')
    return re.sub(r'\s+',' ',text)
def find_urgent(text: str | None) -> list[str]:
    if not text:
        return []
    normalized=_norm(text)
    return [label for label,pattern in PATTERNS if re.search(pattern,normalized)]
def user_part(transcript: str | None) -> str:
    if not transcript:
        return ''
    # TODO(verify-vapi): підтвердити формат transcript у реальних звітах Vapi.
    lines=transcript.splitlines()
    selected=[]
    current=False
    has_prefix=False
    for line in lines:
        match=re.match(r'^\s*(User|Customer):\s*(.*)$',line,re.I)
        if match:
            has_prefix=True
            current=True
            selected.append(match.group(2))
        elif re.match(r'^\s*(?:Assistant|AI):\s*',line,re.I):
            current=False
        elif current:
            selected.append(line)
    return '\n'.join(selected).strip() if has_prefix else transcript.strip()
