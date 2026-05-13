"""
evaluate.py
-----------
Sistem çıktısını cevap anahtarıyla karşılaştırır.
%80+ doğruluk hedefini ölçmek için kullanılır.

Kullanım:
    python evaluate.py <answers.json> <key.json>
    python evaluate.py output_answers/math_exam_answers.json sample_papers/math_exam_key.json
"""

import json
import sys
import argparse


def evaluate(answers_path: str, key_path: str) -> dict:
    """
    Sistem cevaplarını cevap anahtarıyla karşılaştırır.

    Döner:
        {
          "total": 12,
          "correct": 10,
          "incorrect": 1,
          "uncertain": 1,
          "accuracy": 0.833,
          "details": [...]
        }
    """
    with open(answers_path, encoding="utf-8") as f:
        answers = json.load(f)  # solve_questions() çıktısı (liste)

    with open(key_path, encoding="utf-8") as f:
        key = json.load(f)  # {"1": {"answer": "C", ...}, ...}

    results = {
        "total":     len(answers),
        "correct":   0,
        "incorrect": 0,
        "uncertain": 0,
        "details":   [],
    }

    for ans in answers:
        q_num     = str(ans["question_number"])
        predicted = ans["answer"]
        correct   = key.get(q_num, {}).get("answer", "?")

        if predicted == "UNCERTAIN":
            results["uncertain"] += 1
            status = "UNCERTAIN"
        elif predicted == correct:
            results["correct"] += 1
            status = "✓"
        else:
            results["incorrect"] += 1
            status = "✗"

        results["details"].append({
            "q":         q_num,
            "predicted": predicted,
            "correct":   correct,
            "status":    status,
            "confidence": ans.get("confidence", 0),
        })

    answered = results["total"] - results["uncertain"]
    results["accuracy"] = results["correct"] / answered if answered > 0 else 0.0
    results["total_accuracy"] = results["correct"] / results["total"] if results["total"] > 0 else 0.0

    return results


def print_report(results: dict, subject: str = ""):
    """Değerlendirme raporunu terminale yazar."""
    print("\n" + "═" * 55)
    print(f"  DEĞERLENDİRME RAPORU{f'  ({subject})' if subject else ''}")
    print("═" * 55)
    print(f"  Toplam soru     : {results['total']}")
    print(f"  Doğru           : {results['correct']}")
    print(f"  Yanlış          : {results['incorrect']}")
    print(f"  Belirsiz        : {results['uncertain']}")
    print(f"  Doğruluk        : {results['accuracy']:.1%}  (cevaplanan sorular)")
    print(f"  Genel doğruluk  : {results['total_accuracy']:.1%}  (tüm sorular)")

    target = 0.80
    passed = results["accuracy"] >= target
    emoji  = "✅" if passed else "❌"
    print(f"\n  Hedef (≥%80)    : {emoji}  {'BAŞARILI' if passed else 'BAŞARISIZ'}")
    print("═" * 55)

    print(f"\n  {'Q':<5} {'Tahmin':<9} {'Doğru':<9} {'Güven':<8} {'Sonuç'}")
    print("  " + "─" * 42)
    for d in results["details"]:
        conf = f"{d['confidence']:.0%}" if d["status"] != "UNCERTAIN" else "—"
        print(f"  Q{d['q']:<4} {d['predicted']:<9} {d['correct']:<9} {conf:<8} {d['status']}")
    print()


def main():
    parser = argparse.ArgumentParser(description="MCQ Accuracy Evaluator")
    parser.add_argument("answers", help="Sistem çıktısı JSON dosyası")
    parser.add_argument("key",     help="Cevap anahtarı JSON dosyası")
    parser.add_argument("--subject", default="", help="Ders adı (rapor için)")
    args = parser.parse_args()

    results = evaluate(args.answers, args.key)
    print_report(results, subject=args.subject)

    # Tüm sistemi geçen/geçemeyen durumunu exit code ile belirt
    sys.exit(0 if results["accuracy"] >= 0.80 else 1)


if __name__ == "__main__":
    main()
