"""
main.py
-------
VisionSolve MCQ — Ana giriş noktası.

Kullanım:
    python main.py                           # Web arayüzü (localhost:5000)
    python main.py --cli <sınav.docx>        # CLI pipeline
    python main.py --cli <sınav.docx> --provider openai
    python main.py --cli <sınav.docx> --dry-run
"""

import argparse
import sys
import os
import json
import time
import tempfile
from pathlib import Path


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


# ══════════════════════════════════════════════════════════════════
# WEB SUNUCUSU  (Flask)
# ══════════════════════════════════════════════════════════════════

def start_web(port: int = 5000):
    """
    Flask web sunucusunu başlatır.
    index.html'i sunar ve /api/solve endpointi üzerinden sınavı çözer.
    """
    try:
        from flask import Flask, request, jsonify, send_from_directory
        from flask_cors import CORS
    except ImportError:
        print("[✗] Flask bulunamadı. Yüklemek için:")
        print("    pip install flask flask-cors")
        sys.exit(1)

    # Modülleri burada import et (web modunda da aynı pipeline)
    from parser.docx_parser   import parse_exam
    from solver.ai_solver      import solve_questions
    from output.answer_writer  import write_answers

    BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
    OUTPUT_FOLDER = os.path.join(BASE_DIR, "output_answers")
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    import threading
    import uuid

    app = Flask(__name__, static_folder=None)
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # ── İş takip sözlüğü ──────────────────────────────────────────
    jobs = {}  # job_id -> {status, result, error}
    jobs_lock = threading.Lock()

    # ── Statik sayfa ──────────────────────────────────────────────
    @app.route("/")
    def index():
        return send_from_directory(BASE_DIR, "index.html")

    # ── Sağlık kontrolü ───────────────────────────────────────────
    @app.route("/api/health")
    def health():
        return jsonify({"status": "ok", "version": "1.0"})

    # ── Çözme endpoint'i (hemen job_id döner) ────────────────────
    @app.route("/api/solve", methods=["POST"])
    def solve():
        if "file" not in request.files:
            return jsonify({"error": "Dosya gönderilmedi"}), 400

        f = request.files["file"]
        if not f.filename.lower().endswith(".docx"):
            return jsonify({"error": "Sadece .docx dosyaları desteklenir"}), 400

        provider = request.form.get("provider", None)
        dry_run  = request.form.get("dry_run", "false").lower() == "true"

        # Dosyayı oku (request stream kapanmadan önce)
        file_bytes = f.read()
        filename   = f.filename

        job_id = str(uuid.uuid4())
        with jobs_lock:
            jobs[job_id] = {"status": "running", "result": None, "error": None}

        def run_job():
            tmp_path = os.path.join(tempfile.gettempdir(), f"exam_{job_id}.docx")
            try:
                # Dosyayı geçici konuma yaz
                with open(tmp_path, "wb") as fp:
                    fp.write(file_bytes)

                if provider:
                    os.environ["LLM_PROVIDER"] = provider

                start = time.time()

                # Aşama 1 — Parse
                questions = parse_exam(tmp_path)
                if not questions:
                    with jobs_lock:
                        jobs[job_id]["status"] = "error"
                        jobs[job_id]["error"]  = "Soru bulunamadı — dosya formatını kontrol edin"
                    return

                # Aşama 2 — Çöz
                if dry_run:
                    import random
                    answers = []
                    for q in questions:
                        available = [k for k in q.get("options", {}).keys() if not k.endswith("_images")]
                        choice = random.choice(available) if available else "A"
                        answers.append({
                            "question_number": q["question_number"],
                            "question_text":   q["question_text"][:120],
                            "answer":          choice,
                            "confidence":      round(random.uniform(0.70, 0.99), 2),
                            "reason":          "[DRY RUN] Bu gerçek bir cevap değildir.",
                        })
                else:
                    answers = solve_questions(questions)

                # Aşama 3 — Yaz
                output_docx = write_answers(
                    input_path=tmp_path,
                    answers=answers,
                    output_dir=OUTPUT_FOLDER,
                )

                elapsed = round(time.time() - start, 1)
                with jobs_lock:
                    jobs[job_id]["status"] = "done"
                    jobs[job_id]["result"] = {
                        "success":       True,
                        "total":         len(questions),
                        "answered":      sum(1 for a in answers if a["answer"] != "UNCERTAIN"),
                        "uncertain":     sum(1 for a in answers if a["answer"] == "UNCERTAIN"),
                        "elapsed":       elapsed,
                        "provider":      os.environ.get("LLM_PROVIDER", "google"),
                        "docx_filename": Path(output_docx).name,
                        "answers":       answers,
                    }

            except Exception as e:
                with jobs_lock:
                    jobs[job_id]["status"] = "error"
                    jobs[job_id]["error"]  = str(e)
            finally:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

        thread = threading.Thread(target=run_job, daemon=True)
        thread.start()

        return jsonify({"job_id": job_id}), 202

    # ── İş durumu endpoint'i (polling) ───────────────────────────
    @app.route("/api/status/<job_id>")
    def job_status(job_id):
        with jobs_lock:
            job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Geçersiz job_id"}), 404
        if job["status"] == "running":
            return jsonify({"status": "running"})
        if job["status"] == "error":
            return jsonify({"status": "error", "error": job["error"]}), 500
        # done — sonucu döndür ve bellekten temizle
        result = job["result"]
        with jobs_lock:
            jobs.pop(job_id, None)
        return jsonify({"status": "done", **result})

    # ── İndirme endpoint'i ────────────────────────────────────────
    @app.route("/api/download/<filename>")
    def download(filename):
        safe = Path(filename).name
        return send_from_directory(OUTPUT_FOLDER, safe, as_attachment=True)

    # ── Başlat ────────────────────────────────────────────────────
    print_banner()
    print(f"  🌐  Web arayüzü: http://localhost:{port}")
    print(f"  📁  Çıktı klasörü: {OUTPUT_FOLDER}")
    print(f"  ✋  Durdurmak için Ctrl+C\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)


# ══════════════════════════════════════════════════════════════════
# CLI PIPELINE
# ══════════════════════════════════════════════════════════════════

def run_cli(args):
    """Klasik CLI pipeline."""
    from parser.docx_parser   import parse_exam
    from solver.ai_solver      import solve_questions
    from output.answer_writer  import write_answers

    print_banner()

    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider

    if not validate_input(args.input):
        sys.exit(1)

    start_time = time.time()

    # Aşama 1 — Parse
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

    # Aşama 2 — Çöz
    print("[2/3]  Sorular çözülüyor...")
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

    # Aşama 3 — Yaz
    print("\n[3/3]  Cevap kağıdı oluşturuluyor...")
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

    elapsed = time.time() - start_time
    print_summary(answers)
    print(f"  ✅  Tamamlandı! ({elapsed:.1f} saniye)")
    print(f"  📄  Cevap kağıdı: {output_path}\n")


# ══════════════════════════════════════════════════════════════════
# GİRİŞ NOKTASI
# ══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="VisionSolve MCQ — AI ile çoktan seçmeli sınav çözücü",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Örnekler:\n"
            "  python main.py                        # Web arayüzü (localhost:5000)\n"
            "  python main.py --cli sinav.docx       # CLI pipeline\n"
            "  python main.py --port 8080            # Farklı port ile web\n"
        ),
    )

    parser.add_argument(
        "--cli",
        action="store_true",
        help="CLI pipeline modunda çalıştır (web sunucusu başlatılmaz)"
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=None,
        help="[CLI modu] Çözülecek .docx sınav dosyası"
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="output_answers",
        help="[CLI modu] Çıktı klasörü (varsayılan: output_answers/)"
    )
    parser.add_argument(
        "--provider", "-p",
        choices=["google", "anthropic", "openai"],
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
        help="[CLI modu] Cevapları JSON olarak da kaydet (varsayılan: açık)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="[Web modu] Sunucu portu (varsayılan: 5000)"
    )

    args = parser.parse_args()

    # CLI modu: --cli flag'i ya da positional argüman verilmişse
    if args.cli or args.input:
        if not args.input:
            parser.error("CLI modunda bir .docx dosyası belirtmelisiniz: python main.py --cli sinav.docx")
        run_cli(args)
    else:
        # Argümansız çalıştırıldı → web sunucusu
        start_web(port=args.port)


if __name__ == "__main__":
    main()
