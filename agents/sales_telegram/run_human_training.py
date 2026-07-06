import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from agents.sales.human_trainer import run_human_training  # noqa: E402
from core import db  # noqa: E402


async def _main(client_id: str, limit: int) -> dict:
    await db.init()
    try:
        return await run_human_training(client_id, limit=limit)
    finally:
        await db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run trainer on human Telegram sales dialogs.")
    parser.add_argument("--client-id", default="etalhome")
    parser.add_argument("--limit", type=int, default=80)
    args = parser.parse_args()

    result = asyncio.run(_main(args.client_id, args.limit))
    if result.get("error"):
        print(f"ERROR: {result['error']}")
        raise SystemExit(1)
    print(f"written={result.get('written', 0)} pending={result.get('pending_count', 0)}")
    for s in result.get("suggestions", [])[:10]:
        print(f"- {s.get('type')} {s.get('priority')}: {s.get('suggestion')}")


if __name__ == "__main__":
    main()

