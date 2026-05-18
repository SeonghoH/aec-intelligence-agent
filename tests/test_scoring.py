from aec_intel_agent.models import StandardItem
from aec_intel_agent.scoring import score_item


def test_score_item_counts_title_summary_and_topic_matches() -> None:
    keywords_config = {
        "topics": {
            "bim": ["BIM"],
            "embodied_carbon": ["embodied carbon"],
        },
        # Make the LCA gate pass: title already mentions "construction".
        "construction_domain_keywords": ["construction"],
        "lca_negative_keywords": [],
    }
    scoring_rules = {
        "weights": {
            "title_keyword": 3,
            "summary_keyword": 1,
            "topic_match": 2,
        }
    }
    item = StandardItem(
        title="BIM workflows for steel construction",
        source="test",
        summary="Includes embodied carbon tracking.",
    )

    scored = score_item(item, keywords_config, scoring_rules)

    assert scored.score == 8
    assert scored.topics == ["bim", "embodied_carbon"]
    assert scored.metadata["matched_keywords"] == ["BIM", "embodied carbon"]

