import argparse
import asyncio
import csv
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from agents.sales_telegram.common import (  # noqa: E402
    DATA_DIR,
    add_date_args,
    as_utc,
    make_client,
    parse_kyiv_day_end,
    safe_name,
    telethon_offset_after,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


async def _probe_before_until(reader, entity, offset_date, until_utc, probe_limit: int):
    first_before_until = None
    count_probe = 0
    if probe_limit <= 0:
        return first_before_until, count_probe
    async for msg in reader.iter_messages(
        entity,
        offset_date=offset_date,
        limit=probe_limit,
    ):
        if not msg.date:
            continue
        msg_date = as_utc(msg.date)
        if msg_date > until_utc:
            continue
        first_before_until = msg if first_before_until is None else first_before_until
        count_probe += 1
    return first_before_until, count_probe


async def list_private_chats(until: str, output: Path, probe_limit: int) -> int:
    until_utc = parse_kyiv_day_end(until)
    offset_date = telethon_offset_after(until_utc)
    rows: list[dict] = []

    async with make_client() as client:
        me = await client.get_me()
        logger.info("Telegram connected as %s (id=%s)", me.first_name, me.id)

        dialogs = []
        async for dialog in client.iter_dialogs():
            if not dialog.is_user:
                continue
            entity = dialog.entity
            if getattr(entity, "bot", False):
                continue
            if getattr(entity, "is_self", False):
                continue
            dialogs.append(dialog)

        rows = await _build_rows(client, dialogs, offset_date, until_utc, probe_limit)

    rows.sort(key=lambda r: r["sample_msg_before_until"] or r["last_dialog_activity"], reverse=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "chat_id",
            "name",
            "username",
            "last_dialog_activity",
            "sample_msg_before_until",
            "probe_messages_before_until",
        ], delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    logger.info("Saved %d private chats to %s", len(rows), output)
    return len(rows)


async def _build_rows(reader, dialogs, offset_date, until_utc, probe_limit: int) -> list[dict]:
    rows = []
    for dialog in dialogs:
        entity = dialog.entity
        first_before_until, count_probe = await _probe_before_until(
            reader,
            entity,
            offset_date,
            until_utc,
            probe_limit,
        )

        if probe_limit > 0 and not first_before_until:
            continue

        full_name = " ".join(
                part for part in [
                    getattr(entity, "first_name", "") or "",
                    getattr(entity, "last_name", "") or "",
                ] if part
        ).strip() or getattr(entity, "title", "") or str(entity.id)

        rows.append({
            "chat_id": entity.id,
            "name": full_name,
            "username": getattr(entity, "username", "") or "",
            "last_dialog_activity": dialog.date.isoformat() if dialog.date else "",
            "sample_msg_before_until": as_utc(first_before_until.date).isoformat() if first_before_until else "",
            "probe_messages_before_until": count_probe,
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="List private Telegram chats with history before --until.")
    add_date_args(parser)
    parser.add_argument(
        "--output",
        default=None,
        help="TSV output path. Default: data/sales_telegram/chats_until_<date>.tsv",
    )
    parser.add_argument(
        "--probe-limit",
        type=int,
        default=200,
        help="How many old messages to probe per chat for rough volume. Use 0 to list dialogs without history probing.",
    )
    args = parser.parse_args()

    output = Path(args.output) if args.output else DATA_DIR / f"chats_until_{safe_name(args.until)}.tsv"
    count = asyncio.run(list_private_chats(args.until, output, args.probe_limit))
    print(f"Saved {count} chats: {output}")


if __name__ == "__main__":
    main()
