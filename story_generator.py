from __future__ import annotations

import re
from typing import Dict, List

import pandas as pd


def short_list(items: List[str], limit: int = 3) -> str:
    clean_items = []
    for item in items:
        item = " ".join(str(item).split())
        if item and item not in clean_items:
            clean_items.append(item)
        if len(clean_items) >= limit:
            break
    if not clean_items:
        return "not enough clear patterns"
    if len(clean_items) == 1:
        return clean_items[0]
    return ", ".join(clean_items[:-1]) + " and " + clean_items[-1]


def readable(value: object, limit: int = 95) -> str:
    text = " ".join(str(value).replace("—", "-").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def management_worthy(item: Dict[str, object], require_gap: bool = False) -> bool:
    attribute = str(item.get("attribute", ""))
    theme = str(item.get("theme", ""))
    banner = str(item.get("banner", ""))
    attribute_lower = attribute.lower().strip()
    theme_lower = theme.lower().strip()
    pct = float(item.get("pct", 0))
    gap = float(item.get("gap", 0))

    if pct <= 0 or pct > 95:
        return False
    if require_gap and (gap < 5 or gap > 60):
        return False
    if len(attribute) > 120 or len(theme) > 100 or len(banner) > 140:
        return False
    if attribute_lower in {
        "other",
        "none",
        "none of the above",
        "don't know",
        "dont know",
        "minimum",
        "maximum",
        "mean",
        "median",
        "std. deviation",
        "standard deviation",
        "sigma",
    }:
        return False
    if attribute_lower.startswith(("none -", "none –", "none —")):
        return False
    if re.match(r"^\d+(\.\d+)?$", attribute_lower):
        return False
    if any(word in attribute_lower for word in ["top 2 box", "top 3 box", "bottom 2 box", "bottom 3 box"]):
        return False
    if theme_lower == "banner x banner":
        return False
    if re.match(r"^s\d+\b", theme_lower):
        return False
    if any(word in theme_lower for word in ["age", "gender", "employment", "specialty", "screen", "screener", "region", "city", "country", "subdivision"]):
        return False
    return True


def parse_banner_patterns(insights: List[Dict[str, object]]) -> Dict[str, List[Dict[str, object]]]:
    leading = []
    over_index = []
    under_index = []

    leading_re = re.compile(
        r"For (?P<theme>.*?), (?P<attribute>.*?) is the leading overall response at (?P<pct>\d+(?:\.\d+)?)%",
        re.I,
    )
    over_re = re.compile(
        r"For (?P<theme>.*?), (?P<banner>.*?) over-indexes on (?P<attribute>.*?) at (?P<pct>\d+(?:\.\d+)?)%, compared with (?P<total>\d+(?:\.\d+)?)% overall",
        re.I,
    )
    under_re = re.compile(
        r"For (?P<theme>.*?), (?P<banner>.*?) under-indexes on (?P<attribute>.*?) at (?P<pct>\d+(?:\.\d+)?)%, compared with (?P<total>\d+(?:\.\d+)?)% overall",
        re.I,
    )

    for item in insights:
        text = str(item.get("insight_text", ""))
        for match in leading_re.finditer(text):
            data = match.groupdict()
            data["pct"] = float(data["pct"])
            leading.append(data)
        for match in over_re.finditer(text):
            data = match.groupdict()
            data["pct"] = float(data["pct"])
            data["total"] = float(data["total"])
            data["gap"] = data["pct"] - data["total"]
            over_index.append(data)
        for match in under_re.finditer(text):
            data = match.groupdict()
            data["pct"] = float(data["pct"])
            data["total"] = float(data["total"])
            data["gap"] = data["total"] - data["pct"]
            under_index.append(data)

    leading = [item for item in leading if management_worthy(item)]
    over_index = [item for item in over_index if management_worthy(item, require_gap=True)]
    under_index = [item for item in under_index if management_worthy(item, require_gap=True)]

    leading.sort(key=lambda item: item["pct"], reverse=True)
    over_index.sort(key=lambda item: item["gap"], reverse=True)
    under_index.sort(key=lambda item: item["gap"], reverse=True)

    return {
        "leading": leading,
        "over_index": over_index,
        "under_index": under_index,
    }


def parse_general_patterns(insights: List[Dict[str, object]]) -> Dict[str, List[str]]:
    strengths = []
    review_areas = []
    visible_themes = []

    for item in insights:
        theme = str(item.get("theme", "")).strip()
        text = str(item.get("insight_text", "")).strip()
        lowered = text.lower()
        if not theme or theme in {"Overall Summary", "Complete Story"}:
            continue
        if "relative strength" in lowered or "strongest" in lowered or "leading" in lowered:
            strengths.append(theme)
        if "needs human attention" in lowered or "under-indexes" in lowered or "weakest" in lowered:
            review_areas.append(theme)
        if "selected by" in lowered or "visible" in lowered or "moderate" in lowered:
            visible_themes.append(theme)

    return {
        "strengths": strengths,
        "review_areas": review_areas,
        "visible_themes": visible_themes,
    }


def build_banner_summary(patterns: Dict[str, List[Dict[str, object]]], insight_count: int) -> str:
    leading = patterns["leading"]
    over_index = patterns["over_index"]
    under_index = patterns["under_index"]

    leading_bits = [
        f"{readable(item['attribute'])} leads {readable(item['theme'], 55)} at {item['pct']:.1f}%"
        for item in leading[:3]
    ]
    over_bits = [
        f"{readable(item['banner'], 65)} over-indexes on {readable(item['attribute'], 65)} in {readable(item['theme'], 55)} by {item['gap']:.1f} points"
        for item in over_index[:3]
    ]
    under_bits = [
        f"{readable(item['banner'], 65)} under-indexes on {readable(item['attribute'], 65)} in {readable(item['theme'], 55)} by {item['gap']:.1f} points"
        for item in under_index[:3]
    ]

    return (
        f"The banner analysis produced {insight_count} detailed insights. The main read is that "
        f"{short_list(leading_bits)}. The strongest audience skews are {short_list(over_bits)}. "
        f"The clearest gaps are {short_list(under_bits)}, which should be checked before turning the findings into recommendations."
    )


def build_banner_story(patterns: Dict[str, List[Dict[str, object]]]) -> str:
    leading = patterns["leading"]
    over_index = patterns["over_index"]
    under_index = patterns["under_index"]

    first_lead = leading[0] if leading else None
    first_over = over_index[0] if over_index else None
    first_under = under_index[0] if under_index else None

    story_parts = []
    if first_lead:
        story_parts.append(
            f"At the total level, the study is anchored by {readable(first_lead['attribute'])} within {readable(first_lead['theme'])}, "
            f"which stands at {first_lead['pct']:.1f}%."
        )
    if first_over:
        story_parts.append(
            f"The banner cuts show that the market is not uniform: {readable(first_over['banner'])} is especially strong on "
            f"{readable(first_over['attribute'])} within {readable(first_over['theme'])}, over-indexing by {first_over['gap']:.1f} points."
        )
    if first_under:
        story_parts.append(
            f"At the same time, {readable(first_under['banner'])} is weaker on {readable(first_under['attribute'])} within {readable(first_under['theme'])}, "
            f"under-indexing by {first_under['gap']:.1f} points."
        )
    story_parts.append(
        "The practical story is therefore about prioritization: use the over-indexing groups as opportunity pockets, "
        "treat the under-indexing groups as watch-outs, and validate the biggest gaps with business context before client presentation."
    )

    return " ".join(story_parts)


def build_general_summary(patterns: Dict[str, List[str]], insight_count: int, source_label: str) -> str:
    return (
        f"Across {source_label}, AICF generated {insight_count} detailed insights. "
        f"The strongest themes are {short_list(patterns['strengths'])}; the main areas needing review are "
        f"{short_list(patterns['review_areas'])}; and the visible recurring themes are {short_list(patterns['visible_themes'])}."
    )


def build_general_story(patterns: Dict[str, List[str]], source_label: str) -> str:
    return (
        f"The overall story from {source_label} is that the data contains a mix of usable strengths and areas needing validation. "
        f"Management should treat {short_list(patterns['strengths'])} as the positive narrative, while using "
        f"{short_list(patterns['review_areas'])} as the improvement or human-review agenda. "
        "This gives a clearer path from AI-generated outputs to decision-ready market research findings."
    )


def add_summary_and_story(insights_df: pd.DataFrame, source_label: str) -> pd.DataFrame:
    if insights_df.empty:
        return insights_df

    insights = insights_df.to_dict("records")
    banner_patterns = parse_banner_patterns(insights)
    general_patterns = parse_general_patterns(insights)
    is_banner_output = bool(
        banner_patterns["leading"] or banner_patterns["over_index"] or banner_patterns["under_index"]
    )

    if is_banner_output:
        summary_text = build_banner_summary(banner_patterns, len(insights))
        story_text = build_banner_story(banner_patterns)
        evidence_note = (
            f"Summary synthesized from {len(insights)} generated banner insights; "
            f"leading patterns={len(banner_patterns['leading'])}, "
            f"over-index patterns={len(banner_patterns['over_index'])}, "
            f"under-index patterns={len(banner_patterns['under_index'])}."
        )
    else:
        summary_text = build_general_summary(general_patterns, len(insights), source_label)
        story_text = build_general_story(general_patterns, source_label)
        evidence_note = f"Summary synthesized from {len(insights)} generated insights from {source_label}."

    summary = {
        "insight_id": f"SUM-{len(insights) + 1:03d}",
        "theme": "Overall Summary",
        "insight_text": summary_text,
        "evidence_note": evidence_note,
    }

    story = {
        "insight_id": f"SUM-{len(insights) + 2:03d}",
        "theme": "Complete Story",
        "insight_text": story_text,
        "evidence_note": f"Story synthesized from all generated insights and evidence notes for {source_label}.",
    }

    return pd.concat([insights_df, pd.DataFrame([summary, story])], ignore_index=True)
