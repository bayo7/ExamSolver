"""
cloud/firestore_db.py
----------------------
Firestore CRUD — kullanıcı sınav geçmişi.

Koleksiyon şeması:
  exams/{examId}
    userId          : string
    filename        : string
    provider        : string  (google | anthropic | openai)
    status          : string  (processing | completed | error)
    totalQuestions  : int
    answeredQuestions: int
    uploadedAt      : timestamp
    solvedAt        : timestamp | null
    answers         : array   (görüntü verisi olmadan)
    outputFilename  : string | null
    errorMsg        : string | null
"""

from google.cloud.firestore_v1 import SERVER_TIMESTAMP
from .firebase_service import get_db


def save_exam_start(user_id: str, filename: str, provider: str, total: int) -> str:
    """Yeni 'processing' durumunda sınav kaydı oluşturur; exam_id döndürür."""
    db = get_db()
    ref = db.collection("exams").document()
    ref.set({
        "userId":            user_id,
        "filename":          filename,
        "provider":          provider,
        "status":            "processing",
        "totalQuestions":    total,
        "answeredQuestions": 0,
        "uploadedAt":        SERVER_TIMESTAMP,
        "solvedAt":          None,
        "answers":           [],
        "outputFilename":    None,
        "errorMsg":          None,
    })
    return ref.id


def finish_exam(exam_id: str, answers: list, output_filename: str):
    """Çözümleri Firestore'a kaydeder; status='completed' yapar."""
    db = get_db()
    answered = sum(1 for a in answers if a.get("answer") != "UNCERTAIN")

    # Görüntü verisini (base64) çıkar — Firestore 1 MB belge limiti
    clean_answers = [
        {k: v for k, v in a.items() if k not in ("images",)}
        for a in answers
    ]

    db.collection("exams").document(exam_id).update({
        "status":            "completed",
        "answeredQuestions": answered,
        "answers":           clean_answers,
        "outputFilename":    output_filename,
        "solvedAt":          SERVER_TIMESTAMP,
    })


def fail_exam(exam_id: str, error: str):
    """Sınavı hata durumuna alır."""
    get_db().collection("exams").document(exam_id).update({
        "status":   "error",
        "errorMsg": error,
    })


def list_exams(user_id: str) -> list:
    """Kullanıcının son 30 sınavını (cevapsız) döndürür."""
    db = get_db()
    docs = (
        db.collection("exams")
        .where("userId", "==", user_id)
        .order_by("uploadedAt", direction="DESCENDING")
        .limit(30)
        .stream()
    )
    result = []
    for doc in docs:
        d = doc.to_dict()
        d["examId"] = doc.id
        d.pop("answers", None)   # liste görünümünde detay gereksiz
        _timestamps_to_str(d)
        result.append(d)
    return result


def get_exam(exam_id: str, user_id: str) -> dict | None:
    """Tek sınavı (cevaplarıyla birlikte) döndürür; sahiplik kontrolü yapar."""
    doc = get_db().collection("exams").document(exam_id).get()
    if not doc.exists:
        return None
    d = doc.to_dict()
    if d.get("userId") != user_id:
        return None
    d["examId"] = doc.id
    _timestamps_to_str(d)
    return d


def _timestamps_to_str(d: dict):
    for key in ("uploadedAt", "solvedAt"):
        val = d.get(key)
        if val and hasattr(val, "isoformat"):
            d[key] = val.isoformat()
        else:
            d[key] = None
