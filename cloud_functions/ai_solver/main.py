"""
cloud_functions/ai_solver/main.py
-----------------------------------
Google Cloud Function: AI Soru Çözücü (HTTP trigger)

DAĞITIM:
    gcloud functions deploy solve_question \
        --runtime python312 \
        --trigger-http \
        --allow-unauthenticated \
        --region us-central1 \
        --memory 512MB \
        --timeout 120s \
        --set-env-vars LLM_PROVIDER=google,GOOGLE_API_KEY=AIza...,API_DELAY=1,MAX_RETRIES=3 \
        --entry-point solve_question \
        --source .

YEREL TEST:
    pip install functions-framework
    functions-framework --target=solve_question --port=8080
    # Sonra .env'e: CLOUD_FUNCTION_URL=http://localhost:8080

İSTEK FORMATI (POST JSON):
    {
      "question": {
        "question_number": 1,
        "question_text": "...",
        "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
        "images": [{"data": "<base64>", "media_type": "image/png"}]
      },
      "provider": "google"   // google | anthropic | openai
    }

YANIT:
    {"answer": "B", "confidence": 0.95, "reason": "...",
     "question_number": 1, "question_text": "..."}
"""

import os
import re
import json
import base64
import logging

import functions_framework
from dotenv import load_dotenv

load_dotenv()

LLM_PROVIDER      = os.getenv("LLM_PROVIDER", "google").lower()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")
GOOGLE_API_KEY    = os.getenv("GOOGLE_API_KEY", "")
MAX_RETRIES       = int(os.getenv("MAX_RETRIES", "3"))

logger = logging.getLogger(__name__)

_CORS_HEADERS = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Access-Control-Max-Age":       "3600",
}


# ── Prompt builder ────────────────────────────────────────────────────

def _build_prompt(question: dict) -> str:
    lines = [
        f"Question {question['question_number']}:",
        question.get("question_text", ""),
        "",
    ]
    options = {k: v for k, v in question.get("options", {}).items() if not k.endswith("_images")}
    for letter in ["A", "B", "C", "D"]:
        if letter in options:
            lines.append(f"{letter}) {options[letter]}")
    lines += [
        "",
        "Analyze the question carefully. If there are images, use them.",
        'Respond ONLY in JSON: {"answer": "B", "confidence": 0.95, "reason": "one sentence"}',
        "The answer field must be exactly one of: A B C D",
    ]
    return "\n".join(lines)


# ── Answer extractor ──────────────────────────────────────────────────

def _extract(raw: str) -> dict:
    raw = raw.strip()
    try:
        cleaned = re.sub(r"```json\s*|\s*```", "", raw).strip()
        s, e = cleaned.find("{"), cleaned.rfind("}") + 1
        if s != -1 and e > s:
            d = json.loads(cleaned[s:e])
            ans = str(d.get("answer", "")).upper().strip()
            if ans in ("A", "B", "C", "D"):
                return {"answer": ans, "confidence": float(d.get("confidence", 0.9)),
                        "reason": str(d.get("reason", ""))}
    except Exception:
        pass

    for pat in [r"answer[:\s]+([A-D])\b", r"\b([A-D])\s+is correct", r"option\s+([A-D])\b"]:
        m = re.search(pat, raw, re.IGNORECASE)
        if m:
            return {"answer": m.group(1).upper(), "confidence": 0.7, "reason": raw[:200]}

    m = re.search(r"\b([A-D])\b", raw)
    if m:
        return {"answer": m.group(1).upper(), "confidence": 0.5, "reason": raw[:200]}

    return {"answer": "UNCERTAIN", "confidence": 0.0, "reason": f"Parse error: {raw[:100]}"}


# ── Provider calls ────────────────────────────────────────────────────

def _google(question: dict) -> dict:
    from google import genai
    from google.genai import types

    client   = genai.Client(api_key=GOOGLE_API_KEY)
    contents = []
    for img in question.get("images", []):
        contents.append(
            types.Part.from_bytes(data=base64.b64decode(img["data"]), mime_type=img["media_type"])
        )
    contents.append(_build_prompt(question))
    resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=contents,
        config=types.GenerateContentConfig(max_output_tokens=512, temperature=0.1),
    )
    return _extract(resp.text)


def _anthropic(question: dict) -> dict:
    import anthropic
    client  = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    content = []
    for img in question.get("images", []):
        content.append({"type": "image",
                         "source": {"type": "base64", "media_type": img["media_type"], "data": img["data"]}})
    content.append({"type": "text", "text": _build_prompt(question)})
    resp = client.messages.create(model="claude-opus-4-6", max_tokens=512,
                                  messages=[{"role": "user", "content": content}])
    return _extract(resp.content[0].text)


def _openai(question: dict) -> dict:
    from openai import OpenAI
    client  = OpenAI(api_key=OPENAI_API_KEY)
    content = []
    for img in question.get("images", []):
        content.append({"type": "image_url",
                         "image_url": {"url": f"data:{img['media_type']};base64,{img['data']}", "detail": "high"}})
    content.append({"type": "text", "text": _build_prompt(question)})
    resp = client.chat.completions.create(model="gpt-4o", max_tokens=512,
                                          messages=[{"role": "user", "content": content}])
    return _extract(resp.choices[0].message.content)


_SOLVERS = {"google": _google, "anthropic": _anthropic, "openai": _openai}


# ── Cloud Function entry point ────────────────────────────────────────

@functions_framework.http
def solve_question(request):
    """HTTP trigger: tek bir MCQ sorusunu çözer."""

    # CORS preflight
    if request.method == "OPTIONS":
        return ("", 204, _CORS_HEADERS)

    try:
        body     = request.get_json(silent=True) or {}
        question = body.get("question")
        provider = body.get("provider", LLM_PROVIDER).lower()

        if not question:
            return (
                json.dumps({"error": "'question' alanı zorunlu"}),
                400,
                {**_CORS_HEADERS, "Content-Type": "application/json"},
            )

        solver = _SOLVERS.get(provider, _google)
        result = solver(question)
        result["question_number"] = question.get("question_number")
        result["question_text"]   = question.get("question_text", "")[:120]

        return (
            json.dumps(result, ensure_ascii=False),
            200,
            {**_CORS_HEADERS, "Content-Type": "application/json"},
        )

    except Exception as exc:
        logger.exception("solve_question hata")
        return (
            json.dumps({"error": str(exc), "answer": "UNCERTAIN", "confidence": 0.0}),
            500,
            {**_CORS_HEADERS, "Content-Type": "application/json"},
        )
