import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from agents.sales_telegram.common import (  # noqa: E402
    RAW_DIR,
    WHITELIST_PATH,
    add_date_args,
    as_utc,
    load_whitelist,
    make_client,
    parse_kyiv_day_end,
    parse_kyiv_day_start,
    safe_name,
    telethon_offset_after,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


def _media_placeholder(msg) -> str:
    if getattr(msg, "photo", None):
        return "[фото]"
    document = getattr(msg, "document", None)
    if document:
        mime = getattr(document, "mime_type", "") or ""
        if "pdf" in mime:
            return "[pdf]"
        if "image" in mime:
            return "[зображення]"
        return "[файл]"
    if getattr(msg, "media", None):
        return "[медіа]"
    return ""


async def collect_chat(client, chat_id: int, from_date: str | None, until: str, limit: int | None) -> dict:
    until_utc = parse_kyiv_day_end(until)
    from_utc = parse_kyiv_day_start(from_date)
    offset_date = telethon_offset_after(until_utc)
    entity = await client.get_entity(chat_id)

    messages: list[dict] = []
    async for msg in client.iter_messages(entity, offset_date=offset_date, limit=limit):
        if not msg.date:
            continue
        msg_date = as_utc(msg.date)
        if msg_date > until_utc:
            continue
        if from_utc and msg_date < from_utc:
            break

        text = (msg.message or "").strip()
        media = _media_placeholder(msg)
        if not text and not media:
            continue

        messages.append({
            "message_id": msg.id,
            "date": msg_date.isoformat(),
            "out": bool(msg.out),
            "text": text,
            "media": media,
        })

    messages.reverse()
    label = " ".join(
        part for part in [
            getattr(entity, "first_name", "") or "",
            getattr(entity, "last_name", "") or "",
        ] if part
    ).strip() or getattr(entity, "username", "") or str(chat_id)

    return {
        "chat_id": chat_id,
        "label": label,
        "username": getattr(entity, "username", "") or "",
        "from_date": from_date,
        "until": until,
        "source": "telegram_personal",
        "messages": messages,
    }


async def collect_whitelist(from_date: str | None, until: str, whitelist_path: Path, output_dir: Path, limit: int | None) -> int:
    chat_ids = load_whitelist(whitelist_path)
    if not chat_ids:
        raise RuntimeError(f"Whitelist порожній: {whitelist_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    async with make_client() as client:
        me = await client.get_me()
        logger.info("Telegram connected as %s (id=%s)", me.first_name, me.id)
        for chat_id in chat_ids:
            data = await collect_chat(client, chat_id, from_date, until, limit)
            out_path = output_dir / f"chat_{chat_id}_until_{safe_name(until)}.json"
            out_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("Saved chat_id=%s messages=%d to %s", chat_id, len(data["messages"]), out_path)
            saved += 1
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect Telegram history from whitelisted private chats.")
    add_date_args(parser)
    parser.add_argument("--whitelist", default=str(WHITELIST_PATH))
    parser.add_argument("--output-dir", default=str(RAW_DIR))
    parser.add_argument("--limit", type=int, default=None, help="Optional per-chat message limit for dry runs.")
    args = parser.parse_args()

    saved = asyncio.run(collect_whitelist(
        from_date=args.from_date,
        until=args.until,
        whitelist_path=Path(args.whitelist),
        output_dir=Path(args.output_dir),
        limit=args.limit,
    ))
    print(f"Saved raw history for {saved} chats")


if __name__ == "__main__":
    main()
