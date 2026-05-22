"""
solver/ai_solver.py
-------------------
Parse edilmiş soruları Multimodal LLM API'ye gönderir,
cevapları (A/B/C/D) ve açıklamaları döner.

Desteklenen modeller:
  - claude-3-5-sonnet  (Anthropic, vision destekli)
  - gemini-2.5-flash   (Google, vision destekli)
  - gpt-4o             (OpenAI, vision destekli)

Model seçimi .env dosyasındaki LLM_PROVIDER ile yapılır.
"""

import os
import re
import time
import json
from typing import List, Dict, Any

from dotenv import load_dotenv
load_dotenv()

# ─────────────────────────────────────────────
# Hangi provider kullanılacak?
# .env → LLM_PROVIDER=anthropic | openai | google
# ─────────────────────────────────────────────
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").lower()

# API key'leri .env'den oku
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")
GOOGLE_API_KEY    = os.getenv("GOOGLE_API_KEY", "")

# Rate limit için bekleme süresi (saniye)
API_DELAY = float(os.getenv("API_DELAY", "1.0"))

# Kaç kez tekrar dene?
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))


# ─────────────────────────────────────────────
# PROMPT BUILDER
# ─────────────────────────────────────────────
def build_prompt_text(question: Dict[str, Any]) -> str:
    """
    Soru dict'inden LLM'e gidecek prompt metnini oluşturur.
    Görseller ayrıca image content olarak eklenecek.
    """
    lines = []
    lines.append(f"Question {question['question_number']}:")
    lines.append(question["question_text"])
    lines.append("")

    options = {k: v for k, v in question["options"].items() if not k.endswith("_images")}
    for letter in ["A", "B", "C", "D"]:
        if letter in options:
            lines.append(f"{letter}) {options[letter]}")

    lines.append("")
    lines.append(
        "Instructions: Analyze the question carefully. "
        "If there are images, use them to answer. "
        "Respond ONLY in this exact JSON format:\n"
        '{"answer": "B", "confidence": 0.95, "reason": "One sentence explanation"}\n'
        "The answer field must be exactly one of: A, B, C, D"
    )
    return "\n".join(lines)


# ─────────────────────────────────────────────
# RESPONSE PARSER
# ─────────────────────────────────────────────
def extract_answer(raw_response: str) -> Dict[str, Any]:
    """
    LLM yanıtından cevap harfini, güven skorunu ve açıklamayı çeker.
    Birden fazla fallback stratejisi kullanır.
    """
    raw = raw_response.strip()

    # Strateji 1: JSON parse
    try:
        cleaned = re.sub(r"```json\s*|\s*```", "", raw).strip()
        start = cleaned.find("{")
        end   = cleaned.rfind("}") + 1
        if start != -1 and end > start:
            data = json.loads(cleaned[start:end])
            answer = str(data.get("answer", "")).upper().strip()
            if answer in ("A", "B", "C", "D"):
                return {
                    "answer": answer,
                    "confidence": float(data.get("confidence", 0.9)),
                    "reason": str(data.get("reason", "")),
                }
    except Exception:
        pass

    # Strateji 2: "Answer: B" veya "The answer is B" gibi kalıplar
    patterns = [
        r"answer[:\s]+([A-D])\b",
        r"correct[:\s]+([A-D])\b",
        r"\b([A-D])\s+is correct",
        r"option\s+([A-D])\b",
    ]
    for pat in patterns:
        m = re.search(pat, raw, re.IGNORECASE)
        if m:
            return {
                "answer": m.group(1).upper(),
                "confidence": 0.7,
                "reason": raw[:200],
            }

    # Strateji 3: Sadece tek harf yanıt
    m = re.search(r"\b([A-D])\b", raw)
    if m:
        return {
            "answer": m.group(1).upper(),
            "confidence": 0.5,
            "reason": raw[:200],
        }

    return {
        "answer": "UNCERTAIN",
        "confidence": 0.0,
        "reason": f"Could not parse: {raw[:100]}",
    }


# ─────────────────────────────────────────────
# ANTHROPIC (Claude)
# ─────────────────────────────────────────────
def solve_with_anthropic(question: Dict[str, Any]) -> Dict[str, Any]:
    """Claude Sonnet ile soruyu çözer. Vision destekli."""
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    prompt_text = build_prompt_text(question)

    content = []

    for img in question.get("images", []):
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": img["media_type"],
                "data": img["data"],
            }
        })

    content.append({"type": "text", "text": prompt_text})

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=512,
        messages=[{"role": "user", "content": content}]
    )

    raw = response.content[0].text
    return extract_answer(raw)


# ─────────────────────────────────────────────
# OPENAI (GPT-4o)
# ─────────────────────────────────────────────
def solve_with_openai(question: Dict[str, Any]) -> Dict[str, Any]:
    """GPT-4o ile soruyu çözer. Vision destekli."""
    from openai import OpenAI

    client = OpenAI(api_key=OPENAI_API_KEY)
    prompt_text = build_prompt_text(question)

    content = []

    for img in question.get("images", []):
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{img['media_type']};base64,{img['data']}",
                "detail": "high"
            }
        })

    content.append({"type": "text", "text": prompt_text})

    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=512,
        messages=[{"role": "user", "content": content}]
    )

    raw = response.choices[0].message.content
    return extract_answer(raw)


# ─────────────────────────────────────────────
# GOOGLE (Gemini 2.5 Flash)
# ─────────────────────────────────────────────
def solve_with_google(question: Dict[str, Any]) -> Dict[str, Any]:
    """
    Gemini 2.5 Flash ile soruyu çözer. Vision destekli.

    DÜZELTME: google-generativeai yerine google-genai paketi kullanılıyor.
    Doğru paket adı: pip install google-genai
    Model string: gemini-2.5-flash (hâlâ geçerli, Mayıs 2026 itibarıyla)
    """
    # ÖNEMLİ: 'from google import genai' için 'google-genai' paketi gerekir,
    # 'google-generativeai' paketi FARKLIDIR ve bu import'u desteklemez.
    from google import genai
    from google.genai import types
    import base64

    client = genai.Client(api_key=GOOGLE_API_KEY)
    prompt_text = build_prompt_text(question)

    contents = []

    for img in question.get("images", []):
        contents.append(
            types.Part.from_bytes(
                data=base64.b64decode(img["data"]),
                mime_type=img["media_type"]
            )
        )

    contents.append(prompt_text)

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=contents,
        config=types.GenerateContentConfig(
            max_output_tokens=512,
            temperature=0.1,
        )
    )

    return extract_answer(response.text)


# ─────────────────────────────────────────────
# ANA SOLVER FONKSİYONU
# ─────────────────────────────────────────────
def solve_single_question(question: Dict[str, Any]) -> Dict[str, Any]:
    """
    Tek bir soruyu seçilen LLM ile çözer.
    Hata durumunda MAX_RETRIES kadar tekrar dener.
    """
    solver_fn = {
        "anthropic": solve_with_anthropic,
        "openai":    solve_with_openai,
        "google":    solve_with_google,
    }.get(LLM_PROVIDER, solve_with_anthropic)

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = solver_fn(question)
            result["question_number"] = question["question_number"]
            result["question_text"]   = question["question_text"][:120]
            return result
        except Exception as e:
            last_error = e
            print(f"  [!] Q{question['question_number']} deneme {attempt}/{MAX_RETRIES} hata: {e}")
            time.sleep(API_DELAY * attempt)

    return {
        "question_number": question["question_number"],
        "question_text":   question["question_text"][:120],
        "answer":          "UNCERTAIN",
        "confidence":      0.0,
        "reason":          f"API hatası: {last_error}",
    }


def solve_questions(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Tüm soru listesini çözer, ilerlemeyi ekrana yazar.
    """
    answers = []
    total = len(questions)

    print(f"\n[Solver] {total} soru çözülüyor | Provider: {LLM_PROVIDER.upper()}")
    print("─" * 50)

    for i, q in enumerate(questions, 1):
        print(f"  [{i:3}/{total}] Q{q['question_number']}...", end=" ", flush=True)
        result = solve_single_question(q)
        answers.append(result)

        status = f"→ {result['answer']} (güven: {result['confidence']:.0%})"
        if result["answer"] == "UNCERTAIN":
            status = "→ ⚠️  UNCERTAIN"
        print(status)

        if i < total:
            time.sleep(API_DELAY)

    certain  = sum(1 for a in answers if a["answer"] != "UNCERTAIN")
    print(f"\n[Solver] Tamamlandı: {certain}/{total} soru cevaplandı.")
    return answers
