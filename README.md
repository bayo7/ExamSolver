# VisionSolve MCQ 🎯

AI destekli çoktan seçmeli sınav çözücü. `.docx` formatındaki sınav kağıdını sisteme at, temiz bir cevap kağıdı al.

---

## Kurulum

### 1. Repoyu klonla

```bash
git clone https://github.com/kullanici/visionsolve-mcq.git
cd visionsolve-mcq
```

### 2. Python bağımlılıklarını yükle

```bash
pip install -r requirements.txt
```

### 3. API key'ini ayarla

```bash
cp .env.example .env
# .env dosyasını aç ve API key'ini gir
```

`.env` içeriği:
```
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

---

## Kullanım

### Temel kullanım

```bash
python main.py sample_papers/math_exam.docx
```

### Farklı provider ile

```bash
python main.py exam.docx --provider openai
python main.py exam.docx --provider google
```

### Çıktı klasörü belirle

```bash
python main.py exam.docx --output-dir results/
```

### API çağrısı yapmadan test (dry-run)

```bash
python main.py exam.docx --dry-run
```

---

## Örnek sınav dosyaları oluştur

```bash
cd sample_papers
python create_sample_exams.py
```

Bu komut şunları oluşturur:
- `sample_papers/math_exam.docx` — 12 matematik sorusu
- `sample_papers/science_exam.docx` — 12 fen sorusu
- `sample_papers/math_exam_key.json` — Cevap anahtarı
- `sample_papers/science_exam_key.json` — Cevap anahtarı

---

## Doğruluk testi

```bash
# Önce çöz
python main.py sample_papers/math_exam.docx

# Sonra değerlendir
python evaluate.py output_answers/math_exam_answers.json sample_papers/math_exam_key.json --subject Matematik
```

---

## Yeni sınav kağıdı nasıl eklenir?

1. `.docx` dosyasını `sample_papers/` klasörüne koy
2. `python main.py sample_papers/<dosya_adı>.docx` komutunu çalıştır
3. Cevap kağıdı `output_answers/<dosya_adı>_answers.docx` olarak oluşur

---

## Proje Yapısı

```
visionsolve/
├── main.py                        # Ana pipeline
├── evaluate.py                    # Doğruluk testi
├── requirements.txt
├── .env.example
│
├── parser/
│   └── docx_parser.py             # .docx → soru listesi
│
├── solver/
│   └── ai_solver.py               # LLM API entegrasyonu
│
├── output/
│   └── answer_writer.py           # Cevap kağıdı üretici
│
├── utils/
│   └── image_handler.py           # Görsel işleme
│
├── sample_papers/
│   ├── create_sample_exams.py     # Test dosyası üretici
│   ├── math_exam.docx
│   └── science_exam.docx
│
└── output_answers/                # Üretilen cevap kağıtları buraya gelir
```

---

Q1. Soru metni buraya
A) Şık metni
B) Şık metni
C) Şık metni
D) Şık metni
                    ← tek boş satır
Q2. Soru metni buraya
A) Şık metni
...

---

## Tech Stack

| Katman | Teknoloji |
|--------|-----------|
| Dil | Python 3.10+ |
| Docx | python-docx |
| Görsel | Pillow (PIL) |
| AI | Claude / GPT-4o / Gemini 2.5 Flash |
| Çıktı | python-docx |
