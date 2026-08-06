export interface AnalysisInput {
  our_company: string;
  competitor_company: string;
  product: string;
  objective: string;
  scene?: string;
  optional?: Record<string, unknown>;
}

export interface ReportCreateResponse {
  task_id: string;
  status: string;
  message: string;
}

export interface DemoStatusResponse {
  demo_mode: boolean;
  reason?: string | null;
  demo_case?: string | null;
}

export interface PhaseRecord {
  phase: string;
  entered_at: string;
  duration_ms: number;
  status: "running" | "completed" | "failed";
  error?: { code?: string; message?: string } | null;
}

export interface TaskProgressResponse {
  task_id: string;
  status: string;
  current_agent: string;
  progress: number;
  phase_history: PhaseRecord[];
  error_info?: string | null;
  diagnosis?: DiagnosisInfo | null;
  created_at: string;

}

export interface DiagnosisInfo {
  task_id?: string;
  failed_stage?: string;
  failed_agent?: string;
  error_type?: string;
  root_cause?: string;
  suggestion?: string;
  retry_available?: boolean;
  error_code?: string;
  error_message?: string;
  timestamp?: string;
}

export interface ReportSectionDTO {
  title: string;
  content: string;
  order: number;
  word_count: number;
}

export interface ReportDetailResponse {
  id: string;
  task_id: string;
  our_company: string;
  competitor_company: string;
  product: string;
  objective: string;
  markdown: string | null;
  html: string | null;
  word_url: string | null;
  sections: ReportSectionDTO[];
  total_word_count: number;
  generated_at: string | null;
  status?: string | null;
  error?: string | null;
  diagnosis?: DiagnosisInfo | null;
  created_at: string;
  evidence_sources?: {
    source_id?: string;
    url?: string;
    title?: string;
    summary?: string;
    source_type?: string;
    date?: string;
    domain?: string;
  }[]
}

export interface HistoryEntry {
  taskId: string;
  ourCompany: string;
  competitorCompany: string;
  product: string;
  objective: string;
  createdAt: string;
  demo?: boolean;
}

export const OBJECTIVE_LABELS: Record<string, string> = {
  product_improvement: "产品改进 — 对标竞品发现短板",
  go_to_market: "市场进入 — 制定差异化策略",
  investment_due_diligence: "投资尽调 — 评估竞争壁垒",
  competitive_defense: "竞争防御 — 应对竞品进攻",
  positioning_switch: "定位转型 — 重新定义定位",
  partnership_evaluation: "合作评估 — 生态合作考察",
  feature_benchmark: "功能对标 — 深度功能对比",
};

export const PHASE_LABELS: Record<string, string> = {
  initialized: "初始化",
  validated: "输入验证",
  planned: "制定计划",
  researched: "收集证据",
  compared: "竞品对比",
  strategized: "战略分析",
  reported: "生成报告",
  reviewed: "质量审查",
  completed: "分析完成",
  failed: "分析失败",
  review_failed: "审查未通过",
  need_more_research: "证据不足",
};

export const CUSTOM_OBJECTIVE = "__custom__";

export const OBJECTIVE_OPTIONS = [
  { value: "product_improvement", label: "产品改进 — 对标竞品发现短板" },
  { value: "go_to_market", label: "市场进入 — 制定差异化策略" },
  { value: "investment_due_diligence", label: "投资尽调 — 评估竞争壁垒" },
  { value: "competitive_defense", label: "竞争防御 — 应对竞品进攻" },
  { value: "positioning_switch", label: "定位转型 — 重新定义定位" },
  { value: "partnership_evaluation", label: "合作评估 — 生态合作考察" },
  { value: "feature_benchmark", label: "功能对标 — 深度功能对比" },
  { value: CUSTOM_OBJECTIVE, label: "自定义分析目标..." },
];

export const PHASE_ORDER: Record<string, number> = {
  initialized: 0,
  validated: 1,
  planned: 2,
  researched: 3,
  compared: 4,
  strategized: 5,
  reported: 6,
  reviewed: 7,
  completed: 8,
  failed: 9,
  review_failed: 9,
  need_more_research: 9,
};

// SSE streaming types
export interface StreamEvent {
  event_type: "phase_update" | "done" | "heartbeat";
  agent?: string;
  status?: "running" | "completed";
  message?: string;
  progress?: number;
  timestamp: number;
  data?: Record<string, unknown>;
}
