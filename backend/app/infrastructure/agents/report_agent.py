"""Report Agent — LLM-powered structured report generation.

Uses real LLM to organize evidence, gap analysis, and strategy insights
into a well-formatted competitive analysis report.

Formats: Markdown (LLM), HTML + Word (export tools)
"""

from __future__ import annotations

import json
import os
import re
import uuid
import traceback
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
    build_report_prompt,
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


class ReportAgent(BaseAgent[ReportInput, ReportOutput]):

    @property
    def agent_name(self) -> str:
        return "report"

    @property
    def phase(self) -> Phase:
        return Phase.REPORTING

    async def arun(self, ctx: AgentContext, input_data: ReportInput) -> AgentResult:
        try:
            eb = input_data.evidence_bundle
            gap = input_data.gap_analysis
            insights = input_data.strategic_insights

            # ── Serialize input data for LLM ──
            evidence_json = self._serialize_evidence(eb)
            gap_json = self._serialize_gap(gap)
            strategy_json = self._serialize_strategy(insights)

            # ── Call LLM ──
            result = await llm_client.generate(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=build_report_prompt(
                    our_company=input_data.our_company if hasattr(input_data, 'our_company') else "我方",
                    competitor_company=input_data.competitor_company if hasattr(input_data, 'competitor_company') else "竞品",
                    product=input_data.product if hasattr(input_data, 'product') else "产品",
                    objective=input_data.objective if hasattr(input_data, 'objective') else "competitive_defense",
                    evidence_json=evidence_json,
                    gap_json=gap_json,
                    strategy_json=strategy_json,
                ),
                response_model=None,
                temperature=0.5,
                timeout=120.0,
            )
        except Exception as e:
            traceback.print_exc()
            # Generate fallback report from available data
            fallback_md = self._build_fallback_report(input_data, evidence_json, gap_json, strategy_json)
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
                })
        return json.dumps(items, ensure_ascii=False, indent=2)

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

        return json.dumps({
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
                 "evidence_refs": _safe_item(c, "evidence_refs", [])}
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
        }, ensure_ascii=False, indent=2)

    @classmethod
    def _serialize_strategy(cls, insights) -> str:
        """Serialize strategy insights to JSON for LLM prompt."""
        if isinstance(insights, dict):
            swot = insights.get("swot") or insights
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
            for i in items[:5]:
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
                                   "evidence_refs": r.get("evidence_refs", [])})
                else:
                    result.append({"action": getattr(r, "action", ""),
                                   "rationale": getattr(r, "rationale", ""),
                                   "priority": getattr(r, "priority", ""),
                                   "timeline": getattr(r, "timeline", ""),
                                   "kpi": getattr(r, "kpi", None),
                                   "expected_value": getattr(r, "expected_value", ""),
                                   "evidence_refs": getattr(r, "evidence_refs", [])})
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

        return json.dumps({
            "swot": {
                "strengths": _swot_list(getattr(swot, "strengths", []) if hasattr(swot, "strengths") else []),
                "weaknesses": _swot_list(getattr(swot, "weaknesses", []) if hasattr(swot, "weaknesses") else []),
                "opportunities": _swot_list(getattr(swot, "opportunities", []) if hasattr(swot, "opportunities") else []),
                "threats": _swot_list(getattr(swot, "threats", []) if hasattr(swot, "threats") else []),
            },
            "opportunities": _opp_list(opps),
            "risks": _risk_list(risks),
            "recommendations": _rec_list(recs),
            "roadmap_phases": [
                {"phase": (p.get("phase","") if hasattr(p,"get") else getattr(p,"phase","")), "initiatives": (p.get("initiatives",[]) if hasattr(p,"get") else getattr(p,"initiatives",[]))}
                for p in (roadmap.get("phases", []) if isinstance(roadmap, dict) else [])[:3]
            ],
        }, ensure_ascii=False, indent=2)


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
            f"**生成日期**: {datetime.utcnow().strftime("%Y-%m-%d %H:%M")}",
            "",
            "> ℹ️ 本报告由 AI Agent 自动生成。数据来源包括公开信息和 AI 分析。",
            "",
            "## 一、证据收集概况",
            "",
        ]
        # Evidence summary
        try:
            ev = json.loads(evidence_json) if isinstance(evidence_json, str) else evidence_json
            items = ev.get("evidence_summary", [])
            lines.append(f"- 共收集 {len(items)} 条证据")
            sources = ev.get("sources_used", [])
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
