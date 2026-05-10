"""
agents/sales/patcher.py
Застосовує патчі промпту Sales Agent з pending_reviews.
"""
import re
import logging
from core import db

logger = logging.getLogger(__name__)

_CLIENT_ID = "etalhome"
_IG_AGENT_ID = "sales_instagram"
_TG_AGENT_ID = "sales_telegram"

# TELEGRAM_ONLY → патчимо тільки etalhome_telegram; SHARED → обидва
SECTION_SCOPE: dict[str, str] = {
    "product_pricing": "TELEGRAM_ONLY",
    "role": "SHARED",
    "communication_style": "SHARED",
    "dialog_rules": "SHARED",
    "calculation_rules": "SHARED",
    "objection_handling": "SHARED",
    "escalation_rules": "SHARED",
    "forbidden_actions": "SHARED",
    "handoff_triggers": "SHARED",
    "installation_rules": "SHARED",
    "product_terms": "SHARED",
}

SECTION_DELETE_LIMITS: dict[str, float] = {
    "product_pricing": 0.05,
    "forbidden_actions": 0.05,
    "role": 0.10,
    "product_terms": 0.10,
    "dialog_rules": 0.20,
    "handoff_triggers": 0.20,
    "communication_style": 0.20,
    "escalation_rules": 0.20,
    "installation_rules": 0.20,
    "examples": 0.50,
    "objection_handling": 0.50,
}
_DEFAULT_DELETE_LIMIT = 0.30

# Ці секції read-only — не патчити ніколи
_READONLY_SECTIONS = {"kb_placeholder", "system_flags"}


def _extract_section(prompt: str, section_id: str) -> tuple[str, int, int] | None:
    """Повертає (content, content_start, content_end) або None."""
    open_tag = f'<section id="{section_id}">'
    close_tag = "</section>"
    start = prompt.find(open_tag)
    if start == -1:
        return None
    content_start = start + len(open_tag)
    end = prompt.find(close_tag, content_start)
    if end == -1:
        return None
    return prompt[content_start:end], content_start, end


def _check_xml_integrity(text: str) -> bool:
    opens = re.findall(r'<section id="[^"]+">', text)
    closes = re.findall(r"</section>", text)
    return len(opens) == len(closes)


def _apply_text_patch(section_content: str, old_text: str, new_text: str) -> str:
    if old_text:
        return section_content.replace(old_text, new_text, 1)
    return new_text


async def apply_patch(review_id: int, applied_by: str = "manager") -> dict:
    """Застосовує патч із pending_reviews. Повертає {"ok", "status", "reason"}."""
    review = await db.get_trainer_review(review_id)
    if not review:
        return {"ok": False, "status": "not_found", "reason": "Review not found"}
    if review["status"] != "pending":
        return {"ok": False, "status": review["status"], "reason": f"Already {review['status']}"}

    section_id = review.get("section_id") or ""
    old_text = review.get("old_text") or ""
    new_text = review["new_text"]
    based_on_version_id = review.get("based_on_version_id")

    if section_id in _READONLY_SECTIONS:
        await db.update_trainer_review_status(review_id, "guard_failed", reviewed_by=applied_by)
        return {"ok": False, "status": "guard_failed", "reason": f"Section '{section_id}' is read-only"}

    ig_prompt = await db.get_current_prompt(_CLIENT_ID, _IG_AGENT_ID)
    if ig_prompt is None:
        return {"ok": False, "status": "guard_failed", "reason": "Instagram prompt not found in DB — run seed first"}

    # Stale check
    current_vid = await db.get_prompt_current_version_id(_CLIENT_ID, _IG_AGENT_ID)
    if based_on_version_id and current_vid and based_on_version_id != current_vid:
        await db.update_trainer_review_status(review_id, "stale", reviewed_by=applied_by)
        return {"ok": False, "status": "stale", "reason": "Prompt updated since this review was created"}

    # Extract section
    if section_id:
        extracted = _extract_section(ig_prompt, section_id)
        if extracted is None:
            await db.update_trainer_review_status(review_id, "guard_failed", reviewed_by=applied_by)
            return {"ok": False, "status": "guard_failed", "reason": f"Section '{section_id}' not found in prompt"}
        section_content, sec_start, sec_end = extracted
    else:
        section_content = ig_prompt
        sec_start, sec_end = 0, len(ig_prompt)

    # old_text guard
    if old_text and old_text not in section_content:
        await db.update_trainer_review_status(review_id, "guard_failed", reviewed_by=applied_by)
        return {"ok": False, "status": "guard_failed", "reason": "old_text not found in section"}

    # Ambiguous match guard
    if old_text and section_content.count(old_text) > 1:
        await db.update_trainer_review_status(review_id, "ambiguous_match", reviewed_by=applied_by)
        return {"ok": False, "status": "ambiguous_match", "reason": "old_text matches multiple places"}

    new_section = _apply_text_patch(section_content, old_text, new_text)

    # Delete limit guard
    limit = SECTION_DELETE_LIMITS.get(section_id, _DEFAULT_DELETE_LIMIT)
    if len(section_content) > 0:
        shrink = 1.0 - len(new_section) / len(section_content)
        if shrink > limit:
            await db.update_trainer_review_status(review_id, "guard_failed", reviewed_by=applied_by)
            return {
                "ok": False, "status": "guard_failed",
                "reason": f"Section would shrink by {shrink:.0%}, limit is {limit:.0%}",
            }

    new_ig_prompt = ig_prompt[:sec_start] + new_section + ig_prompt[sec_end:]

    if not _check_xml_integrity(new_ig_prompt):
        await db.update_trainer_review_status(review_id, "guard_failed", reviewed_by=applied_by)
        return {"ok": False, "status": "guard_failed", "reason": "XML integrity check failed"}

    # Build patch list
    scope = SECTION_SCOPE.get(section_id, "SHARED")
    patches = [{"client_id": _CLIENT_ID, "agent_id": _IG_AGENT_ID, "new_text": new_ig_prompt, "applied_by": applied_by}]

    if scope == "SHARED":
        tg_prompt = await db.get_current_prompt(_CLIENT_ID, _TG_AGENT_ID)
        if tg_prompt is not None and section_id:
            tg_extracted = _extract_section(tg_prompt, section_id)
            if tg_extracted is not None:
                tg_content, tg_start, tg_end = tg_extracted
                if not old_text or old_text in tg_content:
                    new_tg_section = _apply_text_patch(tg_content, old_text, new_text)
                    new_tg_prompt = tg_prompt[:tg_start] + new_tg_section + tg_prompt[tg_end:]
                    patches.append({
                        "client_id": _CLIENT_ID, "agent_id": _TG_AGENT_ID,
                        "new_text": new_tg_prompt, "applied_by": applied_by,
                    })

    version_ids = await db.apply_prompt_patch_multi(patches)
    await db.update_trainer_review_status(review_id, "approved", reviewed_by=applied_by)
    logger.info("Patch #%d approved: section=%s versions=%s", review_id, section_id, version_ids)
    return {"ok": True, "status": "approved", "version_ids": version_ids}


async def reject_patch(review_id: int, category: str = "other", reviewed_by: str = "manager") -> bool:
    review = await db.get_trainer_review(review_id)
    if not review or review["status"] != "pending":
        return False
    await db.update_trainer_review_status(review_id, "rejected", reject_category=category, reviewed_by=reviewed_by)
    logger.info("Patch #%d rejected: category=%s", review_id, category)
    return True


async def rollback_to_version(
    client_id: str,
    agent_id: str,
    version_id: int,
    applied_by: str,
) -> dict:
    """Створює нову версію з вмістом target_version (не переключення вказівника)."""
    target_text = await db.get_prompt_version_text(version_id)
    if target_text is None:
        return {"ok": False, "reason": "Version not found"}
    ids = await db.apply_prompt_patch_multi([{
        "client_id": client_id,
        "agent_id": agent_id,
        "new_text": target_text,
        "applied_by": f"rollback_by_{applied_by}",
    }])
    logger.info("Rollback to version %d for %s/%s → new version %d", version_id, client_id, agent_id, ids[0])
    return {"ok": True, "new_version_id": ids[0]}
