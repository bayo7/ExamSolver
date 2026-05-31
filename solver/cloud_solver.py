"""
solver/cloud_solver.py
-----------------------
CLOUD_FUNCTION_URL ortam değişkeni tanımlıysa soruları Google Cloud
Function üzerinden çözer; aksi hâlde yerel solver'a devreder.

Cloud Function URL ayarlama (.env):
    CLOUD_FUNCTION_URL=https://us-central1-PROJE_ID.cloudfunctions.net/solve_question

Yerel Cloud Function testi:
    functions-framework --target=solve_question --port=8080
    CLOUD_FUNCTION_URL=http://localhost:8080
"""

import os
import time
import json
import logging
from typing import List, Dict, Any

import requests
from dotenv import load_dotenv

load_dotenv()

CLOUD_FUNCTION_URL = os.getenv("CLOUD_FUNCTION_URL", "").strip()
API_DELAY          = float(os.getenv("API_DELAY", "1.0"))
MAX_RETRIES        = int(os.getenv("MAX_RETRIES", "3"))

logger = logging.getLogger(__name__)


def _call_cloud(question: Dict[str, Any], provider: str) -> Dict[str, Any]:
    """Tek bir soruyu Cloud Function'a HTTP POST ile gönderir."""
    payload = {"question": question, "provider": provider}
    last_err = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(
                CLOUD_FUNCTION_URL,
                json=payload,
                timeout=90,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            data.setdefault("question_number", question.get("question_number"))
            data.setdefault("question_text",   question.get("question_text", "")[:120])
            return data
        except requests.exceptions.RequestException as exc:
            last_err = exc
            logger.warning(f"  [Cloud] Q{question.get('question_number')} deneme {attempt}/{MAX_RETRIES}: {exc}")
            time.sleep(API_DELAY * attempt)

    return {
        "question_number": question.get("question_number"),
        "question_text":   question.get("question_text", "")[:120],
        "answer":          "UNCERTAIN",
        "confidence":      0.0,
        "reason":          f"Cloud Function ulaşılamaz: {last_err}",
    }


def solve_questions_cloud(questions: List[Dict[str, Any]], provider: str) -> List[Dict[str, Any]]:
    """
    Tüm soru listesini Cloud Function üzerinden çözer.
    CLOUD_FUNCTION_URL tanımlı değilse yerel solver'a düşer.
    """
    if not CLOUD_FUNCTION_URL:
        logger.info("[CloudSolver] URL tanımlı değil → yerel solver kullanılıyor")
        from solver.ai_solver import solve_questions
        return solve_questions(questions)

    answers = []
    total   = len(questions)
    print(f"\n[CloudSolver] {total} soru → {CLOUD_FUNCTION_URL}")
    print(f"[CloudSolver] Provider: {provider.upper()}")
    print("─" * 50)

    for i, q in enumerate(questions, 1):
        print(f"  [{i:3}/{total}] Q{q['question_number']}...", end=" ", flush=True)
        result = _call_cloud(q, provider)
        answers.append(result)

        if result["answer"] == "UNCERTAIN":
            print("→ ⚠  UNCERTAIN")
        else:
            print(f"→ {result['answer']} (güven: {result.get('confidence', 0):.0%})")

        if i < total:
            time.sleep(API_DELAY)

    answered = sum(1 for a in answers if a.get("answer") != "UNCERTAIN")
    print(f"\n[CloudSolver] Tamamlandı: {answered}/{total} soru cevaplandı.")
    return answers
