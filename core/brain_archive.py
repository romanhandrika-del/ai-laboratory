from abc import ABC, abstractmethod
from core.message import BrainRecord
import datetime
import uuid


class BrainArchiveBackend(ABC):
    """Абстрактний бекенд Brain Archive. Swappable: Sheets v1 → pgvector v2."""

    @abstractmethod
    def write(self, record: BrainRecord) -> None:
        pass

    @abstractmethod
    def get_recent(self, client_id: str, limit: int = 50) -> list[BrainRecord]:
        pass

    @abstractmethod
    def get_stats(self, client_id: str, hours: int = 24) -> dict:
        pass


class GoogleSheetsBrainArchive(BrainArchiveBackend):
    """Brain Archive v1 — Google Sheets."""

    def __init__(self, sheet_id: str, credentials_json: str):
        self.sheet_id = sheet_id
        self.credentials_json = credentials_json
        self._client = None

    def _get_client(self):
        if self._client is None:
            import gspread
            import json
            from google.oauth2.service_account import Credentials
            creds = Credentials.from_service_account_info(
                json.loads(self.credentials_json),
                scopes=["https://www.googleapis.com/auth/spreadsheets"]
            )
            self._client = gspread.authorize(creds)
        return self._client

    def write(self, record: BrainRecord) -> None:
        gc = self._get_client()
        sheet = gc.open_by_key(self.sheet_id).sheet1
        row = [
            record.record_id,
            record.trace_id,
            record.client_id,
            record.timestamp,
            record.agent_id,
            record.model_used,
            record.input_tokens,
            record.output_tokens,
            round(record.cost_usd, 6),
            record.task,
            record.result,
            round(record.confidence, 3),
            record.needs_human,
            record.sentiment,
            record.prompt_version,
            record.error or "",
        ]
        sheet.append_row(row)

    def get_recent(self, client_id: str, limit: int = 50) -> list[BrainRecord]:
        # Заглушка — повна реалізація при потребі
        return []

    def get_stats(self, client_id: str, hours: int = 24) -> dict:
        # Заглушка — повна реалізація при потребі
        return {"total": 0, "success_rate": 0, "avg_cost_usd": 0}


def make_brain_record(
    result,
    task: str,
    sentiment: str,
    prompt_version: str,
) -> BrainRecord:
    """Утиліта для створення BrainRecord з AgentResult."""
    return BrainRecord(
        record_id=str(uuid.uuid4()),
        trace_id=result.trace_id,
        client_id=result.client_id,
        timestamp=datetime.datetime.utcnow().isoformat() + "Z",
        agent_id=result.agent_id,
        model_used=result.model_used,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost_usd=result.cost_usd,
        task=task,
        result="failed" if result.error else ("partial" if result.needs_human else "success"),
        confidence=result.confidence,
        needs_human=result.needs_human,
        sentiment=sentiment,
        prompt_version=prompt_version,
        error=result.error,
    )
