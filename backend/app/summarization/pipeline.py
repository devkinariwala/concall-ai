import json
import logging
from pathlib import Path
from app.ingestion.state import IngestionState
from app.core.companies import COMPANIES
from app.summarization.evidence import (
    normalize_for_match,
    validate_claims,
    validate_qa_items,
    validate_risks,
)
from app.summarization.gemini_client import GeminiSummarizer
from app.summarization.schemas import ConcallSummary, FactBatch

logger = logging.getLogger(__name__)

EXTRACTED_DIR = Path("backend/data/extracted")
SUMMARY_JSON_DIR = Path("backend/data/summaries/json")
SUMMARY_MD_DIR = Path("backend/data/summaries/markdown")
CHECKPOINT_DIR = Path("backend/data/summaries/checkpoints")

SCHEMA_VERSION = 2

CLAIM_SECTIONS = [
    "tldr",
    "management_commentary",
    "key_metrics",
    "segment_performance",
    "guidance_outlook",
    "strategic_commitments",
]


FACT_PROMPT = """
You are an expert equity research analyst extracting structured, evidence-backed
information from an Indian listed company's earnings conference-call transcript.

Extract ONLY material information explicitly stated in the supplied transcript chunk.
Do not use outside knowledge, do not calculate derived numbers, and do not invent
names, dates, or figures.

1. METADATA (quarter, call_date):
- Extract `quarter` (e.g., "Q2 FY27") and `call_date` (e.g., "October 17, 2026")
  ONLY if explicitly stated in this chunk as the conference call title/date.
- Do NOT use the exchange filing cover-letter date as `call_date`.
- If not explicitly stated in this chunk, return "Not identified".

2. FACTS (`facts` list):
- Extract all material facts: management commentary, financial metrics (with exact
  units, currencies, percentages, and periods), business-segment performance,
  forward guidance/outlook, and major strategic commitments.
- Assign `category` from: management, guidance, segment, metric, strategic_commitment, other.
- Only use `segment` for the company's actual business verticals/segments (e.g.,
  Retail, Wholesale/Corporate, MSME, Treasury). Do NOT classify general
  macroeconomic or agricultural sowing commentary as segment performance.
- Identify `speaker` (name or role) when clear from the transcript, else "Not identified".
- Include the exact `page` number from the [PAGE N] marker immediately preceding the quote.
- Copy `quote` verbatim from a single contiguous passage (at least 15 characters).
  Do NOT stitch together non-contiguous sentences or alter wording.

3. ANALYST Q&A (`qa_items` list):
- Extract every substantive analyst question and management's corresponding answer
  present in this chunk.
- Record `analyst` and `firm` ONLY if explicitly stated; otherwise "Not identified".
- Summarize the `question` and `answer` concisely without turning an analyst's
  assumption into a management commitment.
- Set `page` to the [PAGE N] number where the exchange begins.
- Provide 1 to 3 verbatim `supporting_quotes` (at least 15 characters each) copied
  directly from the transcript covering the question and/or management's answer.

4. RISKS & UNCERTAINTIES (`risks` list):
- Explicitly capture credit, asset-quality, deposit/liquidity, NIM/margin,
  interest-rate/monetary-policy, regulatory, macroeconomic, operational, and
  technology/cyber risks or headwinds discussed in this chunk.
- Set `risk_category` from: credit, asset_quality, deposit_liquidity, nim_margin,
  interest_rate, regulatory, macroeconomic, operational, technology_cyber, other.
- Set `source_type` accurately:
  - `management_acknowledged`: explicitly stated or acknowledged by management.
  - `analyst_raised`: raised by an analyst in a question (do NOT present as confirmed fact).
  - `inferred_from_discussion`: uncertainty or headwind clearly evidenced in discussion.
- Include `speaker`, exact `page`, and a verbatim `quote` (at least 15 characters).

Ignore greetings, operator boilerplate, and cover-letter formalities unless material.

TRANSCRIPT CHUNK:
"""


SUMMARY_PROMPT = """
You are preparing an institutional-grade, evidence-backed earnings call summary
for an Indian listed company.

Use ONLY the supplied extracted metadata, facts, Q&A items, and risks. Do not add
facts from memory or outside knowledge.

STRICT RULES:
- Every claim, Q&A item, and risk in the output MUST retain its exact original
  `page` number and verbatim `quote` / `supporting_quotes` from the supplied inputs.
- You may tighten claim/summary wording slightly for clarity, but NEVER alter
  numbers, units, dates, speaker attributions, or quotes.
- Set `quarter` and `call_date` from the supplied `metadata` if available (do NOT
  use the exchange filing date).
- `tldr`: 4 to 6 of the highest-impact takeaways for an investor.
- `management_commentary`: key narrative highlights, tone, and operational drivers.
- `key_metrics`: core financial numbers with exact units and periods.
- `segment_performance`: performance of the company's actual business segments only
  (do NOT include general macro or agricultural sowing stats here).
- `guidance_outlook`: ONLY explicit forward-looking targets, expectations, or outlook
  stated by management.
- `notable_qa`: the sharpest, most informative analyst Q&A pairs (keep analyst, firm,
  question, answer, page, and supporting_quotes).
- `risks`: material risks and headwinds, preserving `risk_category` and `source_type`
  (never present an `analyst_raised` question as a confirmed company risk).
- `strategic_commitments`: major multi-quarter commitments, structural shifts, or
  capital/operational priorities stated by management.
- Avoid duplicate items within the same section. A key metric may appear in `tldr`
  and `key_metrics` if essential, but do not repeat the same point inside one section.
- If a section genuinely has no supporting evidence, return an empty list.

EXTRACTED EVIDENCE:
"""


def all_summary_claims(summary: ConcallSummary):
    return [
        claim
        for section_name in CLAIM_SECTIONS
        for claim in getattr(summary, section_name)
    ]


def deduplicate_claims(claims: list) -> list:
    seen = set()
    unique = []
    for item in claims:
        key = (item.page, normalize_for_match(item.quote))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def deduplicate_qa(qa_items: list) -> list:
    seen = set()
    unique = []
    for item in qa_items:
        key = (item.page, normalize_for_match(item.question)[:80])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def deduplicate_risks(risks: list) -> list:
    seen = set()
    unique = []
    for item in risks:
        key = (item.page, normalize_for_match(item.quote))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def save_json_atomic(path: Path, payload: dict):
    """Write JSON safely so an interrupted run doesn't leave a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary_path.replace(path)


def save_markdown(summary: ConcallSummary, path: Path):
    claim_sections = [
        ("Executive TL;DR", summary.tldr),
        ("Management Commentary", summary.management_commentary),
        ("Financial Performance & Key Metrics", summary.key_metrics),
        ("Segment-wise Performance", summary.segment_performance),
        ("Management Guidance & Outlook", summary.guidance_outlook),
        ("Strategic Commitments", summary.strategic_commitments),
    ]

    lines = [
        f"# {summary.company} ({summary.symbol}) - Earnings Call Summary",
        "",
        f"**Quarter:** {summary.quarter}",
        f"**Call Date:** {summary.call_date}",
        "",
        "> Every factual claim, Q&A exchange, and risk is traceable to its original transcript page and verbatim quotation.",
        "",
    ]

    for heading, claims in claim_sections:
        lines.extend([f"## {heading}", ""])
        if not claims:
            lines.extend(["Not disclosed in the extracted transcript.", ""])
            continue

        for item in claims:
            speaker_tag = (
                f" | **Speaker:** {item.speaker}"
                if item.speaker and item.speaker != "Not identified"
                else ""
            )
            lines.append(f"- {item.claim} *(Page {item.page}{speaker_tag})*")
            lines.append(f'  > "{item.quote}"')
            lines.append("")

    # Notable Q&A
    lines.extend(["## Notable Analyst Q&A", ""])
    if not summary.notable_qa:
        lines.extend(["Not disclosed in the extracted transcript.", ""])
    else:
        for qa in summary.notable_qa:
            who = qa.analyst
            if qa.firm and qa.firm != "Not identified":
                who = f"{qa.analyst} ({qa.firm})"
            lines.append(f"### {who} - *(Page {qa.page})*")
            lines.append(f"- **Q:** {qa.question}")
            lines.append(f"- **A:** {qa.answer}")
            for quote in qa.supporting_quotes:
                lines.append(f'  > "{quote}"')
            lines.append("")

    # Risks & Uncertainties
    lines.extend(["## Risks & Uncertainties", ""])
    if not summary.risks:
        lines.extend(["Not disclosed in the extracted transcript.", ""])
    else:
        for risk in summary.risks:
            source_label = risk.source_type.replace("_", " ").title()
            cat_label = risk.risk_category.replace("_", " ").title()
            lines.append(
                f"- **[{cat_label} | {source_label}]** {risk.risk} *(Page {risk.page})*"
            )
            lines.append(f'  > "{risk.quote}"')
            lines.append("")

    if summary.limitations:
        lines.extend(["## Limitations & Validation Notes", ""])
        lines.extend(f"- {item}" for item in summary.limitations)
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _fresh_checkpoint(source_name: str, chunk_count: int) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "source_file": source_name,
        "chunk_count": chunk_count,
        "metadata": {"quarter": "Not identified", "call_date": "Not identified"},
        "completed_chunks": {},
        "rejected_counts": {"facts": 0, "qa": 0, "risks": 0},
    }


def load_checkpoint(checkpoint_path: Path, source_name: str, chunk_count: int) -> dict:
    if not checkpoint_path.exists():
        return _fresh_checkpoint(source_name, chunk_count)

    try:
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if (
            checkpoint.get("schema_version") != SCHEMA_VERSION
            or checkpoint.get("source_file") != source_name
            or checkpoint.get("chunk_count") != chunk_count
        ):
            logger.warning(
                "Checkpoint version or source mismatch. Starting a fresh checkpoint."
            )
            return _fresh_checkpoint(source_name, chunk_count)
        return checkpoint
    except (json.JSONDecodeError, OSError):
        logger.warning("Invalid checkpoint. Starting a fresh one.")
        return _fresh_checkpoint(source_name, chunk_count)


def process_one(json_path: Path, ai: GeminiSummarizer):
    data = json.loads(json_path.read_text(encoding="utf-8"))
    transcript = data["transcript"]
    chunks = data["chunks"]

    checkpoint_path = CHECKPOINT_DIR / f"{json_path.stem}.json"
    checkpoint = load_checkpoint(checkpoint_path, json_path.name, len(chunks))
    completed = checkpoint["completed_chunks"]

    logger.info(
        "Processing %s chunks. %s already completed.",
        len(chunks),
        len(completed),
    )

    for position, chunk in enumerate(chunks, start=1):
        chunk_id = str(chunk["chunk_index"])

        if chunk_id in completed:
            logger.info(
                "Skipping chunk %s/%s - already checkpointed",
                position,
                len(chunks),
            )
            continue

        logger.info("Processing chunk %s/%s", position, len(chunks))
        prompt = FACT_PROMPT + "\n" + chunk["text"]
        batch = ai.generate_structured(prompt, FactBatch)

        valid_facts, rejected_facts = validate_claims(batch.facts, transcript)
        valid_qa, rejected_qa = validate_qa_items(batch.qa_items, transcript)
        valid_risks, rejected_risks = validate_risks(batch.risks, transcript)

        if (
            checkpoint["metadata"]["quarter"] == "Not identified"
            and batch.quarter
            and batch.quarter != "Not identified"
        ):
            checkpoint["metadata"]["quarter"] = batch.quarter

        if (
            checkpoint["metadata"]["call_date"] == "Not identified"
            and batch.call_date
            and batch.call_date != "Not identified"
        ):
            checkpoint["metadata"]["call_date"] = batch.call_date

        completed[chunk_id] = {
            "facts": [f.model_dump() for f in valid_facts],
            "qa_items": [q.model_dump() for q in valid_qa],
            "risks": [r.model_dump() for r in valid_risks],
        }

        checkpoint["rejected_counts"]["facts"] += len(rejected_facts)
        checkpoint["rejected_counts"]["qa"] += len(rejected_qa)
        checkpoint["rejected_counts"]["risks"] += len(rejected_risks)

        save_json_atomic(checkpoint_path, checkpoint)

        logger.info(
            "Chunk %s completed: facts=%s (rej %s), qa=%s (rej %s), risks=%s (rej %s)",
            chunk["chunk_index"],
            len(valid_facts),
            len(rejected_facts),
            len(valid_qa),
            len(rejected_qa),
            len(valid_risks),
            len(rejected_risks),
        )

    # Reconstruct all validated evidence from checkpoint.
    all_facts = []
    all_qa = []
    all_risks = []

    for chunk in chunks:
        chunk_data = completed.get(str(chunk["chunk_index"]), {})
        all_facts.extend(chunk_data.get("facts", []))
        all_qa.extend(chunk_data.get("qa_items", []))
        all_risks.extend(chunk_data.get("risks", []))

    if not (all_facts or all_qa or all_risks):
        raise ValueError(f"No evidence-backed data extracted from {json_path.name}")

    logger.info(
        "Evidence extraction complete: %s facts, %s Q&A items, %s risks",
        len(all_facts),
        len(all_qa),
        len(all_risks),
    )

    evidence_payload = {
        "metadata": checkpoint["metadata"],
        "facts": all_facts,
        "qa_items": all_qa,
        "risks": all_risks,
    }

    prompt = SUMMARY_PROMPT + "\n" + json.dumps(evidence_payload, ensure_ascii=False)
    logger.info("Generating final structured summary")
    summary = ai.generate_structured(prompt, ConcallSummary)

    # Validate final claims, Q&A, and risks against the full original transcript.
    valid_claims, rejected_claims = validate_claims(
        all_summary_claims(summary), transcript
    )
    valid_claim_ids = {id(item) for item in valid_claims}

    for section_name in CLAIM_SECTIONS:
        filtered = [
            item
            for item in getattr(summary, section_name)
            if id(item) in valid_claim_ids
        ]
        setattr(summary, section_name, deduplicate_claims(filtered))

    valid_qa, rejected_qa = validate_qa_items(summary.notable_qa, transcript)
    summary.notable_qa = deduplicate_qa(valid_qa)

    valid_risks, rejected_risks = validate_risks(summary.risks, transcript)
    summary.risks = deduplicate_risks(valid_risks)

    total_final_rejected = len(rejected_claims) + len(rejected_qa) + len(rejected_risks)
    if total_final_rejected:
        summary.limitations.append(
            f"{total_final_rejected} generated summary items were removed during "
            "final full-transcript quote/page validation."
        )

    # Fallback to chunk-extracted metadata if summary missed it.
    if not summary.quarter or summary.quarter == "Not identified":
        summary.quarter = checkpoint["metadata"]["quarter"]
    if not summary.call_date or summary.call_date == "Not identified":
        summary.call_date = checkpoint["metadata"]["call_date"]

    company = data["company"]
    company_info = COMPANIES.get(company, {})
    summary.company = company_info.get("name", company)
    summary.symbol = company

    summary.scrip_code = company_info.get("bse_code", "Not identified")

    state = IngestionState()
    try:
        src_meta = state.get_source_metadata(json_path.stem)
    finally:
        state.close()

    summary.source = src_meta["source"]
    summary.source_url = src_meta["source_url"]

    rej = checkpoint["rejected_counts"]
    summary.limitations.append(
        f"Chunk-level validation rejected {rej['facts']} facts, "
        f"{rej['qa']} Q&A items, and {rej['risks']} risks."
    )

    output_name = json_path.stem
    json_output = SUMMARY_JSON_DIR / f"{output_name}.json"
    md_output = SUMMARY_MD_DIR / f"{output_name}.md"

    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    save_markdown(summary, md_output)

    logger.info("Saved JSON summary: %s", json_output)
    logger.info("Saved Markdown summary: %s", md_output)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    ai = GeminiSummarizer()

    # Keep restricted to HDFC Bank until the upgraded pipeline is validated.
    files = sorted(EXTRACTED_DIR.glob("*/*.json"))
    logger.info("Found %s extracted transcripts", len(files))

    for file_path in files:
        try:
            logger.info("Summarising %s", file_path.name)
            process_one(file_path, ai)
        except Exception:
            logger.exception(
                "Failed to summarise %s. Completed chunks have been checkpointed.",
                file_path.name,
            )


if __name__ == "__main__":
    main()