"""
utils/image_handler.py
----------------------
Görsel işleme yardımcı fonksiyonları:
  - Şık görsellerini dikeyde birleştirme (stitching)
  - Görsellere şık etiketi (A, B, C, D) ekleme
  - Boyutlandırma ve normalizasyon
"""

import base64
import io
from PIL import Image, ImageDraw, ImageFont
from typing import List, Dict, Any, Optional


# ─────────────────────────────────────────────
# Base64 ↔ PIL dönüşümleri
# ─────────────────────────────────────────────

def b64_to_pil(b64_str: str) -> Image.Image:
    """Base64 string'i PIL Image'a çevirir."""
    raw = base64.b64decode(b64_str)
    return Image.open(io.BytesIO(raw)).convert("RGB")


def pil_to_b64(img: Image.Image, fmt: str = "PNG") -> str:
    """PIL Image'ı base64 string'e çevirir."""
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


# ─────────────────────────────────────────────
# Şık etiketi ekleme
# ─────────────────────────────────────────────

def add_label_to_image(
    img: Image.Image,
    label: str,
    position: str = "top-left",
    font_size: int = 24
) -> Image.Image:
    """
    Görselin köşesine renkli bir şık etiketi (A, B, C, D) ekler.
    Bu sayede LLM hangi şıkkın hangi görsel olduğunu anlayabilir.
    """
    draw = ImageDraw.Draw(img.copy())
    img_copy = img.copy()
    draw = ImageDraw.Draw(img_copy)

    # Etiket kutusunun boyutu
    box_size = font_size + 12
    padding  = 6

    # Konum hesapla
    if position == "top-left":
        x, y = padding, padding
    elif position == "top-right":
        x, y = img_copy.width - box_size - padding, padding
    elif position == "bottom-left":
        x, y = padding, img_copy.height - box_size - padding
    else:
        x, y = img_copy.width - box_size - padding, img_copy.height - box_size - padding

    # Arka plan kutusu (yarı şeffaf lacivert)
    draw.rectangle(
        [x, y, x + box_size, y + box_size],
        fill=(26, 26, 46, 200)
    )

    # Harf
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()

    # Metni ortala
    bbox = draw.textbbox((0, 0), label, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    tx = x + (box_size - text_w) // 2
    ty = y + (box_size - text_h) // 2

    draw.text((tx, ty), label, fill=(255, 255, 255), font=font)
    return img_copy


# ─────────────────────────────────────────────
# Dikey birleştirme (Stitching)
# ─────────────────────────────────────────────

def stitch_images_vertical(
    images: List[Image.Image],
    labels: Optional[List[str]] = None,
    gap: int = 10,
    bg_color: tuple = (255, 255, 255)
) -> Image.Image:
    """
    Birden fazla görseli dikeyde tek bir görsel olarak birleştirir.
    İlanın "preserve visuals when it splits" gereksinimini karşılar.

    Parametreler:
        images : PIL Image listesi
        labels : Her görsele eklenecek etiketler (opsiyonel)
        gap    : Görseller arası boşluk (piksel)
        bg_color: Arka plan rengi
    """
    if not images:
        return Image.new("RGB", (100, 100), bg_color)

    if len(images) == 1:
        img = images[0]
        if labels:
            img = add_label_to_image(img, labels[0])
        return img

    # Maksimum genişliği bul
    max_w = max(img.width for img in images)

    # Toplam yükseklik
    total_h = sum(img.height for img in images) + gap * (len(images) - 1)

    # Yeni boş tuval
    canvas = Image.new("RGB", (max_w, total_h), bg_color)

    y_offset = 0
    for i, img in enumerate(images):
        # Etiketi ekle (varsa)
        if labels and i < len(labels):
            img = add_label_to_image(img, labels[i])

        # Genişliği normalize et (padding ile)
        if img.width < max_w:
            padded = Image.new("RGB", (max_w, img.height), bg_color)
            padded.paste(img, ((max_w - img.width) // 2, 0))
            img = padded

        canvas.paste(img, (0, y_offset))
        y_offset += img.height + gap

    return canvas


# ─────────────────────────────────────────────
# Soru + Şık görsellerini birleştir
# ─────────────────────────────────────────────

def prepare_question_image(question: Dict[str, Any]) -> Optional[str]:
    """
    Bir sorunun tüm görsellerini (soru görseli + şık görselleri) birleştirir.
    LLM'e tek bir birleşik görsel olarak gönderilmek üzere base64 döner.
    None döner → görsel yoksa.
    """
    all_images = []
    all_labels = []

    # Soru seviyesi görseller
    for i, img_data in enumerate(question.get("images", [])):
        try:
            pil_img = b64_to_pil(img_data["data"])
            all_images.append(pil_img)
            all_labels.append(f"Q{question['question_number']}")
        except Exception:
            pass

    # Şık görselleri
    for letter in ["A", "B", "C", "D"]:
        key = letter + "_images"
        for img_data in question.get("options", {}).get(key, []):
            try:
                pil_img = b64_to_pil(img_data["data"])
                all_images.append(pil_img)
                all_labels.append(letter)
            except Exception:
                pass

    if not all_images:
        return None

    # Birleştir
    combined = stitch_images_vertical(all_images, labels=all_labels, gap=8)

    # Çok büyükse küçült (API limitlerini aşmamak için)
    max_dim = 1024
    if combined.width > max_dim or combined.height > max_dim:
        combined.thumbnail((max_dim, max_dim), Image.LANCZOS)

    return pil_to_b64(combined)


# ─────────────────────────────────────────────
# Test
# ─────────────────────────────────────────────
if __name__ == "__main__":
    # Basit test: 3 renkli blok birleştir
    img1 = Image.new("RGB", (300, 200), (200, 230, 255))
    img2 = Image.new("RGB", (300, 150), (255, 220, 200))
    img3 = Image.new("RGB", (300, 180), (220, 255, 220))

    result = stitch_images_vertical([img1, img2, img3], labels=["Q1", "A", "B"])
    result.save("test_stitch.png")
    print(f"Test görseli kaydedildi: test_stitch.png ({result.size})")
