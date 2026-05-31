"""
cloud/storage_service.py
-------------------------
Firebase Storage — DOCX dosya yükleme ve imzalı indirme URL üretimi.

Storage yapısı:
  exams/{userId}/{examId}/original.docx   ← orijinal sınav dosyası
  exams/{userId}/{examId}/answers.docx    ← üretilen cevap kağıdı
"""

from datetime import timedelta
from .firebase_service import get_bucket

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def upload_bytes(data: bytes, blob_path: str) -> str:
    """Bellekteki veriyi Storage'a yükler; blob_path döndürür."""
    blob = get_bucket().blob(blob_path)
    blob.upload_from_string(data, content_type=_DOCX)
    return blob_path


def upload_file(local_path: str, blob_path: str) -> str:
    """Disk üzerindeki dosyayı Storage'a yükler; blob_path döndürür."""
    blob = get_bucket().blob(blob_path)
    blob.upload_from_filename(local_path, content_type=_DOCX)
    return blob_path


def get_signed_url(blob_path: str, hours: int = 1) -> str:
    """İmzalı indirme URL'i üretir (varsayılan 1 saat geçerli)."""
    blob = get_bucket().blob(blob_path)
    return blob.generate_signed_url(
        expiration=timedelta(hours=hours),
        method="GET",
        version="v4",
    )


def original_path(user_id: str, exam_id: str) -> str:
    return f"exams/{user_id}/{exam_id}/original.docx"


def answers_path(user_id: str, exam_id: str) -> str:
    return f"exams/{user_id}/{exam_id}/answers.docx"
