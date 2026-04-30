# Web Design Agent

**agent_id:** `web-design-v1`  
**Номер у платформі:** Agent #5

## Призначення

Генерує дизайн-пакет (`brief.md` + `mockup.html`) двома способами:
- **URL режим:** scrape сайту → аналіз стилів → редизайн-бриф + HTML/CSS макет
- **Brief режим:** текстовий опис → лендінг з нуля

## Вхід / Вихід

```python
await agent.design(url_or_brief: str) -> dict
```

```python
{
    "brief_path": str,       # шлях до brief.md
    "mockup_path": str,      # шлях до mockup.html
    "dir_path": str,         # директорія пакету
    "summary_text": str,     # Telegram-повідомлення про результат
    # або
    "error": str
}
```

## Пайплайн (URL режим)

1. `scraper.fetch_page_with_styles(url)` → HTML + CSS
2. Паралельно: `seo_extractor.extract()` + `design_extractor.extract()`
3. `design_generator.generate_from_url(visual_data, seo_data, url)` → brief.md + mockup.html

## Пайплайн (Brief режим)

1. `design_generator.generate_from_brief(text)` → brief.md + mockup.html

## Збереження

- Файли: `data/designs/{client_id}/{slug}-design-{YYYYMMDD-HHmm}/`
- Запис у БД: `db.save_design(client_id, input, mode, dir_path)`

## Залежності

- `agents/website_audit/scraper` — завантаження HTML
- `agents/website_audit/seo_extractor` — SEO-факти
- `agents/web_design/design_extractor` — витяг візуальних стилів
- `agents/web_design/design_generator` — генерація через Claude
