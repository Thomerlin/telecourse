"""Inferência determinística e conservadora de módulos/aulas."""
import re
from pathlib import Path

MODULE_RE = re.compile(r'(?<![A-Za-z0-9])(?:m[oó]d(?:ulo)?|module|unidade|unit|cap[ií]tulo|cap)[\s_.:#-]*0*(\d{1,3})(?!\d)', re.I)
LESSON_RE = re.compile(r'(?<![A-Za-z0-9])(?:aula|lesson|li[cç][aã]o|lecture|video|v[ií]deo)[\s_.:#-]*0*(\d{1,4})(?!\d)', re.I)


def media_info(message):
    document = getattr(message, 'document', None)
    if not document:
        return None
    mime = (document.mime_type or '').lower()
    if mime.startswith('video/'):
        kind = 'video'
    elif mime == 'application/pdf':
        kind = 'pdf'
    else:
        return None
    duration = 0
    for attr in (getattr(document, 'attributes', None) or []):
        if hasattr(attr, 'duration'):
            duration = int(attr.duration or 0)
            break
    filename = getattr(getattr(message, 'file', None), 'name', None) or ''
    return {'kind': kind, 'mime_type': mime, 'file_size': int(document.size or 0),
            'duration': duration, 'filename': filename[:240]}


def title_of(message, filename):
    caption = (getattr(message, 'raw_text', None) or '').strip()
    first = caption.splitlines()[0].strip() if caption else ''
    if first and len(first) <= 150:
        return first
    if filename:
        return Path(filename).stem[:150]
    return f'Aula {message.id}'


def propose(message, media):
    title = title_of(message, media['filename'])
    searchable = f"{media['filename']} {title}"
    module_match = MODULE_RE.search(searchable)
    lesson_match = LESSON_RE.search(searchable)
    module_number = int(module_match.group(1)) if module_match else None
    lesson_number = int(lesson_match.group(1)) if lesson_match else None
    topic = getattr(message, 'reply_to', None)
    topic_id = getattr(topic, 'reply_to_top_id', None) if topic else None
    return {
        **media, 'message_id': int(message.id), 'title': title,
        'proposed_module': f'Módulo {module_number:02d}' if module_number is not None else 'Aulas sem módulo',
        'module_number': module_number, 'lesson_number': lesson_number,
        'topic_id': topic_id,
        'uncertain': int(module_number is None or lesson_number is None),
    }


def organize(records):
    """Ordena módulos/aulas quando numerados, cronologia nas lacunas."""
    return sorted(records, key=lambda rec: (
        rec['module_number'] if rec['module_number'] is not None else 99999,
        rec['lesson_number'] if rec['lesson_number'] is not None else 99999,
        rec['message_id']))
