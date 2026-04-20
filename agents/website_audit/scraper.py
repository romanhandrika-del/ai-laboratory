"""
Website Audit Scraper — завантажує HTML сторінку + вимірює час завантаження.
"""

import time
from playwright.async_api import async_playwright
from core.logger import get_logger

logger = get_logger(__name__)

_PAGE_TIMEOUT_MS = 30_000


async def fetch_page(url: str) -> tuple[str, float]:
    """
    Завантажує повний HTML сторінки після JS-рендеру.

    Returns:
        (html_content, load_time_seconds)

    Raises:
        RuntimeError: якщо сторінка не завантажилась за таймаут
    """
    logger.debug("AuditScraper: відкриваю %s", url)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                )
            )
            page = await context.new_page()
            t0 = time.perf_counter()
            await page.goto(url, wait_until="networkidle", timeout=_PAGE_TIMEOUT_MS)
            load_time = time.perf_counter() - t0
            html = await page.content()
        except Exception as e:
            raise RuntimeError(f"Не вдалось завантажити {url}: {e}") from e
        finally:
            await browser.close()

    logger.debug("AuditScraper: %d символів, %.2fs для %s", len(html), load_time, url)
    return html, load_time


async def fetch_page_with_styles(url: str) -> tuple[str, float, dict]:
    """
    Завантажує HTML + збирає computed visual styles одним Playwright-запуском.

    Returns:
        (html_content, load_time_seconds, visual_data)
        visual_data: {fonts, colors, sections_count, has_hero, has_footer,
                      images_count, buttons_count, viewport_width}
    """
    logger.debug("DesignScraper: відкриваю %s з visual extraction", url)

    _JS_EXTRACT = """
    () => {
        const els = Array.from(document.querySelectorAll('*')).filter(e => {
            const r = e.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
        }).slice(0, 300);
        const fontCount = {}, colorCount = {}, bgCount = {};
        for (const el of els) {
            const s = getComputedStyle(el);
            const ff = s.fontFamily.split(',')[0].replace(/['"]/g, '').trim();
            if (ff) fontCount[ff] = (fontCount[ff] || 0) + 1;
            const c = s.color;
            if (c && c !== 'rgba(0, 0, 0, 0)') colorCount[c] = (colorCount[c] || 0) + 1;
            const bg = s.backgroundColor;
            if (bg && bg !== 'rgba(0, 0, 0, 0)') bgCount[bg] = (bgCount[bg] || 0) + 1;
        }
        const top = (obj, n) => Object.entries(obj).sort((a,b)=>b[1]-a[1]).slice(0,n).map(e=>e[0]);
        const sections = document.querySelectorAll('section, article, [class*="section"], [class*="block"]').length;
        const hasHero = !!document.querySelector('[class*="hero"], [class*="banner"], [id*="hero"]');
        const hasFooter = !!document.querySelector('footer, [class*="footer"]');
        return {
            fonts: top(fontCount, 5),
            colors: top(colorCount, 6),
            bg_colors: top(bgCount, 4),
            sections_count: sections,
            has_hero: hasHero,
            has_footer: hasFooter,
            images_count: document.querySelectorAll('img').length,
            buttons_count: document.querySelectorAll('button, [class*="btn"], a[class*="btn"]').length,
            viewport_width: window.innerWidth
        };
    }
    """

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                )
            )
            page = await context.new_page()
            t0 = time.perf_counter()
            await page.goto(url, wait_until="networkidle", timeout=_PAGE_TIMEOUT_MS)
            load_time = time.perf_counter() - t0
            html = await page.content()
            visual_data = await page.evaluate(_JS_EXTRACT)
        except Exception as e:
            raise RuntimeError(f"Не вдалось завантажити {url}: {e}") from e
        finally:
            await browser.close()

    logger.debug("DesignScraper: %d символів, %.2fs, fonts=%s", len(html), load_time, visual_data.get("fonts"))
    return html, load_time, visual_data
