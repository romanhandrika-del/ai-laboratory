"""
PageSpeed Client — отримує метрики від Google PageSpeed Insights API v5.
"""

import os
import requests
from core.logger import get_logger

logger = get_logger(__name__)

_API_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
_TIMEOUT = 60


def fetch(url: str) -> dict:
    """
    Робить запит до PageSpeed Insights API.

    Returns dict:
        performance_score, seo_score, accessibility_score,
        lcp_ms, fid_ms, cls, fcp_ms, ttfb_ms,
        available (False якщо API недоступне)
    """
    api_key = os.getenv("GOOGLE_PAGESPEED_API_KEY", "")
    if not api_key:
        logger.warning("PageSpeed: GOOGLE_PAGESPEED_API_KEY не задано — пропускаємо")
        return {"available": False, "error": "API key не налаштовано"}

    params = {
        "url": url,
        "key": api_key,
        "strategy": "mobile",
        "category": ["performance", "seo", "accessibility"],
    }

    try:
        resp = requests.get(_API_URL, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("PageSpeed: помилка запиту для %s: %s", url, e)
        return {"available": False, "error": str(e)}

    cats = data.get("lighthouseResult", {}).get("categories", {})
    audits = data.get("lighthouseResult", {}).get("audits", {})

    def score(key: str) -> int | None:
        s = cats.get(key, {}).get("score")
        return round(s * 100) if s is not None else None

    def metric_ms(key: str) -> int | None:
        v = audits.get(key, {}).get("numericValue")
        return round(v) if v is not None else None

    def metric_val(key: str) -> float | None:
        v = audits.get(key, {}).get("numericValue")
        return round(v, 3) if v is not None else None

    result = {
        "available": True,
        "performance_score": score("performance"),
        "seo_score": score("seo"),
        "accessibility_score": score("accessibility"),
        "lcp_ms": metric_ms("largest-contentful-paint"),
        "fid_ms": metric_ms("max-potential-fid"),
        "cls": metric_val("cumulative-layout-shift"),
        "fcp_ms": metric_ms("first-contentful-paint"),
        "ttfb_ms": metric_ms("server-response-time"),
    }

    logger.info(
        "PageSpeed: perf=%s seo=%s a11y=%s LCP=%sms",
        result["performance_score"], result["seo_score"],
        result["accessibility_score"], result["lcp_ms"],
    )
    return result
