# VisionSolve MCQ — Cloud Edition

AI destekli çoktan seçmeli sınav çözücü. `.docx` formatındaki sınav kağıdını yükle, AI cevaplasın; geçmişe kaydetsin.

**v2.0 — Firebase Authentication + Cloud Firestore + Google Cloud Functions**

---

## Özellikler

- **Kullanıcı girişi** — Firebase Auth ile e-posta/şifre veya Google hesabı
- **Sınav çözme** — Gemini, GPT-4o veya Claude ile çoktan seçmeli soru çözümü
- **Bulut geçmişi** — Çözülen sınavlar ve cevaplar Firestore'da kullanıcıya özel saklanır
- **Web arayüzü** — Sürükle-bırak dosya yükleme, gerçek zamanlı ilerleme, geçmiş paneli
- **Cloud Function** — AI Solver isteğe bağlı olarak Google Cloud Functions üzerinde çalışır

---

## Kurulum

```bash
git clone https://github.com/bayo7/ExamSolver.git
cd ExamSolver
pip install -r requirements.txt
cp .env.example .env
```

`.env` dosyasını düzenleyerek LLM ve Firebase değerlerini girin (aşağıya bakın).

```bash
python main.py        # Web arayüzü → http://localhost:5000
```

---

## Ortam Değişkenleri (.env)

### LLM Ayarları

| Değişken | Açıklama |
|----------|----------|
| `LLM_PROVIDER` | `google` \| `anthropic` \| `openai` |
| `GOOGLE_API_KEY` | Gemini API anahtarı |
| `ANTHROPIC_API_KEY` | Claude API anahtarı |
| `OPENAI_API_KEY` | OpenAI API anahtarı |
| `API_DELAY` | API çağrıları arası bekleme süresi (saniye) |
| `CLOUD_FUNCTION_URL` | AI Solver Cloud Function URL'i (boş bırakılırsa yerel çalışır) |

### Firebase Ayarları

| Değişken | Nereden Alınır |
|----------|----------------|
| `FIREBASE_PROJECT_ID` | Service Account JSON → `project_id` |
| `FIREBASE_PRIVATE_KEY_ID` | Service Account JSON → `private_key_id` |
| `FIREBASE_PRIVATE_KEY` | Service Account JSON → `private_key` |
| `FIREBASE_CLIENT_EMAIL` | Service Account JSON → `client_email` |
| `FIREBASE_CLIENT_ID` | Service Account JSON → `client_id` |
| `FIREBASE_WEB_API_KEY` | Firebase Console → Proje Ayarları → Web Uygulaması → `apiKey` |
| `FIREBASE_AUTH_DOMAIN` | Firebase Console → Web Uygulaması → `authDomain` |
| `FIREBASE_MESSAGING_SENDER_ID` | Firebase Console → Web Uygulaması → `messagingSenderId` |
| `FIREBASE_APP_ID` | Firebase Console → Web Uygulaması → `appId` |

---

## Firebase Yapılandırması

Firebase entegrasyonunu kullanabilmek için aşağıdaki servislerin aktif edilmesi gerekir:

- **Authentication** — E-posta/Şifre ve Google sağlayıcıları etkinleştirilmeli
- **Firestore** — Veritabanı oluşturulmalı; `firestore.rules` dosyasındaki güvenlik kuralları yayınlanmalı
- **Service Account** — Firebase Console → Proje Ayarları → Hizmet Hesapları → Yeni özel anahtar (JSON) indirilmeli

Firebase yapılandırılmamışsa uygulama sorunsuz şekilde yerel modda çalışmaya devam eder (giriş ve geçmiş özellikleri devre dışı kalır).

---

## Cloud Function (İsteğe Bağlı)

AI Solver'ı Google Cloud Functions üzerinde çalıştırmak için:

```bash
cd cloud_functions/ai_solver
gcloud functions deploy solve_question \
  --runtime python312 \
  --trigger-http \
  --allow-unauthenticated \
  --region europe-west1 \
  --set-env-vars "LLM_PROVIDER=google,GOOGLE_API_KEY=..." \
  --entry-point solve_question \
  --source .
```

Dağıtım sonrası `.env`'e ekle:
```
CLOUD_FUNCTION_URL=https://europe-west1-PROJE_ID.cloudfunctions.net/solve_question
```

`CLOUD_FUNCTION_URL` boş bırakılırsa solver yerel olarak çalışır.

---

## Proje Yapısı

```
ExamSolver/
├── main.py                          # Flask web sunucusu + CLI
├── index.html                       # Web arayüzü (Firebase Auth + geçmiş)
├── requirements.txt
├── .env.example
├── firestore.rules                  # Firestore güvenlik kuralları
│
├── cloud/                           # Firebase entegrasyon modülü
│   ├── firebase_service.py          # Admin SDK başlatma
│   ├── auth_middleware.py           # JWT token doğrulama
│   └── firestore_db.py              # Sınav geçmişi CRUD
│
├── cloud_functions/
│   └── ai_solver/
│       ├── main.py                  # HTTP Cloud Function (AI Solver)
│       └── requirements.txt
│
├── solver/
│   ├── ai_solver.py                 # Yerel LLM entegrasyonu
│   └── cloud_solver.py             # Cloud Function HTTP wrapper
│
├── parser/
│   └── docx_parser.py              # .docx → soru listesi
│
├── output/
│   └── answer_writer.py            # Cevap kağıdı üretici
│
└── utils/
    └── image_handler.py            # Görsel işleme
```

---

## Tech Stack

| Katman | Teknoloji |
|--------|-----------|
| Backend | Python 3.10+, Flask |
| AI | Gemini 2.5 Flash / GPT-4o / Claude Opus |
| Auth | Firebase Authentication |
| Veritabanı | Cloud Firestore |
| Serverless | Google Cloud Functions |
| Frontend | Vanilla JS, Firebase JS SDK v10 |
| Belge işleme | python-docx, Pillow |
