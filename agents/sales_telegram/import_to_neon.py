import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from agents.sales_telegram.common import FORMATTED_DIR  # noqa: E402


async def import_file(path: Path, dry_run: bool) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    result = {
        "path": str(path),
        "client_id": data["client_id"],
        "user_id": data["user_id"],
        "source": data["source"],
        "messages": len(data["messages"]),
        "pairs": data.get("stats", {}).get("pairs", 0),
    }
    if not dry_run:
        from core import db

        await db.upsert_dialog_messages(
            client_id=data["client_id"],
            user_id=data["user_id"],
            source=data["source"],
            messages=data["messages"],
            client_name=data.get("client_name") or None,
        )
    return result


async def import_all(input_path: Path, dry_run: bool) -> list[dict]:
    if not input_path.exists():
        return []
    files = sorted(input_path.glob("*.json")) if input_path.is_dir() else [input_path]
    if not dry_run:
        from core import db

        await db.init()
    try:
        return [await import_file(path, dry_run) for path in files]
    finally:
        if not dry_run:
            from core import db

            await db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Import formatted Telegram sales dialogs to Neon dialogs.")
    parser.add_argument("--input", default=str(FORMATTED_DIR), help="Formatted JSON file or directory.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    results = asyncio.run(import_all(Path(args.input), args.dry_run))
    total_messages = sum(r["messages"] for r in results)
    total_pairs = sum(r["pairs"] for r in results)
    for r in results:
        print(f"{'DRY ' if args.dry_run else ''}import {r['user_id']} messages={r['messages']} pairs={r['pairs']}")
    print(f"Done: chats={len(results)} messages={total_messages} pairs={total_pairs}")


if __name__ == "__main__":
    main()
