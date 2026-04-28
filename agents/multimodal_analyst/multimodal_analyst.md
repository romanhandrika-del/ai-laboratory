# Multimodal Analyst Agent

**agent_id:** `multimodal-analyst-v1`  
**Номер у платформі:** Agent #6  
**Модель:** `claude-sonnet-4-6`

## Призначення

Приймає байти фото або PDF, аналізує через Claude Vision, повертає структурований Markdown-звіт з класифікацією типу матеріалу.

## Підтримувані формати

- **Зображення:** `image/jpeg`, `image/png`, `image/gif`, `image/webp`
- **PDF:** текстовий (не скановані)

## Вхід / Вихід

```python
await agent.analyze(
    file_bytes: bytes,
    media_type: str,
    override_kind: str = "",       # примусовий тип ('pricelist','ad','realty','analytics')
    source_tg_file_id: str = "",
    source_tg_msg_id: int = 0,
) -> dict
```

```python
{
    "kind": str,           # тип матеріалу (auto або override)
    "confidence": float,
    "report_md": str,      # Markdown-звіт
    "summary_html": str,   # HTML для Telegram
    # або
    "error": str
}
```

## Пайплайн

### Зображення
1. OCR через `agents/instagram/ocr.py` → витягує текст (назви, ціни, підписи)
2. Base64-encode → Claude Vision API з OCR-блоком як текст
3. Retry ×3 при HTTP 529

### PDF
1. `pypdf.PdfReader` → витягує текст (до 4000 символів)
2. Якщо текстового шару < 100 символів → error (скановане)
3. Claude аналізує текст (без Vision)

## Зберігання

- Звіт → `db.save_analysis()` (PostgreSQL `analysis_history`)
- Оригінал файлу → Telegram Archive Channel (через `bot.py`)

## Обмеження

- Скановані PDF не підтримуються — потрібен скріншот
- Retry тільки на 529 (overload), не на інші помилки
