import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.sales_telegram.common import FORMATTED_DIR, RAW_DIR, SOURCE, anonymize_text  # noqa: E402


def _message_content(msg: dict) -> str:
    parts = []
    text = anonymize_text(msg.get("text") or "")
    media = msg.get("media") or ""
    if text:
        parts.append(text)
    if media:
        parts.append(media)
    return "\n".join(parts).strip()


def format_raw_dialog(raw: dict) -> dict:
    normalized: list[dict] = []
    for msg in raw.get("messages", []):
        content = _message_content(msg)
        if not content:
            continue
        role = "assistant" if msg.get("out") else "user"
        meta = {
            "source": SOURCE,
            "telegram_message_id": msg.get("message_id"),
        }
        if role == "assistant":
            meta.update({
                "by": "manager",
                "confidence": 1.0,
                "needs_human": False,
                "model_used": "human_manager",
                "cost_usd": 0.0,
            })
        normalized.append({
            "role": role,
            "content": content,
            "ts": msg.get("date", ""),
            "meta": meta,
        })

    merged: list[dict] = []
    for msg in normalized:
        if merged and merged[-1]["role"] == msg["role"]:
            merged[-1]["content"] = merged[-1]["content"] + "\n" + msg["content"]
            merged[-1]["meta"].setdefault("telegram_message_ids", [])
            merged[-1]["meta"]["telegram_message_ids"].append(msg["meta"].get("telegram_message_id"))
        else:
            merged.append(msg)

    return {
        "client_id": "etalhome",
        "user_id": f"tg_{raw['chat_id']}",
        "source": SOURCE,
        "client_name": anonymize_text(raw.get("label") or ""),
        "raw_chat_id": raw["chat_id"],
        "messages": merged,
        "stats": {
            "raw_messages": len(raw.get("messages", [])),
            "formatted_messages": len(merged),
            "pairs": sum(1 for i in range(len(merged) - 1) if merged[i]["role"] == "user" and merged[i + 1]["role"] == "assistant"),
        },
    }


def format_file(input_path: Path, output_dir: Path) -> Path:
    raw = json.loads(input_path.read_text(encoding="utf-8"))
    formatted = format_raw_dialog(raw)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / input_path.name
    output_path.write_text(json.dumps(formatted, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Format raw Telegram dialogs for Neon import.")
    parser.add_argument("--input", default=str(RAW_DIR), help="Raw JSON file or directory.")
    parser.add_argument("--output-dir", default=str(FORMATTED_DIR))
    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    files = sorted(input_path.glob("*.json")) if input_path.is_dir() else [input_path]
    for path in files:
        out = format_file(path, output_dir)
        print(f"Formatted: {out}")


if __name__ == "__main__":
    main()

