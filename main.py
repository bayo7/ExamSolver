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

from dotenv import load_dotenv
load_dotenv()


def print_banner():
    print("""
╔══════════════════════════════════════════════╗
║          VisionSolve MCQ  v2.0               ║
║   AI-Powered Multiple Choice Exam Solver     ║
║   Cloud Edition — Firebase + GCP             ║
╚══════════════════════════════════════════════╝
""")


def validate_input(path: str) -> bool:
    if not os.path.exists(path):
        print(f"[✗] Dosya bulunamadı: {path}")
        return False
    if not path.lower().endswith(".docx"):
        print(f"[✗] Sadece .docx dosyaları desteklenir: {path}")
        return False
    return True


def dry_run_solver(questions):
    import random
    options = ["A", "B", "C", "D"]
    answers = []
    for q in questions:
        available = [o for o in q.get("options", {}).keys() if not o.endswith("_images")]
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
    base = os.path.splitext(os.path.basename(input_path))[0]
    json_path = os.path.join(output_dir, f"{base}_answers.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(answers, f, ensure_ascii=False, indent=2)
    print(f"[Log]    JSON log kaydedildi → {json_path}")
    return json_path


def print_summary(answers):
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
    try:
        from flask import Flask, request, jsonify, send_from_directory, g
        from flask_cors import CORS
    except ImportError:
        print("[✗] Flask bulunamadı: pip install flask flask-cors")
        sys.exit(1)

    from parser.docx_parser  import parse_exam
    from output.answer_writer import write_answers

    BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
    OUTPUT_FOLDER = os.path.join(BASE_DIR, "output_answers")
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    CLOUD_FUNCTION_URL = os.getenv("CLOUD_FUNCTION_URL", "").strip()

    # ── Firebase (opsiyonel) ───────────────────────────────────────
    FIREBASE_ENABLED = False
    try:
        from cloud.firebase_service import FIREBASE_ENABLED as _FB
        FIREBASE_ENABLED = _FB
        if FIREBASE_ENABLED:
            from cloud import firestore_db
            from cloud.auth_middleware import get_uid_from_request
            print("[Firebase] Bulut özellikleri aktif (Auth + Firestore).")
        else:
            print("[Firebase] Yapılandırılmamış; yerel modda çalışılıyor.")
    except Exception as _fe:
        print(f"[Firebase] Yüklenemedi: {_fe}")

    import threading
    import uuid

    app = Flask(__name__, static_folder=None)
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    jobs = {}
    jobs_lock = threading.Lock()

    # ── Statik sayfa ──────────────────────────────────────────────
    @app.route("/")
    def index():
        return send_from_directory(BASE_DIR, "index.html")

    # ── Sağlık kontrolü ───────────────────────────────────────────
    @app.route("/api/health")
    def health():
        return jsonify({
            "status":          "ok",
            "version":         "2.0",
            "firebase":        FIREBASE_ENABLED,
            "cloud_function":  bool(CLOUD_FUNCTION_URL),
        })

    # ── Firebase web config (frontend'in Firebase SDK'yı başlatması için) ──
    @app.route("/api/firebase-config")
    def firebase_config():
        return jsonify({
            "enabled":           FIREBASE_ENABLED,
            "apiKey":            os.getenv("FIREBASE_WEB_API_KEY", ""),
            "authDomain":        os.getenv("FIREBASE_AUTH_DOMAIN", ""),
            "projectId":         os.getenv("FIREBASE_PROJECT_ID", ""),
            "storageBucket":     os.getenv("FIREBASE_STORAGE_BUCKET", ""),
            "messagingSenderId": os.getenv("FIREBASE_MESSAGING_SENDER_ID", ""),
            "appId":             os.getenv("FIREBASE_APP_ID", ""),
        })

    # ── Çözme endpoint'i ──────────────────────────────────────────
    @app.route("/api/solve", methods=["POST"])
    def solve():
        if "file" not in request.files:
            return jsonify({"error": "Dosya gönderilmedi"}), 400

        f = request.files["file"]
        if not f.filename.lower().endswith(".docx"):
            return jsonify({"error": "Sadece .docx dosyaları desteklenir"}), 400

        provider = request.form.get("provider", os.getenv("LLM_PROVIDER", "google"))
        dry_run  = request.form.get("dry_run", "false").lower() == "true"

        file_bytes = f.read()
        filename   = f.filename

        # Kullanıcı kimliğini al (opsiyonel — yoksa geçmişe kaydedilmez)
        user_uid = None
        if FIREBASE_ENABLED:
            try:
                user_uid = get_uid_from_request(request)
            except Exception:
                pass

        job_id = str(uuid.uuid4())
        with jobs_lock:
            jobs[job_id] = {"status": "running", "result": None, "error": None}

        def run_job():
            tmp_path = os.path.join(tempfile.gettempdir(), f"exam_{job_id}.docx")
            exam_id  = None
            try:
                with open(tmp_path, "wb") as fp:
                    fp.write(file_bytes)

                # Aşama 1 — Parse
                questions = parse_exam(tmp_path)
                if not questions:
                    with jobs_lock:
                        jobs[job_id]["status"] = "error"
                        jobs[job_id]["error"]  = "Soru bulunamadı — dosya formatını kontrol edin"
                    return

                # Firestore: başlangıç kaydı
                if FIREBASE_ENABLED and user_uid:
                    try:
                        exam_id = firestore_db.save_exam_start(
                            user_uid, filename, provider, len(questions)
                        )
                    except Exception as _dbe:
                        print(f"[Firestore] Kayıt oluşturulamadı: {_dbe}")

                start = time.time()

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
                elif CLOUD_FUNCTION_URL:
                    # Cloud Function üzerinden çöz
                    from solver.cloud_solver import solve_questions_cloud
                    answers = solve_questions_cloud(questions, provider)
                else:
                    # Yerel solver
                    from solver.ai_solver import solve_questions
                    os.environ["LLM_PROVIDER"] = provider
                    answers = solve_questions(questions)

                # Aşama 3 — Cevap kağıdı yaz
                output_docx = write_answers(
                    input_path=tmp_path,
                    answers=answers,
                    output_dir=OUTPUT_FOLDER,
                )

                elapsed = round(time.time() - start, 1)

                # Firestore: tamamlandı
                if FIREBASE_ENABLED and user_uid and exam_id:
                    try:
                        firestore_db.finish_exam(exam_id, answers, Path(output_docx).name)
                    except Exception as _dbe:
                        print(f"[Firestore] Güncelleme hatası: {_dbe}")

                with jobs_lock:
                    jobs[job_id]["status"] = "done"
                    jobs[job_id]["result"] = {
                        "success":       True,
                        "total":         len(questions),
                        "answered":      sum(1 for a in answers if a["answer"] != "UNCERTAIN"),
                        "uncertain":     sum(1 for a in answers if a["answer"] == "UNCERTAIN"),
                        "elapsed":       elapsed,
                        "provider":      provider,
                        "cloud":         bool(CLOUD_FUNCTION_URL and not dry_run),
                        "docx_filename": Path(output_docx).name,
                        "answers":       answers,
                        "examId":        exam_id,
                    }

            except Exception as e:
                if FIREBASE_ENABLED and user_uid and exam_id:
                    try:
                        firestore_db.fail_exam(exam_id, str(e))
                    except Exception:
                        pass
                with jobs_lock:
                    jobs[job_id]["status"] = "error"
                    jobs[job_id]["error"]  = str(e)
            finally:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

        threading.Thread(target=run_job, daemon=True).start()
        return jsonify({"job_id": job_id}), 202

    # ── İş durumu ─────────────────────────────────────────────────
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
        result = job["result"]
        with jobs_lock:
            jobs.pop(job_id, None)
        return jsonify({"status": "done", **result})

    # ── İndirme ───────────────────────────────────────────────────
    @app.route("/api/download/<filename>")
    def download(filename):
        return send_from_directory(OUTPUT_FOLDER, Path(filename).name, as_attachment=True)

    # ── Geçmiş sınavlar (Firebase gerekli) ───────────────────────
    @app.route("/api/history")
    def history():
        if not FIREBASE_ENABLED:
            return jsonify({"error": "Firebase yapılandırılmamış"}), 503
        uid = get_uid_from_request(request)
        if not uid:
            return jsonify({"error": "Kimlik doğrulama gerekli"}), 401
        try:
            exams = firestore_db.list_exams(uid)
            return jsonify({"exams": exams})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # ── Tek sınav detayı ──────────────────────────────────────────
    @app.route("/api/history/<exam_id>")
    def exam_detail(exam_id):
        if not FIREBASE_ENABLED:
            return jsonify({"error": "Firebase yapılandırılmamış"}), 503
        uid = get_uid_from_request(request)
        if not uid:
            return jsonify({"error": "Kimlik doğrulama gerekli"}), 401
        try:
            exam = firestore_db.get_exam(exam_id, uid)
            if not exam:
                return jsonify({"error": "Sınav bulunamadı"}), 404
            return jsonify(exam)
        except Exception as e:
            return jsonify({"error": str(e)}), 500


    # ── Başlat ────────────────────────────────────────────────────
    print_banner()
    cloud_info = f"Cloud Function: {CLOUD_FUNCTION_URL}" if CLOUD_FUNCTION_URL else "Yerel solver"
    print(f"  Web arayüzü  : http://localhost:{port}")
    print(f"  Firebase     : {'Aktif' if FIREBASE_ENABLED else 'Devre dışı'}")
    print(f"  AI Solver    : {cloud_info}")
    print(f"  Çıktı klasörü: {OUTPUT_FOLDER}")
    print(f"  Durdurmak için Ctrl+C\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)


# ══════════════════════════════════════════════════════════════════
# CLI PIPELINE
# ══════════════════════════════════════════════════════════════════

def run_cli(args):
    from parser.docx_parser  import parse_exam
    from output.answer_writer import write_answers

    print_banner()

    CLOUD_FUNCTION_URL = os.getenv("CLOUD_FUNCTION_URL", "").strip()

    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    provider = os.environ.get("LLM_PROVIDER", "google")

    if not validate_input(args.input):
        sys.exit(1)

    start_time = time.time()

    print(f"[1/3]  Dosya okunuyor: {args.input}")
    try:
        questions = parse_exam(args.input)
    except Exception as e:
        print(f"[✗] Parse hatası: {e}")
        sys.exit(1)

    if not questions:
        print("[✗] Hiç soru bulunamadı.")
        sys.exit(1)
    print(f"       → {len(questions)} soru bulundu\n")

    print("[2/3]  Sorular çözülüyor...")
    if args.dry_run:
        print("       ⚠️  DRY RUN modu — gerçek API çağrısı yapılmıyor")
        answers = dry_run_solver(questions)
    elif CLOUD_FUNCTION_URL:
        print(f"       Cloud Function: {CLOUD_FUNCTION_URL}")
        try:
            from solver.cloud_solver import solve_questions_cloud
            answers = solve_questions_cloud(questions, provider)
        except Exception as e:
            print(f"[✗] Cloud Solver hatası: {e}")
            sys.exit(1)
    else:
        try:
            from solver.ai_solver import solve_questions
            answers = solve_questions(questions)
        except Exception as e:
            print(f"[✗] Solver hatası: {e}")
            sys.exit(1)

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
    print(f"  Tamamlandı! ({elapsed:.1f} saniye)")
    print(f"  Cevap kağıdı: {output_path}\n")


# ══════════════════════════════════════════════════════════════════
# GİRİŞ NOKTASI
# ══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="VisionSolve MCQ — AI ile çoktan seçmeli sınav çözücü (Cloud Edition)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Örnekler:\n"
            "  python main.py                        # Web arayüzü (localhost:5000)\n"
            "  python main.py --cli sinav.docx       # CLI pipeline\n"
            "  python main.py --port 8080            # Farklı port ile web\n"
        ),
    )
    parser.add_argument("--cli", action="store_true")
    parser.add_argument("input", nargs="?", default=None)
    parser.add_argument("--output-dir", "-o", default="output_answers")
    parser.add_argument("--provider", "-p", choices=["google", "anthropic", "openai"], default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--save-json", action="store_true", default=True)
    parser.add_argument("--port", type=int, default=5000)

    args = parser.parse_args()

    if args.cli or args.input:
        if not args.input:
            parser.error("CLI modunda bir .docx dosyası belirtmelisiniz")
        run_cli(args)
    else:
        start_web(port=args.port)


if __name__ == "__main__":
    main()
