from pydantic import BaseModel, Field


class EvidenceClaim(BaseModel):
    claim: str = Field(
        description="One concise, standalone factual statement supported by the transcript"
    )
    speaker: str = Field(
        default="Not identified",
        description="Speaker name or role if identifiable from the transcript, else 'Not identified'",
    )
    page: int = Field(description="Original transcript page number")
    quote: str = Field(
        description="Exact verbatim supporting quote copied from the transcript"
    )
    category: str = Field(
        description="One of: management, guidance, segment, metric, strategic_commitment, other"
    )


class QAItem(BaseModel):
    analyst: str = Field(
        default="Not identified",
        description="Analyst name if explicitly stated in the transcript, else 'Not identified'",
    )
    firm: str = Field(
        default="Not identified",
        description="Brokerage or institution name if explicitly stated, else 'Not identified'",
    )
    question: str = Field(
        description="Concise summary of the analyst's question"
    )
    answer: str = Field(
        description="Concise summary of management's response"
    )
    page: int = Field(
        description="Original transcript page number where this Q&A occurs or begins"
    )
    supporting_quotes: list[str] = Field(
        default_factory=list,
        description="1 to 3 exact verbatim quotes from the transcript supporting both the question and management's answer",
    )


class RiskItem(BaseModel):
    risk: str = Field(
        description="Concise description of the risk, challenge, or uncertainty"
    )
    risk_category: str = Field(
        description=(
            "One of: credit, asset_quality, deposit_liquidity, nim_margin, "
            "interest_rate, regulatory, macroeconomic, operational, technology_cyber, other"
        )
    )
    source_type: str = Field(
        description=(
            "One of: management_acknowledged, analyst_raised, inferred_from_discussion"
        )
    )
    speaker: str = Field(
        default="Not identified",
        description="Speaker name or role if identifiable, else 'Not identified'",
    )
    page: int = Field(description="Original transcript page number")
    quote: str = Field(
        description="Exact verbatim supporting quote copied from the transcript"
    )


class FactBatch(BaseModel):
    quarter: str = Field(
        default="Not identified",
        description="Earnings quarter if explicitly stated in this chunk (e.g., 'Q2 FY27'), else 'Not identified'",
    )
    call_date: str = Field(
        default="Not identified",
        description="Actual conference call date (not the exchange filing date) if explicitly stated in this chunk, else 'Not identified'",
    )
    facts: list[EvidenceClaim] = Field(default_factory=list)
    qa_items: list[QAItem] = Field(default_factory=list)
    risks: list[RiskItem] = Field(default_factory=list)


class ConcallSummary(BaseModel):
    company: str
    symbol: str
    scrip_code: str = "Not identified"
    quarter: str = "Not identified"
    call_date: str = "Not identified"
    source: str = "NSE"
    source_url: str = ""

    tldr: list[EvidenceClaim] = Field(default_factory=list)
    management_commentary: list[EvidenceClaim] = Field(default_factory=list)
    key_metrics: list[EvidenceClaim] = Field(default_factory=list)
    segment_performance: list[EvidenceClaim] = Field(default_factory=list)
    guidance_outlook: list[EvidenceClaim] = Field(default_factory=list)
    notable_qa: list[QAItem] = Field(default_factory=list)
    risks: list[RiskItem] = Field(default_factory=list)
    strategic_commitments: list[EvidenceClaim] = Field(default_factory=list)

    limitations: list[str] = Field(default_factory=list)