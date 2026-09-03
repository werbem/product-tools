"""Step 41: Evidence date — prefer most recent; timeline semantics + confidence."""

from __future__ import annotations

from app.application.dto.agent_dto import EvidenceItemDTO
from app.infrastructure.agents.compare_prompt import (
    COMPACT_SYSTEM_PROMPT,
    build_compare_prompt_compact,
)
from app.infrastructure.agents.strategy_prompt import (
    COMPACT_STRATEGY_SYSTEM,
    build_strategy_prompt_compact,
)
from app.infrastructure.tools.evidence_date import (
    enrich_evidence_item,
    extract_date_from_text,
    format_evidence_date_label,
    is_timeline_context,
)


class TestPreferMostRecentDate:
    def test_multi_date_picks_recent_not_last_occurrence(self):
        text = (
            "公司于2024年3月1日完成融资。"
            "另据记载，2011年12月24日深圳北站贵宾厅落成。"
        )
        assert extract_date_from_text(text) == "2024-03-01"

    def test_timeline_new_to_old_picks_recent_event(self):
        text = (
            "2024年7月2日至5日 出席全球数字经济大会\n"
            "2024年6月20日 当选副会长单位\n"
            "2011年12月24日 深圳北站商务贵宾厅当天落成。"
        )
        assert extract_date_from_text(text) == "2024-07-02"

    def test_single_old_date(self):
        assert extract_date_from_text("2011年12月24日 落成") == "2011-12-24"


class TestTimelineSemantics:
    def test_abouts_url_detected(self):
        assert is_timeline_context(url="https://www.yuetuvip.com/abouts")
        assert is_timeline_context(title="公司大事记")
        assert not is_timeline_context(url="https://news.example.com/2024-01-01/a")

    def test_timeline_enrich_sets_event_semantic_and_recent(self):
        item = EvidenceItemDTO(
            title="悦途出行",
            source="web",
            url="https://www.yuetuvip.com/abouts",
            date="2011-12-24",  # wrong prior pick
            content=(
                "2024年7月2日至5日 悦途集团出席大会\n"
                "2024年5月31日 加入某协会\n"
                "2011年12月24日 呼应大动脉贯通，深圳北站贵宾厅当天落成。"
            ),
            raw_data={"date_source": "unchanged"},
        )
        src = enrich_evidence_item(item)
        assert item.date == "2024-07-02"
        assert src == "timeline_event_recent"
        assert (item.raw_data or {}).get("date_semantic") == "event_date"
        assert (item.raw_data or {}).get("temporal_confidence") == "low"
        assert "事件日期" in format_evidence_date_label(item)

    def test_only_2011_on_timeline(self):
        item = EvidenceItemDTO(
            title="大事记",
            source="web",
            url="https://www.yuetuvip.com/abouts",
            date="",
            content="2011年12月24日 深圳北站商务贵宾厅当天落成。",
        )
        enrich_evidence_item(item)
        assert item.date == "2011-12-24"
        assert (item.raw_data or {}).get("date_source") == "timeline_event_recent"
        assert (item.raw_data or {}).get("date_semantic") == "event_date"
        assert (item.raw_data or {}).get("temporal_confidence") == "low"


class TestPublishPriority:
    def test_published_date_beats_snippet(self):
        item = EvidenceItemDTO(
            title="app",
            source="appstore",
            url="https://apps.apple.com/app/id1",
            date="",
            content="提到 2020年1月1日 的旧闻",
            raw_data={"currentVersionReleaseDate": "2025-11-01T00:00:00Z"},
        )
        src = enrich_evidence_item(item)
        assert item.date == "2025-11-01"
        assert src == "published_date"
        assert (item.raw_data or {}).get("date_semantic") == "publish_date"
        assert (item.raw_data or {}).get("temporal_confidence") == "high"

    def test_publish_date_not_overwritten_by_timeline(self):
        item = EvidenceItemDTO(
            title="大事记",
            source="web",
            url="https://www.yuetuvip.com/abouts",
            date="2025-01-15",
            content="2011年12月24日 旧事件；2024年3月1日 新事件",
            raw_data={"date_source": "published_date", "date_semantic": "publish_date"},
        )
        enrich_evidence_item(item)
        assert item.date == "2025-01-15"
        assert (item.raw_data or {}).get("date_source") == "published_date"


class TestUnknownDisplay:
    def test_no_date_stays_unknown_with_label(self):
        item = EvidenceItemDTO(
            title="plain",
            source="web",
            url="https://example.com/docs/intro",
            date="",
            content="generic blurb without a publication marker",
        )
        src = enrich_evidence_item(item)
        assert item.date == ""
        assert src == "none"
        assert (item.raw_data or {}).get("temporal_confidence") == "low"
        assert format_evidence_date_label(item) == "日期未知（来源未提供发布时间）"


class TestPromptConstraints:
    def test_compare_compact_mentions_temporal_wording(self):
        assert "近期" in COMPACT_SYSTEM_PROMPT or "event_date" in COMPACT_SYSTEM_PROMPT
        prompt = build_compare_prompt_compact("A", "B", "P", "[]", ["growth"])
        assert "近期" in prompt or "event_date" in prompt

    def test_strategy_compact_mentions_temporal_wording(self):
        assert "event_date" in COMPACT_STRATEGY_SYSTEM
        prompt = build_strategy_prompt_compact("obj", "P", "gap", "[]")
        assert "event_date" in prompt or "近期" in prompt
