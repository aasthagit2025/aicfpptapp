from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List


DIMENSIONS = {
    "evidence_strength": {
        "label": "Evidence Strength",
        "weight": 0.20,
        "low_score_action": "Add stronger source support, sample detail, or verbatim evidence.",
    },
    "methodological_fit": {
        "label": "Methodological Fit",
        "weight": 0.15,
        "low_score_action": "Check whether the insight fits the research objective and method.",
    },
    "triangulation": {
        "label": "Triangulation / Consistency",
        "weight": 0.15,
        "low_score_action": "Compare against another data source, analyst read, or model run.",
    },
    "interpretability": {
        "label": "Interpretability",
        "weight": 0.10,
        "low_score_action": "Make the reasoning path clearer and reduce vague claims.",
    },
    "business_relevance": {
        "label": "Business Relevance",
        "weight": 0.15,
        "low_score_action": "Connect the insight more directly to a decision or market problem.",
    },
    "actionability": {
        "label": "Actionability",
        "weight": 0.15,
        "low_score_action": "Translate the insight into a practical recommendation or next step.",
    },
    "bias_risk": {
        "label": "Bias / Risk Control",
        "weight": 0.10,
        "low_score_action": "Review for hallucination, sampling bias, stereotype, or unsupported causality.",
    },
}


REQUIRED_COLUMNS = ["insight_id", "insight_text"]
MANUAL_SCORE_COLUMNS = list(DIMENSIONS.keys())


@dataclass
class AICFResult:
    insight_id: str
    theme: str
    insight_text: str
    evidence_note: str
    evidence_strength: int
    methodological_fit: int
    triangulation: int
    interpretability: int
    business_relevance: int
    actionability: int
    bias_risk: int
    weighted_score: float
    confidence_level: str
    review_status: str
    weakest_dimensions: str
    recommendation: str
    scoring_mode: str


def parse_score(value: object, column: str) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{column} must be an integer from 1 to 5.") from exc

    if score < 1 or score > 5:
        raise ValueError(f"{column} score {score} is outside the valid range of 1 to 5.")
    return score


def confidence_level(score: float) -> str:
    if score >= 4.00:
        return "High Confidence"
    if score >= 3.50:
        return "Moderate Confidence"
    if score >= 2.50:
        return "Low-Moderate Confidence"
    return "Low Confidence"


def clamp_score(score: int) -> int:
    return max(1, min(5, score))


def has_numeric_evidence(text: str) -> bool:
    return bool(re.search(r"(\b\d+(\.\d+)?\s*(%|/5|/10|respondents?|mean|score|rating|top)|\b(n|base)\s*=\s*\d+)", text, re.I))


def contains_any(text: str, words: List[str]) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in words)


def evidence_strength_score(text: str, review_signal: bool, risky_claim: bool) -> int:
    score = 2

    if has_numeric_evidence(text):
        score += 1

    if contains_any(text, ["n=", "sample", "respondents", "survey"]):
        score += 1

    evidence_markers = 0
    for marker in ["mean", "top-two", "low ratings", "promoters", "detractors", "nps-style", "selected percentage"]:
        if marker in text.lower():
            evidence_markers += 1

    if evidence_markers >= 3 and contains_any(text, ["compared", "across", "followed by", "linked", "open-ended", "triangulat"]):
        score += 1

    if review_signal:
        score -= 2
    if risky_claim:
        score -= 1

    return clamp_score(score)


def is_table_evidence(text: str) -> bool:
    lowered = text.lower()
    return (
        "table " in lowered
        and "%" in lowered
        and (
            " vs total" in lowered
            or "among " in lowered
            or "selected percentage" in lowered
            or "generated banner insights" in lowered
        )
    )


def review_status(score: float, dimension_scores: Dict[str, int]) -> str:
    if score < 2.50 or min(dimension_scores.values()) <= 2:
        return "Human review required"
    if score >= 4.00 and min(dimension_scores.values()) >= 3:
        return "Ready with evidence documentation"
    if score < 3.50 or any(value == 3 for value in dimension_scores.values()):
        return "Researcher check recommended"
    return "Ready with evidence documentation"


def dimension_diagnostics(dimension_scores: Dict[str, int], row: Dict[str, object], weighted_score: float = 0) -> tuple[str, str]:
    combined = f"{row.get('insight_text', '')} {row.get('evidence_note', '')}"
    table_evidence = is_table_evidence(combined)
    theme = str(row.get("theme", "")).lower()
    is_synthesis = theme in {"overall summary", "complete story"}
    attention_threshold = 2 if weighted_score >= 4.00 and table_evidence and not is_synthesis else 3

    dimensions_needing_attention = [
        (key, score)
        for key, score in sorted(dimension_scores.items(), key=lambda item: item[1])
        if score <= attention_threshold
    ]

    if not dimensions_needing_attention:
        if table_evidence:
            return (
                "No major weak dimension identified",
                "Proceed with the table-backed insight; document base size, banner definition, and any significance testing before client use.",
            )
        return ("No major weak dimension identified", "Proceed, while documenting evidence and analyst review notes.")

    if table_evidence or is_synthesis:
        weak_keys = [key for key, _ in dimensions_needing_attention]
        weakest_labels = [
            f"{DIMENSIONS[key]['label']} ({score}/5)"
            for key, score in dimensions_needing_attention[:2]
        ]
        actions = []
        if "triangulation" in weak_keys:
            actions.append("Check whether the banner difference is statistically significant and directionally consistent across related cuts.")
        if "interpretability" in weak_keys:
            actions.append("Simplify the table story into a clearer business sentence before sharing.")
        if "actionability" in weak_keys:
            actions.append("Add the practical implication for the audience segment or banner group.")
        if "evidence_strength" in weak_keys:
            actions.append("Verify the base size and table calculation; the table evidence is present but should be checked for reliability.")
        if "business_relevance" in weak_keys:
            actions.append("Connect the banner pattern to a business decision or targeting implication.")
        if "bias_risk" in weak_keys:
            actions.append("Avoid over-claiming causality from a descriptive table difference.")
        if not actions:
            actions.append("Review the banner cut with analyst judgment before final reporting.")
        if is_synthesis:
            actions = [
                "Review the synthesized story against the detailed table insights and add business context before client presentation."
            ]
        return "; ".join(weakest_labels), " ".join(actions)

    weakest_labels = [
        f"{DIMENSIONS[key]['label']} ({score}/5)"
        for key, score in dimensions_needing_attention[:2]
    ]
    recommended_actions = [
        DIMENSIONS[key]["low_score_action"]
        for key, score in dimensions_needing_attention[:2]
    ]

    return "; ".join(weakest_labels), " ".join(recommended_actions)


def is_missing(value: object) -> bool:
    text = str(value or "").strip()
    return text == "" or text.lower() in {"nan", "none", "null", "not specified"}


def normalize_theme(value: object) -> str:
    theme = str(value or "").strip()
    if is_missing(theme):
        return "Not specified"

    lowered = theme.lower()
    prefix = "human review required:"
    if lowered.startswith(prefix):
        cleaned = theme[len(prefix):].strip()
        return cleaned[:1].upper() + cleaned[1:] if cleaned else "Human review issue"

    return theme


def infer_theme(row: Dict[str, object]) -> str:
    theme = normalize_theme(row.get("theme", ""))
    if theme != "Not specified":
        return theme

    source = str(row.get("insight_id", "") or "").strip()
    if not source:
        return "Not specified"

    bracket_match = re.search(r"\(([^()]*(?:usage|apps?|brand|category|social|dating|voice|streaming|game|awareness|consideration)[^()]*)", source, re.I)
    if bracket_match:
        return bracket_match.group(1).replace("Base=", "").strip(" -:/")[:80] or "Not specified"

    cleaned = re.sub(r"\(.*?base\s*=\s*\d+.*?\)", "", source, flags=re.I)
    cleaned = re.sub(r"^q\d+[a-z]?\.\s*", "", cleaned, flags=re.I)
    cleaned = cleaned.replace("?", "").strip(" -:/")
    if cleaned:
        return cleaned[:80]
    return "Not specified"


def auto_dimension_scores(row: Dict[str, object]) -> Dict[str, int]:
    insight = str(row.get("insight_text", "") or "")
    evidence = "" if is_missing(row.get("evidence_note", "")) else str(row.get("evidence_note", "") or "")
    source_context = str(row.get("insight_id", "") or "")
    evidence_context = evidence or source_context
    combined = f"{insight} {evidence_context}".strip()
    word_count = len(re.findall(r"\w+", insight))

    table_evidence = is_table_evidence(combined)
    high_signal = contains_any(combined, ["relative strength", "strong customer advocacy", "high confidence"])
    review_signal = contains_any(combined, ["needs human attention", "requires validation", "unsupported", "not coded", "does not establish", "weak base", "overstates"])
    risky_claim = contains_any(combined, ["fully satisfied", "all customers", "no improvement", "main reason", "primary cause", "only serious", "exclusive benchmark", "reduce investment"])
    evidence_markers = sum(
        1
        for marker in ["n=", "base=", "mean", "top-two", "low ratings", "promoters", "detractors", "nps-style", "selected percentage", "%"]
        if marker in combined.lower()
    )
    complete_survey_evidence = (
        has_numeric_evidence(combined)
        and contains_any(combined, ["n=", "respondents", "survey"])
        and evidence_markers >= 3
        and not review_signal
        and not risky_claim
    )

    base = 4 if (high_signal or complete_survey_evidence) and not review_signal and not risky_claim else 3
    scores = {key: base for key in DIMENSIONS}

    scores["evidence_strength"] = evidence_strength_score(combined, review_signal, risky_claim)
    if not evidence and re.search(r"\bbase\s*=\s*\d+", source_context, re.I) and not review_signal and not risky_claim:
        scores["evidence_strength"] = max(scores["evidence_strength"], 3)
    if table_evidence and not review_signal and not risky_claim:
        scores["evidence_strength"] = max(scores["evidence_strength"], 4)
        scores["methodological_fit"] = max(scores["methodological_fit"], 4)

    if contains_any(combined, ["customer", "satisfaction", "market", "survey", "respondent", "brand", "product", "service", "business"]):
        scores["methodological_fit"] += 1
    if contains_any(combined, ["caused by", "main reason", "fully satisfied", "only serious", "exclusive benchmark", "no improvement"]):
        scores["methodological_fit"] -= 2

    if contains_any(combined, ["compared", "across", "followed by", "alongside", "linked", "triangulat", "open-ended"]):
        scores["triangulation"] += 1
    if table_evidence and " vs total" in combined.lower():
        scores["triangulation"] += 1
    if complete_survey_evidence:
        scores["triangulation"] += 1
    if contains_any(combined, ["requires validation", "not coded", "does not establish", "weak base", "unsupported"]):
        scores["triangulation"] -= 2
    if contains_any(combined, ["primary cause", "main reason", "only serious", "all customers"]):
        scores["triangulation"] -= 2

    if 12 <= word_count <= 55:
        scores["interpretability"] += 1
    if contains_any(combined, ["unclear", "vague", "maybe", "somehow"]):
        scores["interpretability"] -= 1

    if contains_any(combined, ["customer", "client", "business", "revenue", "cost", "roi", "satisfaction", "preference", "recommend", "retention"]):
        scores["business_relevance"] += 1
    if table_evidence and contains_any(combined, ["over-indexes", "under-indexes", "leading", "selected"]):
        scores["business_relevance"] += 1

    if contains_any(combined, ["should", "priority", "improve", "focus", "recommend", "action", "opportunity", "strengthen", "investigate"]):
        scores["actionability"] += 1
    if table_evidence and contains_any(combined, ["over-indexes", "under-indexes", "leading", "selected"]):
        scores["actionability"] += 1
    if complete_survey_evidence:
        scores["actionability"] += 1
    if contains_any(combined, ["no improvement", "exclusive benchmark", "reduce investment"]):
        scores["actionability"] -= 2

    if contains_any(combined, ["requires validation", "unsupported", "causal", "fully satisfied", "all customers", "only serious", "primary cause", "reduce investment"]):
        scores["bias_risk"] -= 2
    if contains_any(combined, ["moderate", "suggest", "may", "should be interpreted", "requires validation", "hypothesis"]):
        scores["bias_risk"] += 1
    if table_evidence and not risky_claim:
        scores["bias_risk"] += 1
    if complete_survey_evidence:
        scores["bias_risk"] += 1

    if risky_claim:
        scores["triangulation"] -= 1
        scores["bias_risk"] -= 1

    if review_signal:
        scores["triangulation"] -= 1

    if high_signal and not review_signal and not risky_claim:
        scores["business_relevance"] += 1
        scores["interpretability"] += 1

    return {key: clamp_score(value) for key, value in scores.items()}


def score_insight(row: Dict[str, object], use_manual_scores: bool = False) -> AICFResult:
    has_manual_scores = use_manual_scores and all(row.get(key) not in (None, "") for key in MANUAL_SCORE_COLUMNS)
    if has_manual_scores:
        dimension_scores = {
            key: parse_score(row.get(key), key)
            for key in DIMENSIONS
        }
        scoring_mode = "Manual evaluator scores"
    else:
        dimension_scores = auto_dimension_scores(row)
        scoring_mode = "AICF auto-estimated scores"

    weighted_score = sum(
        dimension_scores[key] * DIMENSIONS[key]["weight"]
        for key in DIMENSIONS
    )

    weakest_dimensions, recommendation = dimension_diagnostics(dimension_scores, row, weighted_score)
    evidence_note = "" if is_missing(row.get("evidence_note", "")) else str(row.get("evidence_note", "") or "").strip()
    if not evidence_note:
        source_context = str(row.get("insight_id", "") or "").strip()
        if re.search(r"\b(base|n)\s*=\s*\d+", source_context, re.I):
            evidence_note = f"Source context: {source_context}"

    return AICFResult(
        insight_id=str(row.get("insight_id", "")).strip(),
        theme=infer_theme(row),
        insight_text=str(row.get("insight_text", "")).strip(),
        evidence_note=evidence_note,
        evidence_strength=dimension_scores["evidence_strength"],
        methodological_fit=dimension_scores["methodological_fit"],
        triangulation=dimension_scores["triangulation"],
        interpretability=dimension_scores["interpretability"],
        business_relevance=dimension_scores["business_relevance"],
        actionability=dimension_scores["actionability"],
        bias_risk=dimension_scores["bias_risk"],
        weighted_score=round(weighted_score, 2),
        confidence_level=confidence_level(weighted_score),
        review_status=review_status(weighted_score, dimension_scores),
        weakest_dimensions=weakest_dimensions,
        recommendation=recommendation,
        scoring_mode=scoring_mode,
    )


def validate_columns(columns: List[str]) -> List[str]:
    return [column for column in REQUIRED_COLUMNS if column not in columns]
