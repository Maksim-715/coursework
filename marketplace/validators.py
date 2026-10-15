from pathlib import Path
from django.core.exceptions import ValidationError


def validate_portfolio_attachment(upload):
    if upload.size > 10 * 1024 * 1024:
        raise ValidationError('Размер материала не должен превышать 10 МБ.')
    extension = Path(upload.name).suffix.lower()
    signatures = {
        '.pdf': lambda data: data.startswith(b'%PDF-'),
        '.png': lambda data: data.startswith(b'\x89PNG\r\n\x1a\n'),
        '.jpg': lambda data: data.startswith(b'\xff\xd8\xff'),
        '.jpeg': lambda data: data.startswith(b'\xff\xd8\xff'),
        '.webp': lambda data: data.startswith(b'RIFF') and data[8:12] == b'WEBP',
    }
    try:
        position = upload.tell()
        upload.seek(0)
        header = upload.read(16)
        upload.seek(position)
    except (OSError, ValueError):
        raise ValidationError('Не удалось прочитать материал.')
    if extension not in signatures or not signatures[extension](header):
        raise ValidationError('Загрузите PDF, PNG, JPEG или WebP с соответствующим содержимым.')
