# Website Audit Agent

**agent_id:** `website-audit-v1`  
**Номер у платформі:** Agent #3

## Призначення

Аналізує сайт за 4 категоріями та формує Markdown-звіт зі score.

## Категорії аудиту

| # | Категорія | Інструмент |
|---|-----------|-----------|
| 1 | SEO on-page | `seo_extractor` (title, meta, headings, canonical, OG, JSON-LD) |
| 2 | Google visibility | `pagespeed_client` (PageSpeed Insights: LCP, CLS, FCP, scores) |
| 3 | Конверсія/UX | Claude аналіз (CTA, форми, контакти) |
| 4 | Технічний | `technical_checker` (HTTPS, robots.txt, sitemap, статус) |

## Вхід / Вихід

```python
await agent.audit(url: str) -> dict
```

```python
{
    "score": int,              # загальний бал
    "summary_text": str,       # Telegram-повідомлення
    "report_md_path": str,     # шлях до Markdown-звіту
    "report_md": str,          # текст звіту
    # або
    "error": str
}
```

## Пайплайн

1. `scraper.fetch_page(url)` → HTML + load_time
2. Паралельно:
   - `seo_extractor.extract(html, url)`
   - `technical_checker.check(url)`
   - `pagespeed_client.fetch(url)`
3. Claude аналізує UX/конверсію
4. `report_generator` → Markdown-звіт + score
5. Збереження у `data/audits/{client_id}/` + `core.audit_storage`

## Режими запуску

- **On-demand:** `/audit <url>` через Telegram бот
- **Scheduled:** `run.py` + `config/audit_targets.yaml`

## Env vars

| Змінна | Опис |
|--------|------|
| `TELEGRAM_BOT_TOKEN` | Бот для нотифікацій |
| `MANAGER_TELEGRAM_ID` | Telegram ID менеджера |
| `PAGESPEED_API_KEY` | Google PageSpeed Insights API key |
