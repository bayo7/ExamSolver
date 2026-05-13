"""
main.py
-------
VisionSolve MCQ - Ana pipeline giriş noktası.

Kullanım:
    python main.py <sınav.docx>
    python main.py <sınav.docx> --output-dir output_answers/
    python main.py <sınav.docx> --provider openai
    python main.py <sınav.docx> --dry-run        # API çağrısı yapmadan test
"""

import argparse
import sys
import os
import json
import time
from pathlib import Path

# Kendi modüllerimiz
from parser.docx_parser   import parse_exam
from solver.ai_solver      import solve_questions
from output.answer_writer  import write_answers


def print_banner():
    print("""
╔══════════════════════════════════════════════╗
║          VisionSolve MCQ  v1.0               ║
║   AI-Powered Multiple Choice Exam Solver     ║
╚══════════════════════════════════════════════╝
""")


def validate_input(path: str) -> bool:
    """Girdi dosyasını kontrol eder."""
    if not os.path.exists(path):
        print(f"[✗] Dosya bulunamadı: {path}")
        return False
    if not path.lower().endswith(".docx"):
        print(f"[✗] Sadece .docx dosyaları desteklenir: {path}")
        return False
    return True


def dry_run_solver(questions):
    """
    API çağrısı yapmadan sahte cevaplar üretir.
    Sistemi test etmek için kullanılır.
    """
    import random
    options = ["A", "B", "C", "D"]
    answers = []
    for q in questions:
        available = list(q.get("options", {}).keys())
        available = [o for o in available if not o.endswith("_images")]
        choice = random.choice(available) if available else random.choice(options)
        answers.append({
            "question_number": q["question_number"],
            "question_text":   q["question_text"],
            "answer":          choice,
            "confidence":      round(random.uniform(0.7, 0.99), 2),
            "reason":          "[DRY RUN] Bu gerçek bir cevap değildir.",
        })
    return answers


def save_json_log(answers, input_path: str, output_dir: str):
    """Cevapları JSON formatında da kaydeder (debug için)."""
    base = os.path.splitext(os.path.basename(input_path))[0]
    json_path = os.path.join(output_dir, f"{base}_answers.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(answers, f, ensure_ascii=False, indent=2)
    print(f"[Log]    JSON log kaydedildi → {json_path}")
    return json_path


def print_summary(answers):
    """Terminal'e özet tablo yazar."""
    total     = len(answers)
    certain   = sum(1 for a in answers if a["answer"] != "UNCERTAIN")
    uncertain = total - certain

    print("\n" + "═" * 50)
    print(f"  SONUÇ ÖZETİ")
    print("═" * 50)
    print(f"  Toplam soru    : {total}")
    print(f"  Cevaplanan     : {certain}  ({certain/total:.0%})" if total else "")
    print(f"  Belirsiz       : {uncertain}")

    if certain > 0:
        avg = sum(a["confidence"] for a in answers if a["answer"] != "UNCERTAIN") / certain
        print(f"  Ortalama güven : {avg:.0%}")

    print("═" * 50)
    print(f"\n  {'Q#':<5} {'Cevap':<8} {'Güven':<8}")
    print("  " + "─" * 25)
    for a in answers:
        q    = a["question_number"]
        ans  = a["answer"]
        conf = f"{a['confidence']:.0%}" if a["answer"] != "UNCERTAIN" else "—"
        flag = "⚠️ " if ans == "UNCERTAIN" else "✓ "
        print(f"  {flag}Q{q:<4} {ans:<8} {conf}")
    print()


def main():
    print_banner()

    # ── Argümanlar ──
    parser = argparse.ArgumentParser(
        description="VisionSolve MCQ — AI ile çoktan seçmeli sınav çözücü"
    )
    parser.add_argument(
        "input",
        help="Çözülecek .docx sınav dosyası"
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="output_answers",
        help="Çıktı klasörü (varsayılan: output_answers/)"
    )
    parser.add_argument(
        "--provider", "-p",
        choices=["anthropic", "openai", "google"],
        default=None,
        help="Kullanılacak LLM API (varsayılan: .env'den LLM_PROVIDER)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="API çağrısı yapmadan test modu (sahte cevaplar)"
    )
    parser.add_argument(
        "--save-json",
        action="store_true",
        default=True,
        help="Cevapları JSON olarak da kaydet (varsayılan: açık)"
    )
    args = parser.parse_args()

    # Provider override
    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider

    # ── Giriş doğrulama ──
    if not validate_input(args.input):
        sys.exit(1)

    start_time = time.time()

    # ── AŞAMA 1: Parse ──
    print(f"[1/3]  Dosya okunuyor: {args.input}")
    try:
        questions = parse_exam(args.input)
    except Exception as e:
        print(f"[✗] Parse hatası: {e}")
        sys.exit(1)

    if not questions:
        print("[✗] Hiç soru bulunamadı. Dosya formatını kontrol edin.")
        sys.exit(1)

    print(f"       → {len(questions)} soru bulundu\n")

    # ── AŞAMA 2: Çöz ──
    print(f"[2/3]  Sorular çözülüyor...")

    if args.dry_run:
        print("       ⚠️  DRY RUN modu — gerçek API çağrısı yapılmıyor")
        answers = dry_run_solver(questions)
    else:
        try:
            answers = solve_questions(questions)
        except Exception as e:
            print(f"[✗] Solver hatası: {e}")
            print("    İpucu: .env dosyasında API key'ini kontrol et.")
            sys.exit(1)

    # ── AŞAMA 3: Yaz ──
    print(f"\n[3/3]  Cevap kağıdı oluşturuluyor...")

    os.makedirs(args.output_dir, exist_ok=True)

    try:
        output_path = write_answers(
            input_path=args.input,
            answers=answers,
            output_dir=args.output_dir
        )
    except Exception as e:
        print(f"[✗] Yazma hatası: {e}")
        sys.exit(1)

    if args.save_json:
        save_json_log(answers, args.input, args.output_dir)

    # ── Özet ──
    elapsed = time.time() - start_time
    print_summary(answers)

    print(f"  ✅  Tamamlandı! ({elapsed:.1f} saniye)")
    print(f"  📄  Cevap kağıdı: {output_path}\n")


if __name__ == "__main__":
    main()
