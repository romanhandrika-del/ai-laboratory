import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from agents.sales_telegram.collector import collect_whitelist  # noqa: E402
from agents.sales_telegram.common import FORMATTED_DIR, RAW_DIR, WHITELIST_PATH, add_date_args  # noqa: E402
from agents.sales_telegram.formatter import format_file  # noqa: E402
from agents.sales_telegram.import_to_neon import import_all  # noqa: E402


async def run(args) -> None:
    raw_dir = Path(args.raw_dir)
    formatted_dir = Path(args.formatted_dir)

    if not args.skip_collect:
        saved = await collect_whitelist(
            from_date=args.from_date,
            until=args.until,
            whitelist_path=Path(args.whitelist),
            output_dir=raw_dir,
            limit=args.limit,
        )
        print(f"Collected raw chats: {saved}")

    formatted_dir.mkdir(parents=True, exist_ok=True)
    raw_files = sorted(raw_dir.glob("*.json"))
    for path in raw_files:
        out = format_file(path, formatted_dir)
        print(f"Formatted: {out}")

    results = await import_all(formatted_dir, dry_run=args.dry_run)
    total_messages = sum(r["messages"] for r in results)
    total_pairs = sum(r["pairs"] for r in results)
    mode = "DRY RUN" if args.dry_run else "IMPORTED"
    print(f"{mode}: chats={len(results)} messages={total_messages} pairs={total_pairs}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect, format and import whitelisted Telegram sales history.")
    add_date_args(parser)
    parser.add_argument("--whitelist", default=str(WHITELIST_PATH))
    parser.add_argument("--raw-dir", default=str(RAW_DIR))
    parser.add_argument("--formatted-dir", default=str(FORMATTED_DIR))
    parser.add_argument("--limit", type=int, default=None, help="Optional per-chat message limit for tests.")
    parser.add_argument("--skip-collect", action="store_true", help="Use existing raw JSON files.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write to Neon.")
    args = parser.parse_args()

    asyncio.run(run(args))


if __name__ == "__main__":
    main()

