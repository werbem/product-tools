"""Report Agent — LLM-powered structured report generation.

Uses real LLM to organize evidence, gap analysis, and strategy insights
into a well-formatted competitive analysis report.

Formats: Markdown (LLM), HTML + Word (export tools)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
import traceback
import time
from datetime import datetime
from typing import Any

from app.application.dto.agent_dto import (
    EvidenceBundleDTO,
    GapAnalysis,
    ReportDocument,
    ReportFormatsDTO,
    ReportInput,
    ReportOutput,
    ReportSectionDTO,
    StrategicInsights,
)
from app.config.constants import Phase
from app.config.settings import settings
from app.infrastructure.agents.base import AgentContext, AgentResult, BaseAgent
from app.infrastructure.agents.report_prompt import (
    SYSTEM_PROMPT,
    SEGMENT_WORD_TARGETS,
    build_report_prompt,
    build_report_prompt_segment,
)
from app.infrastructure.workflow.progress_hints import (
    FAST_REPORT_SEGMENT_HINTS,
)
from app.infrastructure.llm.client import llm_client
from app.infrastructure.tools.export_tool import (
    HTMLBuilder,
    MarkdownBuilder,
    WordBuilder,
)

# ── Report section definitions (for SectionDTO extraction) ──
SECTION_DEFS = [
    ("一、Executive Summary", "executive_summary"),
    ("二、产品概览与定位", "positioning"),
    ("三、目标用户与画像", "users"),
    ("四、核心功能对比", "features"),
    ("五、用户体验与设计", "ux"),
    ("六、商业模式与收费", "business"),
    ("七、技术架构与能力", "technology"),
    ("八、增长策略与市场", "growth"),
    ("九、竞争格局", "competitive_landscape"),
    ("十、SWOT 分析", "swot_section"),
    ("十一、关键指标对比", "metrics"),
    ("十二、战略建议", "strategy"),
    ("十三、实施路线图", "roadmap"),
]

FAST_REPORT_SEGMENTS: dict[int, list[tuple[str, str]]] = {
    1: SECTION_DEFS[0:4],
    2: SECTION_DEFS[4:9],
    3: SECTION_DEFS[9:13],
}

FAST_SEGMENT_PROGRESS: dict[int, float] = {
    1: 70.0,
    2: 75.0,
    3: 80.0,
}

MERGE_BUFFER_S = 5.0
DEFAULT_SEGMENT_LLM_TIMEOUT_S = 55.0
FAST_GENERATION_NOTE = (
    "快速模式：未执行对比/洞察/战略分析，对比章节基于证据整理。"
)


class ReportAgent(BaseAgent[ReportInput, ReportOutput]):

    @staticmethod
    def normalize_table_breaks(md: str) -> str:
        """Replace HTML <br> variants with Chinese semicolon (safe for MD tables).

        Markdown table rows break if a cell contains a raw newline; semicolon
        keeps the pipe-row intact while remaining readable in SWOT cells.
        """
        if not md:
            return md or ""
        return re.sub(r"<br\s*/?\s*>", "；", md, flags=re.IGNORECASE)

    @classmethod
    def _prepare_markdown(cls, md: str) -> str:
        return cls.normalize_table_breaks(md or "")

    @property
    def agent_name(self) -> str:
        return "report"

    @property
    def phase(self) -> Phase:
        return Phase.REPORTING

    def build_timeout_fallback(self, input_data: ReportInput) -> AgentResult:
        """Non-LLM fallback when the report node hits its hard timeout budget."""
        if getattr(input_data, "fast_mode", False):
            segments = [
                self._build_segment_timeout_fallback(n, FAST_REPORT_SEGMENTS[n])
                for n in (1, 2, 3)
            ]
            fallback_md = self._merge_segments(input_data, segments)
            metadata_extra = {
                "generation_mode": "fast_segmented",
                "segment_timeouts": [1, 2, 3],
                "report_timeout_fallback": True,
            }
        else:
            evidence_json = self._serialize_evidence(input_data.evidence_bundle)
            gap_json = self._serialize_gap(input_data.gap_analysis)
            strategy_json = self._serialize_strategy(input_data.strategic_insights)
            fallback_md = self._build_fallback_report(input_data, evidence_json, gap_json, strategy_json)
            metadata_extra = {"report_timeout_fallback": True}

        fallback_md = self._prepare_markdown(fallback_md)
        if not getattr(input_data, "fast_mode", False):
            metadata_extra["generation_mode"] = "full_single"

        try:
            html_content = self._markdown_to_html(fallback_md, input_data)
        except Exception:
            html_content = f"<html><body><h1>竞品分析报告</h1><pre>{fallback_md[:5000]}</pre></body></html>"
        sections: list[ReportSectionDTO] = []
        try:
            sections = self._extract_sections(fallback_md)
        except Exception:
            pass
        total_words = len(fallback_md.replace("\n", ""))
        doc = ReportDocument(
            formats=ReportFormatsDTO(markdown=fallback_md, html=html_content, docx_url=None),
            sections=sections,
            metadata={
                "total_word_count": total_words,
                "generated_at": datetime.utcnow().isoformat(),
                "sources_count": 0,
                "template_used": "v1",
                "llm_prompt_tokens": 0,
                "llm_completion_tokens": 0,
                "fast_mode": bool(getattr(input_data, "fast_mode", False)),
                "generation_note": FAST_GENERATION_NOTE if getattr(input_data, "fast_mode", False) else None,
                **metadata_extra,
            },
        )
        return AgentResult(
            success=True,
            output=ReportOutput(report_document=doc),
            phase_record={
                "phase": Phase.REPORTING.value,
                "status": "completed",
                "error": "report_timeout_fallback",
                "llm_generated": False,
            },
        )

    async def arun(self, ctx: AgentContext, input_data: ReportInput) -> AgentResult:
        if getattr(input_data, "fast_mode", False):
            return await self._arun_segmented(ctx, input_data)
        return await self._arun_single(ctx, input_data)

    async def _arun_single(self, ctx: AgentContext, input_data: ReportInput) -> AgentResult:
        try:
            eb = input_data.evidence_bundle
            gap = input_data.gap_analysis
            insights = input_data.strategic_insights

            # ── Serialize input data for LLM ──
            evidence_json = self._serialize_evidence(eb)
            gap_json = self._serialize_gap(gap)
            strategy_json = self._serialize_strategy(insights)
            strategy_is_stub = self._is_strategy_stub(insights)
            gap_is_stub = self._is_gap_stub(gap)

            # ── Call LLM ──
            gen_kwargs: dict = {
                "system_prompt": SYSTEM_PROMPT,
                "user_prompt": build_report_prompt(
                    our_company=input_data.our_company if hasattr(input_data, 'our_company') else "我方",
                    competitor_company=input_data.competitor_company if hasattr(input_data, 'competitor_company') else "竞品",
                    product=input_data.product if hasattr(input_data, 'product') else "产品",
                    objective=input_data.objective if hasattr(input_data, 'objective') else "competitive_defense",
                    evidence_json=evidence_json,
                    gap_json=gap_json,
                    strategy_json=strategy_json,
                    fast_mode=bool(getattr(input_data, "fast_mode", False)),
                    compact_report=bool(getattr(input_data, "compact_report", False)),
                    strategy_is_stub=strategy_is_stub,
                    gap_is_stub=gap_is_stub,
                    memory_notes_context=getattr(input_data, "memory_notes_context", None),
                ),
                "response_model": None,
                "temperature": 0.5,
            }
            if input_data.llm_timeout_seconds is not None:
                gen_kwargs["timeout"] = input_data.llm_timeout_seconds
            result = await llm_client.generate(**gen_kwargs)
        except Exception as e:
            traceback.print_exc()
            # Generate fallback report from available data
            fallback_md = self._build_fallback_report(input_data, evidence_json, gap_json, strategy_json)
            fallback_md = self._prepare_markdown(fallback_md)
            try:
                html_content = self._markdown_to_html(fallback_md, input_data)
            except Exception:
                html_content = f"<html><body><h1>竞品分析报告</h1><pre>{fallback_md[:5000]}</pre></body></html>"
            sections = []
            try:
                sections = self._extract_sections(fallback_md)
            except Exception:
                pass
            total_words = len(fallback_md.replace("\n", ""))
            doc = ReportDocument(
                formats=ReportFormatsDTO(markdown=fallback_md, html=html_content, docx_url=None),
                sections=sections,
                metadata={"total_word_count": total_words, "generated_at": datetime.utcnow().isoformat(), "sources_count": 0, "template_used": "v1", "llm_prompt_tokens": 0, "llm_completion_tokens": 0},
            )
            output = ReportOutput(report_document=doc)
            return AgentResult(
                success=True,
                output=output,
                error={"code": "REPORT_ERROR", "message": f"Report Agent 执行失败，使用回退报告: {type(e).__name__}: {str(e)[:200]}"},
            )

        markdown_content = (result.content or "").strip()
        if not markdown_content or markdown_content.startswith("["):
            # LLM returned empty/invalid — use fallback
            fallback_md = self._build_fallback_report(input_data, evidence_json, gap_json, strategy_json)
            fallback_md = self._prepare_markdown(fallback_md)
            try:
                html_content = self._markdown_to_html(fallback_md, input_data)
            except Exception:
                html_content = f"<html><body><h1>竞品分析报告</h1><pre>{fallback_md[:5000]}</pre></body></html>"
            sections = []
            try:
                sections = self._extract_sections(fallback_md)
            except Exception:
                pass
            total_words = len(fallback_md.replace("\n", ""))
            doc = ReportDocument(
                formats=ReportFormatsDTO(markdown=fallback_md, html=html_content, docx_url=None),
                sections=sections,
                metadata={"total_word_count": total_words, "generated_at": datetime.utcnow().isoformat(), "sources_count": 0, "template_used": "v1", "llm_prompt_tokens": 0, "llm_completion_tokens": 0},
            )
            output = ReportOutput(report_document=doc)
            return AgentResult(
                success=True,
                output=output,
                error={"code": "REPORT_ERROR", "message": f"LLM 返回空或异常，使用回退报告: {markdown_content[:200]}"},
            )

        # ── Strip code fences if present ──
        if markdown_content.startswith("```"):
            markdown_content = markdown_content.split("\n", 1)[-1]
        if markdown_content.endswith("```"):
            markdown_content = markdown_content.rsplit("```", 1)[0]
        markdown_content = markdown_content.strip()
        markdown_content = self._prepare_markdown(markdown_content)

        # ── Generate HTML (try/except — don't lose markdown on failure) ──
        try:
            html_content = self._markdown_to_html(markdown_content, input_data)
        except Exception as html_err:
            traceback.print_exc()
            html_content = (
                f"<html><body><h1>竞品分析报告</h1>"
                f"<p>HTML 生成失败: {html_err}. 请查看 Markdown 版本。</p>"
                f"<pre>{markdown_content[:5000]}</pre>"
                f"</body></html>"
            )

        # ── Generate Word (.docx) ──
        word_path = ""
        try:
            if "docx" in input_data.output_formats:
                word_path = self._save_word(markdown_content, input_data)
        except Exception as word_err:
            traceback.print_exc()
            word_path = ""

        # ── Extract sections ──
        try:
            sections = self._extract_sections(markdown_content)
        except Exception:
            traceback.print_exc()
            sections = []

        # ── Build output ──
        total_words = len(markdown_content.replace("\n", ""))
        now = datetime.utcnow().isoformat()

        doc = ReportDocument(
            formats=ReportFormatsDTO(
                markdown=markdown_content,
                html=html_content,
                docx_url=word_path if word_path and os.path.exists(word_path) else None,
            ),
            sections=sections,
            metadata={
                "total_word_count": total_words,
                "generated_at": now,
                "sources_count": len(eb.get("sources_used", []) if isinstance(eb, dict) else getattr(eb, "sources_used", [])),
                "template_used": input_data.template_version or "v1",
                "llm_prompt_tokens": result.prompt_tokens,
                "llm_completion_tokens": result.completion_tokens,
                "fast_mode": bool(getattr(input_data, "fast_mode", False)),
                "generation_mode": "full_single",
                "generation_note": (
                    "快速模式：未执行对比/洞察/战略分析，对比章节基于证据整理。"
                    if getattr(input_data, "fast_mode", False)
                    else None
                ),
            },
        )
        output = ReportOutput(report_document=doc)

        return AgentResult(
            success=True,
            output=output,
            phase_record={
                "phase": self.agent_name,
                "entered_at": getattr(ctx, "phase_entered_at", None) or now,
                "duration_ms": 0,  # overridden by aexecute wrapper
            },
        )

    async def _arun_segmented(self, ctx: AgentContext, input_data: ReportInput) -> AgentResult:
        """Fast mode: generate 13 chapters in 3 sequential LLM segments."""
        total_budget = float(input_data.llm_timeout_seconds or 180.0)
        segment_cap = float(
            getattr(input_data, "segment_timeout_seconds", None)
            or DEFAULT_SEGMENT_LLM_TIMEOUT_S
        )
        start = time.monotonic()
        segment_timeouts: list[int] = []
        segment_markdowns: list[str] = []
        previous_summary: str | None = None
        total_prompt_tokens = 0
        total_completion_tokens = 0

        evidence_json = self._serialize_evidence(input_data.evidence_bundle)
        gap_json = self._serialize_gap(input_data.gap_analysis)
        strategy_json = self._serialize_strategy(input_data.strategic_insights)

        for seg_num in (1, 2, 3):
            self._touch_segment_progress(ctx.task_id, seg_num)
            elapsed = time.monotonic() - start
            remaining = total_budget - elapsed - MERGE_BUFFER_S
            if remaining <= 8.0:
                segment_markdowns.append(
                    self._build_segment_timeout_fallback(seg_num, FAST_REPORT_SEGMENTS[seg_num])
                )
                segment_timeouts.append(seg_num)
                continue

            segment_budget = min(segment_cap, max(8.0, remaining - 8.0))
            try:
                md, pt, ct = await asyncio.wait_for(
                    self._generate_segment(
                        input_data,
                        seg_num,
                        evidence_json,
                        gap_json,
                        strategy_json,
                        previous_summary,
                        segment_budget,
                    ),
                    timeout=segment_budget,
                )
                total_prompt_tokens += pt
                total_completion_tokens += ct
            except asyncio.CancelledError:
                raise
            except Exception:
                md = self._build_segment_timeout_fallback(seg_num, FAST_REPORT_SEGMENTS[seg_num])
                segment_timeouts.append(seg_num)

            segment_markdowns.append(md)
            previous_summary = self._summarize_segment(md)

        markdown_content = self._merge_segments(input_data, segment_markdowns)
        return self._finalize_report_document(
            ctx,
            input_data,
            markdown_content,
            total_prompt_tokens,
            total_completion_tokens,
            extra_metadata={
                "generation_mode": "fast_segmented",
                "segment_timeouts": segment_timeouts,
                "fast_mode": True,
                "generation_note": FAST_GENERATION_NOTE,
            },
            phase_extra={"segmented": True, "segment_timeouts": segment_timeouts},
        )

    async def _generate_segment(
        self,
        input_data: ReportInput,
        segment: int,
        evidence_json: str,
        gap_json: str,
        strategy_json: str,
        previous_summary: str | None,
        llm_timeout: float,
    ) -> tuple[str, int, int]:
        user_prompt = build_report_prompt_segment(
            segment=segment,  # type: ignore[arg-type]
            our_company=input_data.our_company or "我方",
            competitor_company=input_data.competitor_company or "竞品",
            product=input_data.product or "产品",
            objective=input_data.objective or "competitive_defense",
            evidence_json=evidence_json,
            gap_json=gap_json,
            strategy_json=strategy_json,
            fast_mode=True,
            previous_segments_summary=previous_summary,
            word_target=SEGMENT_WORD_TARGETS.get(segment, 800),  # type: ignore[arg-type]
            memory_notes_context=getattr(input_data, "memory_notes_context", None),
        )
        llm_timeout = min(llm_timeout, DEFAULT_SEGMENT_LLM_TIMEOUT_S)
        result = await llm_client.generate(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=None,
            temperature=0.5,
            timeout=llm_timeout,
        )
        content = self._strip_markdown_fences((result.content or "").strip())
        if not content or content.startswith("["):
            raise ValueError(f"segment_{segment}_empty_response")
        return content, result.prompt_tokens, result.completion_tokens

    @staticmethod
    def _strip_markdown_fences(text: str) -> str:
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        return text.strip()

    @staticmethod
    def _build_segment_timeout_fallback(
        segment: int,
        section_defs: list[tuple[str, str]],
    ) -> str:
        lines: list[str] = []
        for title, _ in section_defs:
            lines.append(f"## {title}")
            lines.append("")
            lines.append("> 本章生成超时，请稍后重试或切换完整模式。")
            lines.append("")
        return "\n".join(lines).strip()

    @staticmethod
    def _summarize_segment(markdown: str, max_chars: int = 400) -> str:
        text = re.sub(r"\s+", " ", markdown).strip()
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3] + "..."

    @classmethod
    def _merge_segments(cls, input_data: ReportInput, segments: list[str]) -> str:
        now = datetime.utcnow().strftime("%Y-%m-%d")
        header = (
            f"# 互联网产品竞品分析报告\n\n"
            f"> **我方**：{input_data.our_company or '我方'} | "
            f"**竞品**：{input_data.competitor_company or '竞品'} | "
            f"**产品**：{input_data.product or '产品'} | **日期**：{now}\n"
        )
        body_parts = [s.strip() for s in segments if s and s.strip()]
        body = "\n\n---\n\n".join(body_parts)
        footer = (
            "\n\n---\n\n## 附录\n\n"
            "**生成说明**：*本报告由 AI 竞品分析助手自动生成。"
            f"{FAST_GENERATION_NOTE} 本报告采用分段生成（fast_segmented）。*"
        )
        return f"{header}\n---\n\n{body}{footer}"

    @staticmethod
    def _touch_segment_progress(task_id: str, segment: int) -> None:
        if not task_id:
            return
        try:
            from app.infrastructure.persistence import task_report_runtime

            progress = FAST_SEGMENT_PROGRESS.get(segment, 70.0)
            task_report_runtime.touch_task_progress(
                task_id,
                current_phase="reporting",
                progress=progress,
                current_agent="report",
                stage_hint=FAST_REPORT_SEGMENT_HINTS.get(segment, "正在撰写报告…"),
            )
        except Exception:
            pass

    def _finalize_report_document(
        self,
        ctx: AgentContext,
        input_data: ReportInput,
        markdown_content: str,
        prompt_tokens: int,
        completion_tokens: int,
        *,
        extra_metadata: dict[str, Any] | None = None,
        phase_extra: dict[str, Any] | None = None,
    ) -> AgentResult:
        markdown_content = self._prepare_markdown(markdown_content)
        eb = input_data.evidence_bundle
        try:
            html_content = self._markdown_to_html(markdown_content, input_data)
        except Exception as html_err:
            traceback.print_exc()
            html_content = (
                f"<html><body><h1>竞品分析报告</h1>"
                f"<p>HTML 生成失败: {html_err}. 请查看 Markdown 版本。</p>"
                f"<pre>{markdown_content[:5000]}</pre>"
                f"</body></html>"
            )

        word_path = ""
        try:
            if "docx" in input_data.output_formats:
                word_path = self._save_word(markdown_content, input_data)
        except Exception:
            traceback.print_exc()
            word_path = ""

        try:
            sections = self._extract_sections(markdown_content)
        except Exception:
            sections = []

        total_words = len(markdown_content.replace("\n", ""))
        now = datetime.utcnow().isoformat()
        metadata: dict[str, Any] = {
            "total_word_count": total_words,
            "generated_at": now,
            "sources_count": len(
                eb.get("sources_used", []) if isinstance(eb, dict) else getattr(eb, "sources_used", [])
            ),
            "template_used": input_data.template_version or "v1",
            "llm_prompt_tokens": prompt_tokens,
            "llm_completion_tokens": completion_tokens,
        }
        if extra_metadata:
            metadata.update(extra_metadata)

        doc = ReportDocument(
            formats=ReportFormatsDTO(
                markdown=markdown_content,
                html=html_content,
                docx_url=word_path if word_path and os.path.exists(word_path) else None,
            ),
            sections=sections,
            metadata=metadata,
        )
        phase_record = {
            "phase": self.agent_name,
            "entered_at": getattr(ctx, "phase_entered_at", None) or now,
            "duration_ms": 0,
        }
        if phase_extra:
            phase_record.update(phase_extra)

        return AgentResult(
            success=True,
            output=ReportOutput(report_document=doc),
            phase_record=phase_record,
        )

    # ── Serialization helpers ──

    @classmethod
    def _serialize_evidence(cls, eb) -> str:
        """Serialize evidence to JSON for LLM prompt."""
        items = []
        evidence_items = (
            eb.get("evidence_items", []) if isinstance(eb, dict)
            else getattr(eb, "evidence_items", [])
        )
        sources_used = (
            eb.get("sources_used", []) if isinstance(eb, dict)
            else getattr(eb, "sources_used", [])
        )
        for item in evidence_items[:30]:  # top 30 evidence items
            if isinstance(item, dict):
                items.append({
                    "id": item.get("id", ""),
                    "title": item.get("title", ""),
                    "source": item.get("source", ""),
                    "url": item.get("url", ""),
                    "content": (item.get("content", "") or "")[:300],
                    "category": item.get("category", ""),
                    "confidence": item.get("confidence", ""),
                    "date": item.get("date", ""),
                    "temporal_level": cls._resolve_temporal_level(item),
                })
            else:
                items.append({
                    "id": getattr(item, "id", ""),
                    "title": getattr(item, "title", ""),
                    "source": getattr(item, "source", ""),
                    "url": getattr(item, "url", ""),
                    "content": (getattr(item, "content", "") or "")[:300],
                    "category": getattr(item, "category", ""),
                    "confidence": getattr(item, "confidence", ""),
                    "date": getattr(item, "date", ""),
                    "temporal_level": cls._resolve_temporal_level(item),
                })
        return json.dumps(items, ensure_ascii=False, indent=2)

    @classmethod
    def _resolve_temporal_level(cls, item) -> str:
        """Read temporal_level from quality_score; fall back to date derivation.

        temporal_level is computed by the Research Agent (P0) and cached in
        quality_score. For legacy/missing data, derive it from the date year.
        """
        qs = cls._safe_get(item, "quality_score", None) or {}
        if isinstance(qs, dict) and qs.get("temporal_level"):
            return qs["temporal_level"]
        date_str = cls._safe_get(item, "date", "") or ""
        return cls._compute_temporal_level(date_str)

    @staticmethod
    def _compute_temporal_level(date_str: str) -> str:
        """Year-based temporal level (fallback when quality_score lacks it)."""
        if not date_str:
            return "unknown"
        m = re.search(r"(20\d{2})", str(date_str))
        if not m:
            return "unknown"
        try:
            year = int(m.group(1))
        except (ValueError, TypeError):
            return "unknown"
        age = datetime.now().year - year
        if age < 1:
            return "recent"
        if age < 3:
            return "aging"
        if age < 5:
            return "stale"
        return "historical"

    @staticmethod
    def _safe_get(obj, key, default=None):
        """Safely get key from dict or object. Returns default if obj is not dict-like."""
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        if hasattr(obj, key):
            return getattr(obj, key, default)
        return default

    @classmethod
    def _serialize_gap(cls, gap) -> str:
        """Serialize gap analysis to JSON for LLM prompt."""
        pos = gap.get("positioning") if isinstance(gap, dict) else gap.positioning or {}
        if not isinstance(pos, dict):
            pos = {}

        features_data = gap.get("features") if isinstance(gap, dict) else gap.features
        if isinstance(features_data, dict):
            fm = features_data.get("feature_matrix", [])
        else:
            fm = getattr(features_data, "feature_matrix", []) if features_data else []

        gaps_data = gap.get("gaps") if isinstance(gap, dict) else gap.gaps
        if isinstance(gaps_data, dict):
            caps = gaps_data.get("capability_gaps", [])
            advs = gaps_data.get("competitive_advantages", [])
            disadvs = gaps_data.get("competitive_disadvantages", [])
        else:
            caps = getattr(gaps_data, "capability_gaps", []) if gaps_data else []
            advs = getattr(gaps_data, "competitive_advantages", []) if gaps_data else []
            disadvs = getattr(gaps_data, "competitive_disadvantages", []) if gaps_data else []

        def _safe_item(item, field, default=""):
            if isinstance(item, dict):
                return item.get(field, default)
            return getattr(item, field, default)

        payload = {
            "positioning": {
                "our_positioning": cls._safe_get(pos, "our_positioning", ""),
                "competitor_positioning": cls._safe_get(pos, "competitor_positioning", ""),
                "positioning_diff": cls._safe_get(pos, "positioning_diff", ""),
            },
            "feature_matrix": [
                {"feature": _safe_item(f, "feature_name", ""),
                 "our_score": _safe_item(f, "our_score", "N/A"),
                 "competitor_score": _safe_item(f, "competitor_score", "N/A"),
                 "evidence_refs": _safe_item(f, "evidence_refs", [])}
                for f in (fm if isinstance(fm, list) else [])[:10]
            ],
            "capability_gaps": [
                {"description": _safe_item(c, "description", ""),
                 "evidence_refs": _safe_item(c, "evidence_refs", []),
                 "evidence_temporal_level": _safe_item(c, "evidence_temporal_level", "unknown")}
                for c in (caps if isinstance(caps, list) else [])[:5]
            ],
            "advantages": [
                {"description": _safe_item(a, "description", ""),
                 "evidence_refs": _safe_item(a, "evidence_refs", [])}
                for a in (advs if isinstance(advs, list) else [])[:3]
            ],
            "disadvantages": [
                {"description": _safe_item(d, "description", ""),
                 "evidence_refs": _safe_item(d, "evidence_refs", [])}
                for d in (disadvs if isinstance(disadvs, list) else [])[:3]
            ],
        }
        if isinstance(gap, dict):
            for key in (
                "compare_timeout",
                "compare_fallback",
                "generation_note",
                "compare_partial",
            ):
                if key in gap:
                    payload[key] = gap[key]
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @classmethod
    def _is_strategy_stub(cls, insights) -> bool:
        if not isinstance(insights, dict):
            return False
        return insights.get("swot_source") in ("evidence_stub", "partial_json") or insights.get(
            "strategy_fallback"
        ) in ("evidence_stub", "partial_json")

    @classmethod
    def _is_gap_stub(cls, gap) -> bool:
        if not isinstance(gap, dict):
            return False
        return gap.get("compare_fallback") in ("evidence_stub", "partial_json")

    @classmethod
    def _serialize_strategy(cls, insights) -> str:
        """Serialize strategy insights to JSON for LLM prompt."""
        if insights is None:
            insights = {}
        if isinstance(insights, dict):
            swot = insights.get("swot") if insights.get("swot") is not None else {}
            if not isinstance(swot, dict) and not hasattr(swot, "strengths"):
                swot = {}
            opps = insights.get("opportunities") or []
            risks = insights.get("risks") or []
            recs = insights.get("recommendations") or []
            roadmap = insights.get("roadmap") or {}
        else:
            swot = insights.swot or insights
            opps = insights.opportunities or []
            risks = insights.risks or []
            recs = insights.recommendations or []
            roadmap = insights.roadmap or {}

        def _swot_list(items):
            result = []
            for i in (items or [])[:5]:
                if isinstance(i, dict):
                    result.append({"conclusion": i.get("item", ""), "evidence_refs": i.get("evidence_refs", []),
                                   "confidence": i.get("confidence", "medium")})
                else:
                    result.append({"conclusion": getattr(i, "item", ""),
                                   "evidence_refs": getattr(i, "evidence_refs", []),
                                   "confidence": getattr(i, "confidence", "medium")})
            return result

        def _opp_list(items):
            result = []
            for o in items[:5]:
                if isinstance(o, dict):
                    result.append({"title": o.get("title", ""), "description": o.get("description", ""),
                                   "impact": o.get("impact", ""), "effort": o.get("effort", ""),
                                   "confidence": o.get("confidence", "medium"),
                                   "evidence_refs": o.get("evidence_refs", [])})
                else:
                    result.append({"title": getattr(o, "title", ""),
                                   "description": getattr(o, "description", ""),
                                   "impact": getattr(o, "impact", ""),
                                   "effort": getattr(o, "effort", ""),
                                   "confidence": getattr(o, "confidence", "medium"),
                                   "evidence_refs": getattr(o, "evidence_refs", [])})
            return result

        def _rec_list(items):
            result = []
            for r in items[:5]:
                if isinstance(r, dict):
                    result.append({"action": r.get("action", ""), "rationale": r.get("rationale", ""),
                                   "priority": r.get("priority", ""), "timeline": r.get("timeline", ""),
                                   "kpi": r.get("kpi", None), "expected_value": r.get("expected_value", ""),
                                   "evidence_refs": r.get("evidence_refs", []),
                                   "evidence_temporal_level": r.get("evidence_temporal_level", "unknown")})
                else:
                    result.append({"action": getattr(r, "action", ""),
                                   "rationale": getattr(r, "rationale", ""),
                                   "priority": getattr(r, "priority", ""),
                                   "timeline": getattr(r, "timeline", ""),
                                   "kpi": getattr(r, "kpi", None),
                                   "expected_value": getattr(r, "expected_value", ""),
                                   "evidence_refs": getattr(r, "evidence_refs", []),
                                   "evidence_temporal_level": getattr(r, "evidence_temporal_level", "unknown")})
            return result

        def _risk_list(items):
            result = []
            for r in items[:5]:
                if isinstance(r, dict):
                    result.append({"title": r.get("title", ""), "description": r.get("description", ""),
                                   "probability": r.get("probability", ""), "impact": r.get("impact", ""),
                                   "mitigation": r.get("mitigation", ""),
                                   "evidence_refs": r.get("evidence_refs", [])})
                else:
                    result.append({"title": getattr(r, "title", ""),
                                   "description": getattr(r, "description", ""),
                                   "probability": getattr(r, "probability", ""),
                                   "impact": getattr(r, "impact", ""),
                                   "mitigation": getattr(r, "mitigation", ""),
                                   "evidence_refs": getattr(r, "evidence_refs", [])})
            return result

        if isinstance(swot, dict):
            strengths = _swot_list(swot.get("strengths", []))
            weaknesses = _swot_list(swot.get("weaknesses", []))
            opportunities_swot = _swot_list(swot.get("opportunities", []))
            threats = _swot_list(swot.get("threats", []))
        else:
            strengths = _swot_list(getattr(swot, "strengths", []))
            weaknesses = _swot_list(getattr(swot, "weaknesses", []))
            opportunities_swot = _swot_list(getattr(swot, "opportunities", []))
            threats = _swot_list(getattr(swot, "threats", []))

        payload = {
            "swot": {
                "strengths": strengths,
                "weaknesses": weaknesses,
                "opportunities": opportunities_swot,
                "threats": threats,
            },
            "opportunities": _opp_list(opps),
            "risks": _risk_list(risks),
            "recommendations": _rec_list(recs),
            "roadmap_phases": [
                {"phase": (p.get("phase","") if hasattr(p,"get") else getattr(p,"phase","")), "initiatives": (p.get("initiatives",[]) if hasattr(p,"get") else getattr(p,"initiatives",[]))}
                for p in (roadmap.get("phases", []) if isinstance(roadmap, dict) else [])[:3]
            ],
        }
        if isinstance(insights, dict):
            for key in (
                "strategy_timeout",
                "strategy_fallback",
                "swot_source",
                "generation_note",
                "strategy_partial",
            ):
                if key in insights:
                    payload[key] = insights[key]
        return json.dumps(payload, ensure_ascii=False, indent=2)


    # ── Fallback report without LLM ──

    @classmethod
    def _build_fallback_report(cls, input_data, evidence_json, gap_json, strategy_json) -> str:
        """Generate a minimal report from available data without LLM."""
        our = getattr(input_data, "our_company", "") or "我方"
        comp = getattr(input_data, "competitor_company", "") or "竞品"
        prod = getattr(input_data, "product", "") or "产品"
        obj = getattr(input_data, "objective", "") or "竞品分析"

        lines = [
            f"# {our} vs {comp} 竞品分析报告",
            "",
            f"**产品**: {prod}",
            f"**分析目标**: {obj}",
            f"**生成日期**: {datetime.utcnow():%Y-%m-%d %H:%M}",
            "",
            "> ℹ️ 本报告由 AI Agent 自动生成。数据来源包括公开信息和 AI 分析。",
            "",
            "## 一、证据收集概况",
            "",
        ]
        # Evidence summary (evidence_json may be a JSON array or object)
        try:
            ev = json.loads(evidence_json) if isinstance(evidence_json, str) else evidence_json
            if isinstance(ev, list):
                items = ev
                sources = []
            elif isinstance(ev, dict):
                items = ev.get("evidence_summary", []) or []
                sources = ev.get("sources_used", []) or []
            else:
                items = []
                sources = []
            lines.append(f"- 共收集 {len(items)} 条证据")
            if sources:
                lines.append(f"- 来源: {', '.join(str(s) for s in sources[:10])}")
        except Exception:
            lines.append("- 证据数据暂时无法解析")
        lines.append("")

        # Gap summary
        lines.append("## 二、竞品差距分析")
        try:
            gap = json.loads(gap_json) if isinstance(gap_json, str) else gap_json
            positioning = gap.get("positioning", {})
            if positioning and isinstance(positioning, dict):
                our_pos = positioning.get("our_positioning", "未分析")
                comp_pos = positioning.get("competitor_positioning", "未分析")
                lines.append(f"- 我方定位: {str(our_pos)[:200]}")
                lines.append(f"- 竞品定位: {str(comp_pos)[:200]}")
            caps = gap.get("capability_gaps", [])
            if caps:
                lines.append(f"- 发现 {len(caps)} 个能力差距")
                for c in caps[:5]:
                    lines.append(f"  - {str(c.get('description', c))[:150]}")
        except Exception:
            lines.append("- 差距分析数据暂时无法解析")
        lines.append("")

        # Strategy summary
        lines.append("## 三、策略建议")
        try:
            strat = json.loads(strategy_json) if isinstance(strategy_json, str) else strategy_json
            recs = strat.get("recommendations", [])
            if recs:
                lines.append(f"共 {len(recs)} 条建议:")
                for r in recs[:5]:
                    action = r.get("action", str(r))
                    lines.append(f"- {str(action)[:200]}")
            swot = strat.get("swot", {})
            strengths = swot.get("strengths", [])
            if strengths:
                lines.append(f"- 优势项: {len(strengths)} 个")
            weaknesses = swot.get("weaknesses", [])
            if weaknesses:
                lines.append(f"- 劣势项: {len(weaknesses)} 个")
        except Exception:
            lines.append("- 策略数据暂时无法解析")
        lines.append("")

        lines.append("---")
        lines.append(f"*报告由 AI 竞品分析助手自动生成*")

        return "\n".join(lines)

    # ── Markdown → HTML ──


    @staticmethod
    def _markdown_to_html(md_text: str, input_data: ReportInput) -> str:
        html = HTMLBuilder()
        html.h1(f"{input_data.our_company} vs {input_data.competitor_company} 竞品分析报告")
        # meta info handled by cover()
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
        # date handled by cover()

        lines = md_text.split("\n")
        in_table = False
        table_headers: list[str] = []
        table_rows: list[list[str]] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                # End of table
                if in_table and table_headers and table_rows:
                    html.table(table_headers, table_rows)
                    table_rows = []
                    table_headers = []
                    in_table = False
                continue

            # Tables
            if "|" in stripped and not stripped.startswith("#"):
                if not in_table:
                    in_table = True
                cells = [c.strip() for c in stripped.split("|") if c.strip()]
                # Skip separator rows
                if all(c.replace("-", "").replace(":", "").strip() == "" for c in cells):
                    continue
                if not table_headers:
                    table_headers = cells
                else:
                    table_rows.append(cells)
                continue

            # End table on non-table content
            if in_table:
                if table_headers and table_rows:
                    html.table(table_headers, table_rows)
                table_rows = []
                table_headers = []
                in_table = False

            # Headings
            if stripped.startswith("## "):
                heading = stripped[3:]
                sid = heading_to_id(heading)
                html.h2(heading, sid=sid)
            elif stripped.startswith("### "):
                heading = stripped[4:]
                html.h3(heading)
            elif stripped.startswith("# "):
                heading = stripped[2:]
                if hasattr(html, 'h1'):
                    html.h1(heading)
                elif hasattr(html, 'add_title'):
                    html.add_title(heading)
            elif stripped.startswith("> "):
                html.quote(stripped[2:])
            elif stripped.startswith("- "):
                html.bullet([stripped[2:]])
            elif stripped:
                # Inline formatting
                formatted = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", stripped)
                formatted = re.sub(r"\[(E\d+)\]", r'<code>\1</code>', formatted)
                html.para(formatted)

        # Close any remaining table
        if in_table and table_headers and table_rows:
            html.table(table_headers, table_rows)

        return html.build()

    # ── Word generation ──

    @staticmethod
    def _save_word(md_text: str, input_data: ReportInput) -> str:
        """Save Word (.docx) from Markdown content."""
        word = WordBuilder()
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
        word.add_title("互联网产品竞品分析报告")
        word.add_meta(f"我方：{input_data.our_company} | 竞品：{input_data.competitor_company} | 产品：{input_data.product}")
        word.add_meta(f"生成日期：{now}")
        word.page_break()

        lines = md_text.split("\n")
        for line in lines:
            stripped = line.strip()

            # Skip cover elements
            if stripped.startswith("# ") and "竞品分析报告" in stripped:
                continue
            if stripped.startswith("> **我方**"):
                continue
            if not stripped:
                continue

            if stripped.startswith("## "):
                word.add_h2(stripped[3:])
            elif stripped.startswith("### "):
                word.add_h3(stripped[4:])
            elif stripped.startswith("# "):
                word.add_h1(stripped[2:])
            elif stripped.startswith("---"):
                word.add_para("")
            elif stripped.startswith("> "):
                word.quote(stripped[2:])
            elif stripped.startswith("- "):
                word.add_bullets([stripped[2:]])
            elif stripped.startswith("| ") or "|" in stripped:
                continue  # Skip tables in Word for now
            else:
                word.add_para(stripped)

        data_dir = settings.data_dir
        word_dir = data_dir / "word_outputs"
        word_path = str(word_dir / f"report_{uuid.uuid4().hex[:12]}.docx")
        return word.save(word_path)

    # ── Section extraction ──

    @staticmethod
    def _extract_sections(md_text: str) -> list[ReportSectionDTO]:
        """Extract report sections from Markdown for structured output."""
        sections: list[ReportSectionDTO] = []
        order = 0

        for section_title, section_id in SECTION_DEFS:
            order += 1
            # Find section content
            pattern = rf"## {re.escape(section_title)}"
            match = re.search(pattern, md_text)
            if match:
                start = match.start()
                # Find next ## section or end
                next_match = re.search(r"\n## ", md_text[start + len(section_title):])
                if next_match:
                    content = md_text[start:start + len(section_title) + next_match.start()]
                else:
                    content = md_text[start:]
                word_count = len(content.replace("\n", ""))
            else:
                content = f"[{section_title}] 暂无内容"
                word_count = 0

            sections.append(ReportSectionDTO(
                title=section_title,
                content=content[:2000],  # truncate for DTO
                order=order,
                word_count=word_count,
            ))

        return sections


def heading_to_id(heading: str) -> str:
    """Convert a Chinese heading to an HTML-safe ID."""
    # Map known headings to IDs
    id_map = {
        "目录": "toc",
        "一、Executive Summary": "executive_summary",
        "二、产品概览与定位": "positioning",
        "三、目标用户与画像": "users",
        "四、核心功能对比": "features",
        "五、用户体验与设计": "ux",
        "六、商业模式与收费": "business",
        "七、技术架构与能力": "technology",
        "八、增长策略与市场": "growth",
        "九、竞争格局": "competitive_landscape",
        "十、SWOT 分析": "swot_section",
        "十一、关键指标对比": "metrics",
        "十二、战略建议": "strategy",
        "十三、实施路线图": "roadmap",
        "附录": "appendix",
    }
    return id_map.get(heading, "section")
