from dataclasses import dataclass, field
from typing import Optional
import uuid


@dataclass
class AgentMessage:
    content: str
    client_id: str
    input_type: str = "text"  # "text" | "image" | "audio"
    context: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class AgentResult:
    content: str
    confidence: float
    needs_human: bool
    cost_usd: float
    trace_id: str
    agent_id: str
    client_id: str
    model_used: str
    input_tokens: int
    output_tokens: int
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class PsychologistResult:
    sentiment: str          # positive | neutral | frustrated | toxic
    buy_intent: str         # HIGH | MEDIUM | LOW
    is_toxic: bool
    recommended_model: str
    escalation_required: bool
    analysis_note: str


@dataclass
class OrchestratorDecision:
    trace_id: str
    client_id: str
    selected_agents: list
    task_breakdown: dict
    priority: str           # high | medium | low
    routing_reason: str
    estimated_cost_usd: float


@dataclass
class BrainRecord:
    record_id: str
    trace_id: str
    client_id: str
    timestamp: str
    agent_id: str
    model_used: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    task: str
    result: str             # success | partial | failed
    confidence: float
    needs_human: bool
    sentiment: str
    prompt_version: str
    error: Optional[str] = None
