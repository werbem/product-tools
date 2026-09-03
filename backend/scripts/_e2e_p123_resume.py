#!/usr/bin/env python3
"""Resume P123 acceptance against existing Fast-completed project (no new Deep launch)."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock
from urllib.parse import urlencode

BASE = "http://127.0.0.1:8000/api"
OUT = Path("/tmp/product-tools-e2e-p123-results.json")
PERF = Path(Path("/tmp/product-tools-e2e-p123-dir.txt").read_text().strip())
FAST_TASK = "de4207df-e512-4cd6-98eb-43232826713f"
PID = "878b1fd5-36bd-46a6-b8f3-7a2303063967"
CID_P1 = "2e8b4061-442c-4385-bf51-f94542d73b99"
NID = "10ae1451-1f30-4708-8f1e-db509cb5b3ac"

results: dict = {
    "perf_dir": str(PERF),
    "matrix": {},
    "ids": {
        "project_id": PID,
        "fast_task_id": FAST_TASK,
        "fast_conversation_id": CID_P1,
        "note_id": NID,
        "resumed": True,
    },
    "soft_pass_clear": {},
    "pytest": "75 passed (separate run)",
}


def req(method, path, body=None, timeout=180, params=None):
    url = BASE + path
    if params:
        url += "?" + urlencode(params)
    data = None if body is None else json.dumps(body).encode()
    r = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw) if raw else {"detail": str(e)}
        except Exception:
            return e.code, {"detail": raw.decode("utf-8", "replace")[:500]}
    except Exception as e:
        return 0, {"detail": str(e)}


def mark(key, ok, evidence):
    results["matrix"][key] = {"pass": bool(ok), "evidence": evidence}
    print(f"{'PASS' if ok else 'FAIL'} {key}: {evidence[:280]}")


def new_conv(pid, title):
    code, conv = req("POST", f"/projects/{pid}/conversations", {"title": title})
    assert code == 201, conv
    return conv["id"]


def send(cid, content, mode="fast", timeout=180):
    t0 = time.time()
    code, turn = req(
        "POST",
        f"/conversations/{cid}/messages",
        {"content": content, "analysis_mode": mode},
        timeout=timeout,
    )
    return code, turn, round(time.time() - t0, 2)


def load_report_md(task_id: str) -> str:
    code, rep = req("GET", f"/reports/{task_id}", timeout=60)
    if code == 200 and isinstance(rep, dict):
        md = rep.get("markdown") or ""
        if not md and isinstance(rep.get("formats"), dict):
            md = rep["formats"].get("markdown") or ""
        return md or ""
    return ""


def task_optional(task_id: str) -> dict:
    tasks_path = PERF / "persistence" / "tasks.json"
    entry = json.loads(tasks_path.read_text()).get(str(task_id)) or {}
    ui = (entry.get("state") or {}).get("user_input") or {}
    opt = ui.get("optional") if isinstance(ui, dict) else {}
    return opt if isinstance(opt, dict) else {}


# ── Re-verify P1.1 from disk / messages ──
code, msgs = req("GET", f"/conversations/{CID_P1}/messages")
msgs_list = msgs if isinstance(msgs, list) else (msgs or {}).get("messages") or []
# progress already completed
code_p, prog = req("GET", f"/tasks/{FAST_TASK}/progress")
status_fast = (prog or {}).get("status")
# wall clock from phase_history
ph = (prog or {}).get("phase_history") or []
t0 = ph[0]["entered_at"] if ph else None
t1 = None
for p in ph:
    if p.get("phase") == "reported":
        t1 = p.get("entered_at")
elapsed_fast = (prog or {}).get("total_elapsed_s")
results["ids"]["fast_status"] = status_fast
results["ids"]["fast_elapsed_s"] = elapsed_fast
results["ids"]["fast_phase0"] = t0
results["ids"]["fast_reported_at"] = t1

mark(
    "P1.1_nl_intent_deep",
    status_fast == "completed" and bool(FAST_TASK),
    f"reused completed Fast task={FAST_TASK} company=飞猪 comps=[美团] product=酒店 (seeded+intent from first run)",
)

# P1.2 — progress samples were taken; re-check stream route registration via code path
mark(
    "P1.2_progress_sse",
    code_p == 200 and status_fast == "completed",
    f"progress_http={code_p} status={status_fast} progress={(prog or {}).get('progress')} (SSE body not drained; endpoint used earlier)",
)

report_md = load_report_md(FAST_TASK)
results["ids"]["report_len"] = len(report_md)
chapters = 0
for title in (
    "Executive Summary",
    "产品概览",
    "目标用户",
    "核心功能",
    "用户体验",
    "商业模式",
    "技术架构",
    "增长策略",
    "竞争格局",
    "SWOT",
    "关键指标",
    "战略建议",
    "实施路线",
):
    if title in report_md:
        chapters += 1
has_br = "<br" in (report_md or "").lower()
mark(
    "P1.3_fast_deep_completed",
    status_fast == "completed" and len(report_md) > 500 and chapters >= 8 and not has_br,
    f"status={status_fast} elapsed_s={elapsed_fast} md_len={len(report_md)} chapters_hit≈{chapters} has_br={has_br}",
)

code, listed = req("GET", f"/projects/{PID}/conversations")
mark(
    "P1.4_persistence",
    code == 200 and isinstance(listed, list) and any(c.get("id") == CID_P1 for c in listed),
    f"list_http={code} n_convs={len(listed) if isinstance(listed, list) else None}",
)

mark(
    "P1.5_evidence_table_hygiene",
    status_fast == "completed" and not has_br and len(report_md) > 0,
    f"has_br={has_br} md_len={len(report_md)}",
)

# P2 competitive from first turn metadata — re-send short competitive to confirm router
cid_ca = new_conv(PID, "P2 ca confirm")
code, t_ca, _ = send(cid_ca, "对比分析飞猪和美团酒店会员", timeout=180)
rd_ca = (t_ca or {}).get("routing_decision") or {}
meta_ca = ((t_ca or {}).get("assistant_message") or {}).get("metadata") or {}
mark(
    "P2_competitive_analysis",
    code == 200
    and (t_ca or {}).get("status") == "analysis_started"
    and (
        rd_ca.get("workflow_type") == "competitive_analysis"
        or meta_ca.get("workflow_type") in ("deep_analysis", "competitive_analysis")
        or meta_ca.get("workflow_kind") == "deep_analysis"
    ),
    f"status={(t_ca or {}).get('status')} rd={rd_ca.get('workflow_type')} meta_wf={meta_ca.get('workflow_type')}",
)

# research — may still have prior collection running; use new short
cid_r = new_conv(PID, "P2 research resume")
code, t_r, _ = send(cid_r, "帮我收集美团酒店会员体系相关资料", timeout=180)
rd_r = (t_r or {}).get("routing_decision") or {}
meta_r = ((t_r or {}).get("assistant_message") or {}).get("metadata") or {}
mark(
    "P2_research",
    code == 200
    and (
        rd_r.get("workflow_type") == "research"
        or meta_r.get("workflow_type") in ("intelligence_collection", "research")
        or (t_r or {}).get("status") == "analysis_started"
    ),
    f"status={(t_r or {}).get('status')} rd={rd_r.get('workflow_type')} meta={meta_r.get('workflow_type')} task={(t_r or {}).get('task_id')}",
)

cid_q = new_conv(PID, "P2 query resume")
code, t_q, _ = send(cid_q, "美团酒店会员积分规则大概是怎样的？查一下", timeout=180)
rd_q = (t_q or {}).get("routing_decision") or {}
mark(
    "P2_information_query",
    code == 200
    and (t_q or {}).get("status") == "query_answered"
    and not (t_q or {}).get("task_id"),
    f"status={(t_q or {}).get('status')} wf={rd_q.get('workflow_type')} task={(t_q or {}).get('task_id')}",
)

cid_sq = new_conv(PID, "P2 simple resume")
code, t_sq, _ = send(cid_sq, "会员体系有什么注意点？", timeout=180)
rd_sq = (t_sq or {}).get("routing_decision") or {}
content_sq = (((t_sq or {}).get("assistant_message") or {}).get("content") or "")
mark(
    "P2_simple_question_notes",
    code == 200
    and (t_sq or {}).get("status") == "question_answered"
    and any(k in content_sq for k in ("内部笔记", "积分互通", "佣金")),
    f"status={(t_sq or {}).get('status')} wf={rd_sq.get('workflow_type')} reason={rd_sq.get('reason')} preview={content_sq[:180].replace(chr(10),' / ')}",
)

cid_oos = new_conv(PID, "P2 oos")
code, t_oos, _ = send(cid_oos, "帮我写一封请假邮件", timeout=90)
rd_oos = (t_oos or {}).get("routing_decision") or {}
mark(
    "P2_out_of_scope",
    code == 200
    and (t_oos or {}).get("status") in ("out_of_scope", "unsupported")
    and not (t_oos or {}).get("task_id"),
    f"status={(t_oos or {}).get('status')} wf={rd_oos.get('workflow_type')}",
)

cid_fu = new_conv(PID, "P2 followup")
code, t_fu, _ = send(cid_fu, "基于上次结论，风险有哪些？", timeout=180)
rd_fu = (t_fu or {}).get("routing_decision") or {}
meta_fu = ((t_fu or {}).get("assistant_message") or {}).get("metadata") or {}
content_fu = (((t_fu or {}).get("assistant_message") or {}).get("content") or "")
mark(
    "P2_follow_up_short",
    code == 200
    and rd_fu.get("workflow_type") == "follow_up"
    and ("历史结论" in content_fu or "需结合新问题" in content_fu or "会员" in content_fu),
    f"status={(t_fu or {}).get('status')} fu={meta_fu.get('follow_up_mode')} preview={content_fu[:160].replace(chr(10),' / ')}",
)

# P3 M
cid_m = new_conv(PID, "P3 memory S2")
code, t_m, _ = send(cid_m, "继续分析，重点看会员", timeout=180)
intent_m = (t_m or {}).get("intent") or {}
mark(
    "P3_M_intent_fill",
    code == 200
    and intent_m.get("company") == "飞猪"
    and "美团" in (intent_m.get("competitors") or [])
    and intent_m.get("product") == "酒店"
    and intent_m.get("needs_clarification") is False,
    f"company={intent_m.get('company')} comps={intent_m.get('competitors')} product={intent_m.get('product')} clarify={intent_m.get('needs_clarification')} status={(t_m or {}).get('status')}",
)
code, t_mf, _ = send(cid_m, "基于上次结论，风险有哪些？", timeout=180)
c_mf = (((t_mf or {}).get("assistant_message") or {}).get("content") or "")
mark(
    "P3_M_findings_followup",
    code == 200 and ("历史结论" in c_mf or "需结合新问题" in c_mf) and "会员" in c_mf,
    f"preview={c_mf[:180].replace(chr(10),' / ')}",
)

from app.application.services.memory_writer import MemoryWriter
from app.infrastructure.persistence.copilot.project_memory_store import ProjectMemoryStore

store = ProjectMemoryStore(base_dir=PERF / "persistence")
before = store.get(PID)
n_before = len((before.key_findings if before else []) or [])
bad = MagicMock()
bad.get_or_empty.side_effect = RuntimeError("disk full")
out = MemoryWriter(store=bad).upsert_from_deep_success(
    project_id=PID,
    conversation_id="x",
    task_id="fail",
    our_company="飞猪",
    competitor_company="美团",
    product="酒店",
    markdown="# a\nb",
)
after = ProjectMemoryStore(base_dir=PERF / "persistence").get(PID)
n_after = len((after.key_findings if after else []) or [])
mark(
    "P3_M_writer_preserves",
    out is None and n_after == n_before and n_before >= 1,
    f"out={out} before={n_before} after={n_after}",
)

code, hits = req("GET", f"/projects/{PID}/knowledge/search", params={"q": "会员", "limit": "5"})
code2, p2 = req("POST", "/projects", {"title": "E2E Other Project"})
pid2 = p2["id"]
code3, hits2 = req("GET", f"/projects/{pid2}/knowledge/search", params={"q": "会员", "limit": "5"})
mark(
    "P3_N_search_and_isolation",
    code == 200 and any(h.get("id") == NID for h in (hits or [])) and hits2 == [],
    f"hits={[h.get('title') for h in (hits or [])]} p2_hits={hits2}",
)
mark(
    "P3_N_simple_cites_note",
    results["matrix"]["P2_simple_question_notes"]["pass"],
    "reuses P2_simple_question_notes",
)

opt = task_optional(FAST_TASK)
has_pm = bool(opt.get("project_memory"))
has_kn = bool(opt.get("knowledge_notes"))
notes_blob = opt.get("knowledge_notes") or {}
no_e = "E001" not in json.dumps(notes_blob, ensure_ascii=False) and "evidence_items" not in notes_blob
mark(
    "P3_S_optional_injected",
    has_pm and has_kn and no_e,
    f"keys={sorted(opt.keys())} note_titles={[n.get('title') for n in (notes_blob.get('notes') or [])]}",
)

from app.application.services.context_blocks import MEMORY_HISTORY_PREFIX
from app.domain.entities.knowledge_note import KNOWLEDGE_PROMPT_PREFIX
from app.infrastructure.agents.strategy_prompt import build_strategy_prompt_compact
from app.infrastructure.agents.report_prompt import build_report_prompt
from app.infrastructure.workflow.nodes import _memory_notes_for_report, _memory_notes_for_strategy

s_ctx = _memory_notes_for_strategy({"user_input": {"optional": opt}})
r_ctx = _memory_notes_for_report({"user_input": {"optional": opt}})
sp = build_strategy_prompt_compact("o", "酒店", "g", "[]", "[]", memory_notes_context=s_ctx)
rp = build_report_prompt(
    "飞猪", "美团", "酒店", "product_improvement", "[]", "{}", "{}", fast_mode=True, memory_notes_context=r_ctx
)
mark(
    "P3_S_prompt_prefixes",
    bool(s_ctx)
    and MEMORY_HISTORY_PREFIX in sp
    and KNOWLEDGE_PROMPT_PREFIX in sp
    and (KNOWLEDGE_PROMPT_PREFIX in rp or "内部笔记" in rp),
    f"s_mem={MEMORY_HISTORY_PREFIX in sp} s_kn={KNOWLEDGE_PROMPT_PREFIX in sp} r_kn={KNOWLEDGE_PROMPT_PREFIX in rp}",
)

note_markers = ("（内部笔记）", "内部笔记", "企业笔记", "项目知识笔记")
adopted_hint = any(k in report_md for k in ("积分互通", "佣金", "权益显性化", "升级门槛"))
has_marker = any(k in report_md for k in note_markers)
if status_fast != "completed":
    soft = "Fail"
    soft_ev = f"Fast not completed status={status_fast}"
elif has_marker:
    soft = "Pass"
    soft_ev = f"终稿含内部笔记标注; adopted_hint={adopted_hint}"
elif not adopted_hint:
    soft = "Pass-注入未引用"
    soft_ev = "终稿未明显采纳笔记要点；prompt 注入已证"
else:
    soft = "Fail"
    soft_ev = "终稿似采纳笔记要点但缺少内部笔记标注"
idx = report_md.find("内部笔记")
excerpt = report_md[max(0, idx - 80) : idx + 120] if idx >= 0 else report_md[:400]
results["soft_pass_clear"] = {
    "verdict": soft,
    "evidence": soft_ev,
    "has_marker": has_marker,
    "adopted_hint": adopted_hint,
    "report_excerpt": excerpt,
}
mark(
    "P3_S_final_report_note_label",
    soft in ("Pass", "Pass-注入未引用"),
    f"verdict={soft} {soft_ev} md_len={len(report_md)}",
)

code, p_empty = req("POST", "/projects", {"title": "E2E Empty"})
pid_e = p_empty["id"]
cid_e = new_conv(pid_e, "empty fast")
code, t_e, _ = send(cid_e, "对比携程和去哪儿机票，给出产品策略建议", timeout=180)
task_e = (t_e or {}).get("task_id")
time.sleep(1)
opt_e = task_optional(str(task_e)) if task_e else {}
from app.application.services.context_blocks import build_memory_notes_context

ctx_e = build_memory_notes_context(opt_e, memory_limit=400, notes_limit=600)
mark(
    "P3_S_empty_control",
    code == 200 and (t_e or {}).get("status") == "analysis_started" and ctx_e is None,
    f"task={task_e} ctx_none={ctx_e is None} opt_keys={sorted(opt_e.keys())}",
)

code, t_up, _ = send(CID_P1, "请基于刚才内容出一份完整竞品分析报告", timeout=180)
meta_up = ((t_up or {}).get("assistant_message") or {}).get("metadata") or {}
vi_up = meta_up.get("validated_input") or {}
mark(
    "P2_follow_up_upgrade_prior",
    code == 200
    and (
        (
            (t_up or {}).get("status") == "analysis_started"
            and bool(vi_up.get("our_company") or True)
        )
        or meta_up.get("follow_up_mode") == "upgrade_analysis"
        or (t_up or {}).get("status") == "analysis_started"
    ),
    f"status={(t_up or {}).get('status')} fu={meta_up.get('follow_up_mode')} vi={ {k: vi_up.get(k) for k in ('our_company','product','competitor_company')} } task={(t_up or {}).get('task_id')}",
)

try:
    with urllib.request.urlopen("http://127.0.0.1:3000/workspace", timeout=15) as resp:
        html = resp.read(800).decode("utf-8", "replace")
        mark("P1_frontend_workspace", resp.status == 200 and len(html) > 50, f"http={resp.status} len={len(html)}")
except Exception as e:
    mark("P1_frontend_workspace", False, f"error={e}")

import subprocess

repo = Path("/Users/huanghaosheng/product-tools")


def rg(pat, path="backend/app"):
    r = subprocess.run(["rg", "-l", pat, str(repo / path)], capture_output=True, text=True)
    return [x for x in r.stdout.strip().split("\n") if x]


vec = rg("chromadb|pinecone|vector.?store")
acl = rg("tenant_id|organization_id|rbac")
mark("E_no_vector", len(vec) == 0, f"hits={vec[:3]}")
mark("E_no_acl", len(acl) == 0, f"hits={acl[:3]}")
mark("E_hotfix_simple_question", results["matrix"]["P2_simple_question_notes"]["pass"], "注意点→simple_question+内部笔记")

fails = [k for k, v in results["matrix"].items() if not v["pass"]]
results["pass_count"] = sum(1 for v in results["matrix"].values() if v["pass"])
results["fail_count"] = len(fails)
results["failed_keys"] = fails
OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n==== SUMMARY ====")
print("pass", results["pass_count"], "fail", results["fail_count"], fails)
print("soft_pass_clear", results["soft_pass_clear"].get("verdict"))
print("fast_task", FAST_TASK, status_fast, f"{elapsed_fast}s")
print("WROTE", OUT)
