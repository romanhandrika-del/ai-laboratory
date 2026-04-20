"""
Technical Checker — перевіряє технічний стан сайту.
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests

from core.logger import get_logger

logger = get_logger(__name__)

_TIMEOUT = 15
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AuditBot/1.0)"}


def _fetch_main(url: str) -> tuple:
    t0 = time.perf_counter()
    resp = requests.get(url, timeout=_TIMEOUT, headers=_HEADERS, allow_redirects=True)
    rt = round((time.perf_counter() - t0) * 1000)
    chain = [r.url for r in resp.history] if resp.history else []
    return resp.status_code, chain, rt


def _fetch_robots(base: str) -> tuple[bool, bool]:
    r = requests.get(urljoin(base, "/robots.txt"), timeout=_TIMEOUT, headers=_HEADERS)
    if r.status_code != 200:
        return False, False
    disallow_all = any(l.strip().lower() == "disallow: /" for l in r.text.splitlines())
    return True, disallow_all


def _fetch_sitemap(base: str) -> tuple[bool, str | None]:
    for path in ["/sitemap.xml", "/sitemap_index.xml", "/sitemap"]:
        try:
            r = requests.get(urljoin(base, path), timeout=_TIMEOUT, headers=_HEADERS)
            ct = r.headers.get("content-type", "")
            if r.status_code == 200 and ("xml" in ct or "<urlset" in r.text or "<sitemapindex" in r.text):
                return True, urljoin(base, path)
        except Exception:
            continue
    return False, None


def check(url: str) -> dict:
    """
    Перевіряє технічні характеристики сайту (3 запити паралельно).

    Returns dict:
        https, status_code, redirect_chain,
        robots_txt_exists, robots_txt_disallow_all,
        sitemap_exists, sitemap_url,
        response_time_ms
    """
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    https = parsed.scheme == "https"

    status_code = None
    redirect_chain: list = []
    response_time_ms = None
    robots_txt_exists = False
    robots_txt_disallow_all = False
    sitemap_exists = False
    sitemap_url = None

    tasks = {
        "main": lambda: _fetch_main(url),
        "robots": lambda: _fetch_robots(base),
        "sitemap": lambda: _fetch_sitemap(base),
    }

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(fn): key for key, fn in tasks.items()}
        for future in as_completed(futures):
            key = futures[future]
            try:
                result = future.result()
                if key == "main":
                    status_code, redirect_chain, response_time_ms = result
                elif key == "robots":
                    robots_txt_exists, robots_txt_disallow_all = result
                elif key == "sitemap":
                    sitemap_exists, sitemap_url = result
            except Exception as e:
                logger.warning("TechnicalChecker[%s]: %s", key, e)

    result = {
        "https": https,
        "status_code": status_code,
        "redirect_chain": redirect_chain[:5],
        "robots_txt_exists": robots_txt_exists,
        "robots_txt_disallow_all": robots_txt_disallow_all,
        "sitemap_exists": sitemap_exists,
        "sitemap_url": sitemap_url,
        "response_time_ms": response_time_ms,
    }

    logger.info(
        "TechnicalChecker: https=%s status=%s robots=%s sitemap=%s rt=%sms",
        https, status_code, robots_txt_exists, sitemap_exists, response_time_ms,
    )
    return result
