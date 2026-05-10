#!/usr/bin/env python3
"""
Seed-скрипт: завантажує prompt_template.md → prompts + prompt_versions у Neon.

Використання:
  python scripts/migrate_md_to_db.py [--target ig|tg|both] [--yes]

Flags:
  --target ig   (default) seeds sales_instagram
  --target tg   seeds sales_telegram (з etalhome/agents/sales.md)
  --target both seeds обидва
  --yes         пропустити підтвердження
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from core import db

_CLIENT_ID = "etalhome"
_IG_PATH = ROOT / "agents" / "sales" / "prompt_template.md"
_TG_PATH = ROOT.parent / "etalhome" / "agents" / "sales.md"


def _diff_preview(old: str | None, new: str) -> str:
    if old is None:
        return f"  [NEW] {len(new)} chars"
    if old == new:
        return "  [IDENTICAL — no change]"
    added = len(new) - len(old)
    return f"  [UPDATE] {len(old)} → {len(new)} chars ({'+' if added >= 0 else ''}{added})"


async def seed(target: str, confirm: bool) -> None:
    await db.init()

    seeds: list[tuple[str, Path]] = []
    if target in ("ig", "both"):
        seeds.append(("sales_instagram", _IG_PATH))
    if target in ("tg", "both"):
        seeds.append(("sales_telegram", _TG_PATH))

    for agent_id, path in seeds:
        if not path.exists():
            print(f"[SKIP] {agent_id}: файл не знайдено ({path})")
            continue

        new_text = path.read_text(encoding="utf-8").strip()
        existing = await db.get_current_prompt(_CLIENT_ID, agent_id)

        print(f"\n[{agent_id}]{_diff_preview(existing, new_text)}")
        if existing == new_text:
            print("  Пропускаємо — вміст ідентичний.")
            continue

        if existing is not None and not confirm:
            ans = input(f"  Перезаписати {agent_id}? [y/N] ").strip().lower()
            if ans != "y":
                print("  Скасовано.")
                continue

        ids = await db.apply_prompt_patch_multi([{
            "client_id": _CLIENT_ID,
            "agent_id": agent_id,
            "new_text": new_text,
            "applied_by": "seed_migrate_md",
        }])
        print(f"  ✅ Збережено версія #{ids[0]} → prompts ({_CLIENT_ID}/{agent_id})")

    await db.close()
    print("\nГотово.")


def main() -> None:
    p = argparse.ArgumentParser(description="Seed prompt_template.md → Neon")
    p.add_argument("--target", choices=("ig", "tg", "both"), default="ig")
    p.add_argument("--yes", action="store_true", help="Пропустити підтвердження")
    args = p.parse_args()
    asyncio.run(seed(args.target, confirm=args.yes))


if __name__ == "__main__":
    main()
