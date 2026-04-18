"""
Web Scraper — завантажує HTML сторінку через Playwright.

Playwright рендерить JavaScript перед поверненням HTML,
тому підходить для сучасних сайтів з динамічним контентом.
"""

from playwright.async_api import async_playwright
from core.logger import get_logger

logger = get_logger(__name__)

_PAGE_TIMEOUT_MS = 30_000


async def fetch_page(url: str) -> str:
    """
    Завантажує повний HTML сторінки після виконання JavaScript.

    Args:
        url: URL сторінки

    Returns:
        HTML як рядок

    Raises:
        RuntimeError: якщо сторінка не завантажилась за таймаут
    """
    logger.debug("Scraper: відкриваю %s", url)

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
            await page.goto(url, wait_until="networkidle", timeout=_PAGE_TIMEOUT_MS)
            html = await page.content()
        except Exception as e:
            raise RuntimeError(f"Не вдалось завантажити {url}: {e}") from e
        finally:
            await browser.close()

    logger.debug("Scraper: отримано %d символів для %s", len(html), url)
    return html
