import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
} from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Loader2,
  Activity,
  Info,
  Search,
  Brain,
  ChevronDown,
  ChevronUp,
  Link,
  AlertTriangle,
  Shield,
  FileText,
  BarChart2,
  ChevronRight,
  MessageSquare,
  TrendingUp,
  Clock,
} from "lucide-react";
import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";

export interface ProcessedEvent {
  title: string;
  data: any;
}

interface ActivityTimelineProps {
  processedEvents: ProcessedEvent[];
  isLoading: boolean;
  websiteCount: number;
}

// ── Score bar helper ──────────────────────────────────────────────────────────
function ScoreBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color =
    pct >= 80 ? "bg-red-500"
    : pct >= 60 ? "bg-orange-400"
    : pct >= 30 ? "bg-yellow-400"
    : "bg-emerald-400";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-neutral-800 rounded-full h-1.5">
        <div className={`${color} h-1.5 rounded-full transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className={`text-xs font-mono font-bold ${
        pct >= 80 ? "text-red-400" : pct >= 60 ? "text-orange-300" : "text-neutral-300"
      }`}>{pct}%</span>
    </div>
  );
}

// ── Decision badge ────────────────────────────────────────────────────────────
function DecisionBadge({ decision }: { decision: string }) {
  const styles: Record<string, string> = {
    ESCALATE:          "bg-red-900/60 text-red-300 border border-red-700",
    INVESTIGATE_FURTHER: "bg-orange-900/60 text-orange-300 border border-orange-700",
    MONITOR:           "bg-yellow-900/60 text-yellow-300 border border-yellow-700",
    CLOSE:             "bg-neutral-700 text-neutral-400",
    CONTINUE:          "bg-blue-900/60 text-blue-300 border border-blue-700",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded font-semibold ${styles[decision] ?? "bg-neutral-700 text-neutral-400"}`}>
      {decision.replace("_", " ")}
    </span>
  );
}

// ── Flag pill ─────────────────────────────────────────────────────────────────
function FlagPill({ label, active }: { label: string; active: boolean }) {
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${
      active ? "bg-red-900/60 text-red-300" : "bg-neutral-700 text-neutral-500"
    }`}>
      {label}
    </span>
  );
}

// ── Expandable section ────────────────────────────────────────────────────────
function Expandable({ label, children }: { label: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-1">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1 text-xs text-neutral-400 hover:text-neutral-200 transition-colors"
      >
        <ChevronRight className={`h-3 w-3 transition-transform ${open ? "rotate-90" : ""}`} />
        {label}
      </button>
      {open && <div className="mt-1 ml-4">{children}</div>}
    </div>
  );
}

// ── Investigator result card ──────────────────────────────────────────────────
function InvestigatorCard({ d }: { d: any }) {
  const score = d.anomaly_score ?? 0;
  return (
    <div className="space-y-1.5">
      <ScoreBar score={score} />
      <div className="flex flex-wrap gap-1 mt-1">
        {d.agent === "orders_investigator" && <>
          <FlagPill label="Spoofing" active={d.spoofing_flag} />
          <FlagPill label={`Layering ×${d.layering_count}`} active={d.layering_count > 0} />
          {d.cancel_rate != null && (
            <span className="text-xs text-neutral-400">
              Cancel rate: <span className="text-neutral-200 font-mono">{(d.cancel_rate * 100).toFixed(1)}%</span>
              {" "}/ {d.total_orders} orders
            </span>
          )}
        </>}
        {d.agent === "trades_investigator" && <>
          <FlagPill label={`Front-run ×${d.front_run_count}`} active={d.front_run_count > 0} />
          <FlagPill label={`Wash ×${d.wash_pairs}`} active={d.wash_pairs > 0} />
          {d.total_trades != null && (
            <span className="text-xs text-neutral-400">{d.total_trades} trades</span>
          )}
        </>}
        {d.agent === "market_data_investigator" && <>
          <FlagPill label="Vol Anomaly" active={d.volume_anomaly_flag} />
          <FlagPill label="Spread Widening" active={d.spread_widening} />
          {d.volume_zscore != null && (
            <span className="text-xs text-neutral-400">
              Z-score: <span className="text-neutral-200 font-mono">{d.volume_zscore.toFixed(2)}</span>
            </span>
          )}
          {d.price_change_pct != null && (
            <span className="text-xs text-neutral-400">
              Price Δ: <span className="text-neutral-200 font-mono">{d.price_change_pct.toFixed(3)}%</span>
            </span>
          )}
        </>}
        {d.agent === "comms_investigator" && <>
          <span className="text-xs text-neutral-400">
            Hits: <span className="text-neutral-200 font-mono">{d.keyword_hits}</span>
            {d.total_comms != null && ` / ${d.total_comms} msgs`}
          </span>
          {(d.comms_categories ?? []).map((cat: string) => (
            <span key={cat} className="text-xs px-1.5 py-0.5 rounded bg-purple-900/50 text-purple-300">
              {cat.replace("_", " ")}
            </span>
          ))}
        </>}
      </div>
    </div>
  );
}

// ── Escalation score card ─────────────────────────────────────────────────────
function EscalationScoreCard({ d }: { d: any }) {
  const score = d.score ?? 0;
  const queries: string[] = d.follow_up_queries ?? [];
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3">
        <div className="text-2xl font-bold font-mono text-white">
          {(score * 100).toFixed(0)}
          <span className="text-sm text-neutral-400">/ 100</span>
        </div>
        <DecisionBadge decision={d.decision ?? "MONITOR"} />
      </div>
      <ScoreBar score={score} />
      {d.reasoning && (
        <Expandable label="Reasoning">
          <p className="text-xs text-neutral-400 leading-relaxed">{d.reasoning}</p>
        </Expandable>
      )}
      {queries.length > 0 && (
        <Expandable label={`${queries.length} follow-up queries`}>
          <ul className="space-y-1">
            {queries.map((q: string, i: number) => (
              <li key={i} className="text-xs text-neutral-400 flex gap-1">
                <span className="text-neutral-500 shrink-0">{i + 1}.</span>{q}
              </li>
            ))}
          </ul>
        </Expandable>
      )}
    </div>
  );
}

// ── Escalation check banner ───────────────────────────────────────────────────
function EscalationCheckCard({ d }: { d: any }) {
  const escalating = d.decision === "ESCALATE";
  return (
    <div className={`flex items-center gap-3 px-3 py-2 rounded text-xs ${
      escalating ? "bg-red-900/40 border border-red-700/50" : "bg-blue-900/30 border border-blue-700/40"
    }`}>
      {escalating
        ? <AlertTriangle className="h-4 w-4 text-red-400 shrink-0" />
        : <Search className="h-4 w-4 text-blue-400 shrink-0" />}
      <div>
        <span className="text-neutral-200 font-medium">
          {escalating ? "Threshold reached" : `Attempt ${d.attempt} — continuing`}
        </span>
        <span className="text-neutral-400 ml-2">
          score {(d.score * 100).toFixed(0)}% {escalating ? "≥" : "<"} {(d.threshold * 100).toFixed(0)}%
        </span>
      </div>
    </div>
  );
}

// ── SOP invocation card ───────────────────────────────────────────────────────
function SopCard({ d }: { d: any }) {
  const sections: string[] = d.sop_sections_invoked ?? [];
  const rules: string[] = d.expansion_rules_fired ?? [];
  const keywords: string[] = d.comms_keywords_used ?? [];
  const checks: string[] = d.extra_checks_performed ?? [];
  const base = d.time_window_base ?? "";
  const expanded = d.time_window_expanded ?? "";

  return (
    <div className="space-y-2">
      {/* SOP sections */}
      {sections.length > 0 && (
        <div>
          <p className="text-xs text-neutral-500 mb-1">SOP sections invoked</p>
          <div className="flex flex-wrap gap-1">
            {sections.map((s: string) => (
              <span key={s} className="text-xs px-1.5 py-0.5 rounded bg-emerald-900/40 text-emerald-300">
                ✓ {s}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Time window */}
      {base && (
        <div className="flex items-center gap-1.5 text-xs">
          <Clock className="h-3 w-3 text-neutral-500 shrink-0" />
          <span className="text-neutral-500 font-mono">{base}</span>
          {expanded && expanded !== base && <>
            <span className="text-neutral-600">→</span>
            <span className="text-cyan-400 font-mono">{expanded}</span>
          </>}
        </div>
      )}

      {/* Expansion rules */}
      {rules.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {rules.map((r: string) => (
            <span key={r} className="text-xs px-1.5 py-0.5 rounded bg-orange-900/40 text-orange-300">
              {r}
            </span>
          ))}
        </div>
      )}

      {/* Extra checks & keywords */}
      {checks.length > 0 && (
        <Expandable label={`${checks.length} extra checks`}>
          <ul className="space-y-0.5">
            {checks.map((c: string, i: number) => (
              <li key={i} className="text-xs text-neutral-400">• {c}</li>
            ))}
          </ul>
        </Expandable>
      )}
      {keywords.length > 0 && (
        <Expandable label={`${keywords.length} keywords used`}>
          <p className="text-xs text-neutral-400 font-mono break-all">
            {keywords.join(", ")}
          </p>
        </Expandable>
      )}
    </div>
  );
}

// ── Artifact written card ─────────────────────────────────────────────────────
function ArtifactCard({ d }: { d: any }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <DecisionBadge decision={d.decision ?? "MONITOR"} />
        <span className="text-xs text-neutral-400">
          Score <span className="text-neutral-200 font-mono font-bold">
            {((d.score ?? 0) * 100).toFixed(0)}%
          </span>
        </span>
      </div>

      {/* File paths + Excel download */}
      <div className="space-y-0.5 text-xs font-mono text-neutral-400">
        {d.yaml_path  && <div className="truncate">📄 {d.yaml_path}</div>}
        {d.xlsx_path  && (
          <div className="flex items-center gap-2">
            <span className="truncate">📊 {d.xlsx_path}</span>
            <a
              href={`/files/${d.xlsx_path.split('agent_outputs/')[1]}`}
              download
              className="shrink-0 px-2 py-0.5 rounded bg-emerald-700 hover:bg-emerald-600 text-emerald-100 text-xs font-sans"
            >
              Download Excel
            </a>
          </div>
        )}
        {d.closure_path && <div className="truncate">📝 {d.closure_path}</div>}
      </div>

      {/* YAML preview */}
      {d.yaml_content && (
        <Expandable label="attempt YAML">
          <pre className="text-xs bg-neutral-900 rounded p-2 overflow-x-auto max-h-48 text-neutral-300 whitespace-pre-wrap">
            {d.yaml_content}
          </pre>
        </Expandable>
      )}

      {/* Closure note */}
      {d.closure_content && (
        <Expandable label="closure note">
          <pre className="text-xs bg-neutral-900 rounded p-2 overflow-x-auto max-h-48 text-neutral-300 whitespace-pre-wrap">
            {d.closure_content}
          </pre>
        </Expandable>
      )}

      {/* SOP sections */}
      {(d.sop_sections_invoked ?? []).length > 0 && (
        <div className="flex flex-wrap gap-1">
          {(d.sop_sections_invoked as string[]).map(s => (
            <span key={s} className="text-xs px-1.5 py-0.5 rounded bg-emerald-900/40 text-emerald-300">
              ✓ {s}
            </span>
          ))}
        </div>
      )}

      {/* Time expansion summary */}
      {d.time_window_base && d.time_window_expanded && d.time_window_base !== d.time_window_expanded && (
        <div className="flex items-center gap-1.5 text-xs">
          <Clock className="h-3 w-3 text-neutral-500 shrink-0" />
          <span className="text-neutral-500 font-mono">{d.time_window_base}</span>
          <span className="text-neutral-600">→</span>
          <span className="text-cyan-400 font-mono">{d.time_window_expanded}</span>
        </div>
      )}
    </div>
  );
}

// ── Rate limit retry card ─────────────────────────────────────────────────────
function RateLimitRetryCard({ d }: { d: any }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <Loader2 className="h-3 w-3 animate-spin text-yellow-400 shrink-0" />
      <span className="text-yellow-300 font-medium">Rate limit hit</span>
      <span className="text-neutral-400">— switching to combo {d.attempt + 1} of {d.total}</span>
      {d.failed_combo && (
        <span className="text-neutral-500 font-mono truncate max-w-[160px]">({d.failed_combo})</span>
      )}
    </div>
  );
}

// ── Rate limit exhausted card ─────────────────────────────────────────────────
function RateLimitExhaustedCard({ d }: { d: any }) {
  return (
    <div className="rounded-lg bg-red-950/60 border border-red-700/50 p-3 space-y-2">
      <div className="flex items-center gap-2">
        <AlertTriangle className="h-4 w-4 text-red-400 shrink-0" />
        <span className="text-red-300 font-semibold text-xs">All {d.total} key + model combos exhausted</span>
      </div>
      <p className="text-xs text-neutral-400 leading-relaxed">
        Every free-tier key has hit its daily quota. The agent has stopped.
      </p>
      <p className="text-xs text-yellow-300 font-medium">
        ⟳ Please refresh the page and try again after quota resets (midnight PT), or add a paid API key.
      </p>
    </div>
  );
}

// ── Workflow initialized card ─────────────────────────────────────────────────
function WorkflowInitializedCard({ d }: { d: any }) {
  const thresholds = d.thresholds ?? {};
  const paramRanges = d.parameter_ranges ?? {};
  return (
    <div className="space-y-2">
      {d.investigation_type && (
        <span className="text-xs px-2 py-0.5 rounded bg-blue-900/40 text-blue-300 font-mono">
          type: {d.investigation_type}
        </span>
      )}
      {Object.keys(thresholds).length > 0 && (
        <Expandable label="Base thresholds">
          <div className="space-y-0.5">
            {Object.entries(thresholds).map(([k, v]) => (
              <div key={k} className="flex justify-between text-xs gap-4">
                <span className="text-neutral-500 font-mono">{k}</span>
                <span className="text-neutral-300 font-mono">{String(v)}</span>
              </div>
            ))}
          </div>
        </Expandable>
      )}
      {Object.keys(paramRanges).length > 0 && (
        <Expandable label="Parameter ranges (adaptive bounds)">
          <div className="space-y-1">
            {Object.entries(paramRanges).map(([k, r]: [string, any]) => (
              <div key={k} className="text-xs flex gap-1">
                <span className="text-neutral-400 font-mono shrink-0">{k}:</span>
                <span className="text-neutral-500">[{r.min}–{r.max}]</span>
                <span className="text-neutral-500">base:</span>
                <span className="text-cyan-300 font-mono">{r.base}</span>
              </div>
            ))}
          </div>
        </Expandable>
      )}
    </div>
  );
}

// ── Workflow updated card ─────────────────────────────────────────────────────
function WorkflowUpdatedCard({ d }: { d: any }) {
  const thresholds = d.thresholds ?? {};
  const rules: string[] = d.last_expansion_rules_fired ?? [];
  const expanded: string = d.last_time_window_expanded ?? '';
  return (
    <div className="space-y-2">
      {expanded && (
        <div className="flex items-center gap-1.5 text-xs">
          <Clock className="h-3 w-3 text-cyan-500 shrink-0" />
          <span className="text-neutral-500">window expanded →</span>
          <span className="text-cyan-400 font-mono">{expanded}</span>
        </div>
      )}
      {rules.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {rules.map((r: string) => (
            <span key={r} className="text-xs px-1.5 py-0.5 rounded bg-orange-900/40 text-orange-300">
              {r}
            </span>
          ))}
        </div>
      )}
      {Object.keys(thresholds).length > 0 && (
        <Expandable label="Updated thresholds (now active for next cycle)">
          <div className="space-y-0.5">
            {Object.entries(thresholds).map(([k, v]) => (
              <div key={k} className="flex justify-between text-xs gap-4">
                <span className="text-neutral-500 font-mono">{k}</span>
                <span className="text-cyan-300 font-mono font-semibold">{String(v)}</span>
              </div>
            ))}
          </div>
        </Expandable>
      )}
    </div>
  );
}

// ── Minimal YAML serialiser (no external dependency) ─────────────────────────
function toYaml(value: any, indent = 0): string {
  const pad = " ".repeat(indent);

  if (value === null || value === undefined) return "~";

  if (typeof value === "boolean") return value ? "true" : "false";

  if (typeof value === "number") return String(value);

  if (typeof value === "string") {
    // Quote strings that contain YAML-special chars or are empty
    if (
      value === "" ||
      /[:#\[\]{},&*?|<>=!%@`\n\r]/.test(value) ||
      /^[-?:]/.test(value) ||
      value.includes("'")
    ) {
      return `"${value.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
    }
    return value;
  }

  if (Array.isArray(value)) {
    if (value.length === 0) return "[]";
    return value
      .map((item) => {
        if (typeof item === "object" && item !== null && !Array.isArray(item)) {
          // Inline first key on the dash line, rest indented
          const entries = Object.entries(item);
          if (entries.length === 0) return `${pad}- {}`;
          const [firstKey, firstVal] = entries[0];
          const firstLine = `${pad}- ${firstKey}: ${toYaml(firstVal, indent + 2)}`;
          const rest = entries
            .slice(1)
            .map(([k, v]) => `${pad}  ${k}: ${toYaml(v, indent + 2)}`)
            .join("\n");
          return rest ? `${firstLine}\n${rest}` : firstLine;
        }
        return `${pad}- ${toYaml(item, indent + 2)}`;
      })
      .join("\n");
  }

  if (typeof value === "object") {
    const entries = Object.entries(value);
    if (entries.length === 0) return "{}";
    return entries
      .map(([k, v]) => {
        if (typeof v === "object" && v !== null) {
          const nested = toYaml(v, indent + 2);
          // Arrays and objects get a newline after the key
          return `${pad}${k}:\n${nested}`;
        }
        return `${pad}${k}: ${toYaml(v, indent + 2)}`;
      })
      .join("\n");
  }

  return String(value);
}

/** Serialize the plan object as a top-level YAML document */
function planToYaml(plan: any): string {
  // Strip the internal `type` key added by the SSE parser before serialising
  const { type: _type, ...rest } = plan ?? {};
  return toYaml(rest, 0);
}

// ── Agentic investigation plan card ──────────────────────────────────────────
function AgenticPlanCard({ d }: { d: any }) {
  const tw = d.time_window ?? {};
  const params = d.parameters ?? {};
  const tools: any[] = d.tools_sequence ?? [];
  const sections: string[] = d.sop_sections ?? [];
  const rules: string[] = tw.rules_applied ?? [];
  const queries: string[] = d.follow_up_queries_addressed ?? [];

  return (
    <div className="space-y-2">
      {/* Time window */}
      {tw.base && (
        <div className="flex items-center gap-1.5 text-xs">
          <Clock className="h-3 w-3 text-neutral-500 shrink-0" />
          <span className="text-neutral-500 font-mono">{tw.base}</span>
          {tw.expanded && tw.expanded !== tw.base && (
            <>
              <span className="text-neutral-600">→</span>
              <span className="text-cyan-400 font-mono">{tw.expanded}</span>
            </>
          )}
        </div>
      )}
      {tw.expansion_reason && (
        <p className="text-xs text-neutral-500 italic ml-4">{tw.expansion_reason}</p>
      )}

      {/* Expansion rules applied */}
      {rules.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {rules.map((r: string) => (
            <span key={r} className="text-xs px-1.5 py-0.5 rounded bg-orange-900/40 text-orange-300">
              {r}
            </span>
          ))}
        </div>
      )}

      {/* Parameters */}
      {Object.keys(params).length > 0 && (
        <Expandable label="Parameters to use">
          <div className="space-y-0.5">
            {Object.entries(params).map(([k, v]) => (
              <div key={k} className="flex justify-between text-xs gap-4">
                <span className="text-neutral-500 font-mono">{k}</span>
                <span className="text-cyan-300 font-mono">{String(v)}</span>
              </div>
            ))}
          </div>
        </Expandable>
      )}

      {/* Tools sequence */}
      {tools.length > 0 && (
        <Expandable label={`${tools.length} tools planned`}>
          <div className="space-y-1">
            {tools.map((t: any, i: number) => (
              <div key={i} className="text-xs flex gap-2">
                <span className="text-neutral-500 shrink-0">{i + 1}.</span>
                <span className="text-emerald-400 font-mono shrink-0">{t.tool}</span>
                <span className="text-neutral-400">{t.reason}</span>
              </div>
            ))}
          </div>
        </Expandable>
      )}

      {/* SOP sections */}
      {sections.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {sections.map((s: string) => (
            <span key={s} className="text-xs px-1.5 py-0.5 rounded bg-emerald-900/40 text-emerald-300">
              ✓ {s}
            </span>
          ))}
        </div>
      )}

      {/* Follow-up queries being addressed */}
      {queries.length > 0 && (
        <Expandable label={`${queries.length} follow-up queries addressed`}>
          <ul className="space-y-1">
            {queries.map((q: string, i: number) => (
              <li key={i} className="text-xs text-neutral-400 flex gap-1">
                <span className="text-neutral-500 shrink-0">{i + 1}.</span>{q}
              </li>
            ))}
          </ul>
        </Expandable>
      )}

      {/* ── YAML view of the full plan ── */}
      <Expandable label="plan YAML">
        <pre className="text-xs bg-neutral-900 rounded p-2 overflow-x-auto max-h-64 text-neutral-300 whitespace-pre leading-relaxed">
          {planToYaml(d)}
        </pre>
      </Expandable>
    </div>
  );
}

// ── Structured plan card (prose + goals + YAML) ──────────────────────────────
const TAG_COLORS: Record<string, string> = {
  ORDERS:    "bg-blue-900/50 text-blue-300 border border-blue-800/50",
  TRADES:    "bg-emerald-900/50 text-emerald-300 border border-emerald-800/50",
  MARKET:    "bg-cyan-900/50 text-cyan-300 border border-cyan-800/50",
  COMMS:     "bg-purple-900/50 text-purple-300 border border-purple-800/50",
  SYNTHESIS: "bg-orange-900/50 text-orange-300 border border-orange-800/50",
};

function PlanStructuredCard({ d }: { d: any }) {
  const goals: any[] = d.investigation_goals ?? [];

  return (
    <div className="space-y-3">
      {/* Entity / symbol / window chips */}
      {(d.entity_id || d.symbol || d.time_window) && (
        <div className="flex flex-wrap items-center gap-1.5">
          {d.entity_id && (
            <span className="text-xs px-2 py-0.5 rounded bg-neutral-700 text-neutral-200 font-mono font-semibold">
              {d.entity_id}
            </span>
          )}
          {d.symbol && (
            <span className="text-xs px-2 py-0.5 rounded bg-neutral-700 text-neutral-200 font-mono">
              {d.symbol}
            </span>
          )}
          {d.time_window && (
            <div className="flex items-center gap-1 text-xs text-neutral-400">
              <Clock className="h-3 w-3 text-neutral-500 shrink-0" />
              <span className="font-mono">{d.time_window}</span>
            </div>
          )}
        </div>
      )}

      {/* Prose — always visible */}
      {d.prose && (
        <div className="text-xs text-neutral-300 leading-relaxed">
          <ReactMarkdown
            components={{
              p: ({ children }) => <p className="mb-1">{children}</p>,
              strong: ({ children }) => <strong className="text-neutral-100">{children}</strong>,
              li: ({ children }) => <li className="ml-3 list-disc">{children}</li>,
              ol: ({ children }) => <ol className="space-y-0.5">{children}</ol>,
            }}
          >
            {d.prose}
          </ReactMarkdown>
        </div>
      )}

      {/* Structured goals */}
      {goals.length > 0 && (
        <Expandable label="Structured goals">
          <div className="space-y-1.5">
            {goals.map((g: any, i: number) => (
              <div key={i} className="text-xs flex gap-2 items-start">
                <span className="text-neutral-500 shrink-0 w-4">{g.step ?? i + 1}.</span>
                <span className={`px-1.5 py-0.5 rounded text-xs shrink-0 font-mono ${TAG_COLORS[g.tag] ?? "bg-neutral-700 text-neutral-400"}`}>
                  {g.tag}
                </span>
                <div>
                  <span className="text-neutral-100 font-medium">{g.action}</span>
                  {g.description && (
                    <span className="text-neutral-400 ml-1">{g.description}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Expandable>
      )}

      {/* YAML view */}
      <Expandable label="plan YAML">
        <pre className="text-xs bg-neutral-900 rounded p-2 overflow-x-auto max-h-64 text-neutral-300 whitespace-pre leading-relaxed">
          {planToYaml(d)}
        </pre>
      </Expandable>
    </div>
  );
}

// ── Plan generating spinner ───────────────────────────────────────────────────
function PlanGeneratingCard() {
  return (
    <div className="flex items-center gap-2 text-xs text-neutral-400">
      <Loader2 className="h-3 w-3 animate-spin text-blue-400" />
      <span>Calling plan generator agent…</span>
    </div>
  );
}

// ── Plan generated card ───────────────────────────────────────────────────────
function PlanGeneratedCard({ d }: { d: any }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="space-y-1">
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1 text-xs text-neutral-400 hover:text-neutral-200 transition-colors"
      >
        <ChevronRight className={`h-3 w-3 transition-transform ${open ? "rotate-90" : ""}`} />
        View full plan
      </button>
      {open && (
        <div className="ml-4 text-xs text-neutral-300 leading-relaxed space-y-1">
          <ReactMarkdown
            components={{
              p: ({ children }) => <p className="mb-1">{children}</p>,
              strong: ({ children }) => <strong className="text-neutral-100">{children}</strong>,
              li: ({ children }) => <li className="ml-3 list-disc">{children}</li>,
            }}
          >
            {d.plan}
          </ReactMarkdown>
        </div>
      )}
    </div>
  );
}

// ── Rich event content dispatcher ─────────────────────────────────────────────
function RichEventContent({ data }: { data: any }) {
  switch (data?.type) {
    case "rate_limit_retry":      return <RateLimitRetryCard d={data} />;
    case "rate_limit_exhausted":  return <RateLimitExhaustedCard d={data} />;
    case "plan_generating":       return <PlanGeneratingCard />;
    case "plan_structured":       return <PlanStructuredCard d={data} />;
    case "plan_generated":        return <PlanGeneratedCard d={data} />;
    case "investigator_result":   return <InvestigatorCard d={data} />;
    case "escalation_score":      return <EscalationScoreCard d={data} />;
    case "escalation_check":      return <EscalationCheckCard d={data} />;
    case "sop_invoked":           return <SopCard d={data} />;
    case "artifact_written":      return <ArtifactCard d={data} />;
    case "workflow_initialized":  return <WorkflowInitializedCard d={data} />;
    case "workflow_updated":      return <WorkflowUpdatedCard d={data} />;
    case "agentic_plan":          return <AgenticPlanCard d={data} />;
    default:                      return null;
  }
}

// ── Is this a rich surveillance event? ───────────────────────────────────────
const RICH_TYPES = new Set([
  "rate_limit_retry", "rate_limit_exhausted",
  "plan_generating", "plan_generated", "plan_structured",
  "investigator_result", "escalation_score", "escalation_check",
  "sop_invoked", "artifact_written",
  "workflow_initialized", "workflow_updated",
  "agentic_plan",
]);

function isRichEvent(data: any): boolean {
  return typeof data === "object" && data !== null && RICH_TYPES.has(data.type);
}

function isJsonData(data: any): boolean {
  if (isRichEvent(data)) return false;
  if (typeof data === "object" && data !== null && data.type) {
    if (data.type === "sources") return false;
    return data.type === "functionCall" || data.type === "functionResponse";
  }
  if (typeof data === "string") {
    try { JSON.parse(data); return true; } catch { return false; }
  }
  return typeof data === "object" && data !== null;
}

function formatEventData(data: any): string {
  if (typeof data === "object" && data !== null && data.type) {
    switch (data.type) {
      case "functionCall":
        return `Calling: ${data.name}\n${JSON.stringify(data.args, null, 2)}`;
      case "functionResponse":
        return `${data.name} response:\n${JSON.stringify(data.response, null, 2)}`;
      case "text":
        return data.content;
      case "sources": {
        const s = data.content as Record<string, { title: string; url: string }>;
        return Object.keys(s).length === 0
          ? "No sources found."
          : Object.values(s).map(src => `[${src.title ?? "Source"}](${src.url})`).join(", ");
      }
      default:
        return JSON.stringify(data, null, 2);
    }
  }
  if (typeof data === "string") {
    try { return JSON.stringify(JSON.parse(data), null, 2); } catch { return data; }
  }
  if (Array.isArray(data)) return data.join(", ");
  if (typeof data === "object" && data !== null) return JSON.stringify(data, null, 2);
  return String(data);
}

function getEventIcon(data: any, title: string, index: number, isLoading: boolean, totalEvents: number) {
  if (index === 0 && isLoading && totalEvents === 0) {
    return <Loader2 className="h-4 w-4 text-neutral-400 animate-spin" />;
  }
  if (data?.type === "investigator_result") {
    const agent = data.agent ?? "";
    if (agent === "orders_investigator")      return <Search className="h-4 w-4 text-blue-300" />;
    if (agent === "trades_investigator")      return <TrendingUp className="h-4 w-4 text-emerald-400" />;
    if (agent === "market_data_investigator") return <BarChart2 className="h-4 w-4 text-cyan-400" />;
    if (agent === "comms_investigator")       return <MessageSquare className="h-4 w-4 text-purple-400" />;
  }
  if (data?.type === "rate_limit_retry")     return <Loader2 className="h-4 w-4 text-yellow-400 animate-spin" />;
  if (data?.type === "rate_limit_exhausted") return <AlertTriangle className="h-4 w-4 text-red-400" />;
  if (data?.type === "plan_generating")   return <Loader2 className="h-4 w-4 text-blue-400 animate-spin" />;
  if (data?.type === "plan_structured")   return <Brain className="h-4 w-4 text-blue-300" />;
  if (data?.type === "plan_generated")    return <Brain className="h-4 w-4 text-blue-300" />;
  if (data?.type === "escalation_score")  return <AlertTriangle className="h-4 w-4 text-orange-400" />;
  if (data?.type === "escalation_check") {
    return data.decision === "ESCALATE"
      ? <AlertTriangle className="h-4 w-4 text-red-400" />
      : <Search className="h-4 w-4 text-blue-400" />;
  }
  if (data?.type === "sop_invoked")          return <Shield className="h-4 w-4 text-emerald-400" />;
  if (data?.type === "artifact_written")     return <FileText className="h-4 w-4 text-purple-400" />;
  if (data?.type === "workflow_initialized") return <Activity className="h-4 w-4 text-blue-400" />;
  if (data?.type === "workflow_updated")     return <TrendingUp className="h-4 w-4 text-cyan-400" />;
  if (data?.type === "agentic_plan")         return <Brain className="h-4 w-4 text-purple-400" />;

  const t = title.toLowerCase();
  if (t.includes("function call"))       return <Activity className="h-4 w-4 text-blue-400" />;
  if (t.includes("function response"))   return <Activity className="h-4 w-4 text-green-400" />;
  if (t.includes("escalation"))          return <AlertTriangle className="h-4 w-4 text-orange-400" />;
  if (t.includes("evidence"))            return <FileText className="h-4 w-4 text-purple-400" />;
  if (t.includes("investigat"))          return <Search className="h-4 w-4 text-blue-300" />;
  if (t.includes("market data"))         return <BarChart2 className="h-4 w-4 text-cyan-400" />;
  if (t.includes("surveillance"))        return <Shield className="h-4 w-4 text-emerald-400" />;
  if (t.includes("thinking"))            return <Loader2 className="h-4 w-4 text-neutral-400 animate-spin" />;
  if (t.includes("planning"))            return <Brain className="h-4 w-4 text-neutral-400" />;
  if (t.includes("retrieved sources"))   return <Link className="h-4 w-4 text-yellow-400" />;
  return <Activity className="h-4 w-4 text-neutral-400" />;
}

export function ActivityTimeline({
  processedEvents,
  isLoading,
  websiteCount,
}: ActivityTimelineProps) {
  const [isTimelineCollapsed, setIsTimelineCollapsed] = useState<boolean>(false);

  useEffect(() => {
    if (!isLoading && processedEvents.length !== 0) {
      setIsTimelineCollapsed(true);
    }
  }, [isLoading, processedEvents]);

  return (
    <Card className={`border-none rounded-lg bg-neutral-700 ${isTimelineCollapsed ? "h-10 py-2" : "max-h-[32rem] py-2"}`}>
      <CardHeader className="py-0">
        <CardDescription className="flex items-center justify-between">
          <div
            className="flex items-center justify-start text-sm w-full cursor-pointer gap-2 text-neutral-100"
            onClick={() => setIsTimelineCollapsed(!isTimelineCollapsed)}
          >
            <span>Investigation Activity</span>
            {websiteCount > 0 && (
              <span className="text-xs bg-neutral-600 px-2 py-0.5 rounded-full">
                {websiteCount} data checks
              </span>
            )}
            {isTimelineCollapsed
              ? <ChevronDown className="h-4 w-4 mr-2" />
              : <ChevronUp className="h-4 w-4 mr-2" />}
          </div>
        </CardDescription>
      </CardHeader>

      {!isTimelineCollapsed && (
        <ScrollArea className="max-h-[28rem] overflow-y-auto">
          <CardContent>
            {/* Initial spinner */}
            {isLoading && processedEvents.length === 0 && (
              <div className="flex flex-col items-center justify-center py-10 gap-4">
                <span className="relative flex h-8 w-8">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-60" />
                  <span className="relative inline-flex rounded-full h-8 w-8 bg-blue-600 items-center justify-center">
                    <Loader2 className="h-4 w-4 text-white animate-spin" />
                  </span>
                </span>
                <div className="text-center">
                  <p className="text-sm text-blue-400 font-semibold">Agents initialising</p>
                  <p className="text-xs text-neutral-500 mt-1">Investigation pipeline starting up…</p>
                </div>
              </div>
            )}

            {processedEvents.length > 0 && (
              <div className="space-y-0">
                {processedEvents.map((eventItem, index) => (
                  <div key={index} className="relative pl-8 pb-4">
                    {(index < processedEvents.length - 1 || (isLoading && index === processedEvents.length - 1)) && (
                      <div className="absolute left-3 top-3.5 h-full w-0.5 bg-neutral-600" />
                    )}
                    <div className="absolute left-0.5 top-2 h-6 w-6 rounded-full bg-neutral-600 flex items-center justify-center ring-4 ring-neutral-700">
                      {getEventIcon(eventItem.data, eventItem.title, index, isLoading, processedEvents.length)}
                    </div>

                    <div>
                      <p className="text-sm text-neutral-200 font-medium mb-1">
                        {eventItem.title}
                      </p>

                      <div className="text-xs text-neutral-300 leading-relaxed">
                        {isRichEvent(eventItem.data) ? (
                          <RichEventContent data={eventItem.data} />
                        ) : isJsonData(eventItem.data) ? (
                          <pre className="bg-neutral-800 p-2 rounded text-xs overflow-x-auto whitespace-pre-wrap max-h-40">
                            {formatEventData(eventItem.data)}
                          </pre>
                        ) : (
                          <ReactMarkdown
                            components={{
                              p: ({ children }) => <span>{children}</span>,
                              a: ({ href, children }) => (
                                <a href={href} target="_blank" rel="noopener noreferrer"
                                  className="text-blue-400 hover:text-blue-300 underline">
                                  {children}
                                </a>
                              ),
                              code: ({ children }) => (
                                <code className="bg-neutral-800 px-1 py-0.5 rounded text-xs">{children}</code>
                              ),
                            }}
                          >
                            {formatEventData(eventItem.data)}
                          </ReactMarkdown>
                        )}
                      </div>
                    </div>
                  </div>
                ))}

                {isLoading && processedEvents.length > 0 && (
                  <div className="relative pl-8 pb-4">
                    {/* Pulsing connector dot */}
                    <div className="absolute left-0.5 top-3 flex items-center justify-center">
                      <span className="relative flex h-5 w-5">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75" />
                        <span className="relative inline-flex rounded-full h-5 w-5 bg-blue-500 items-center justify-center">
                          <Loader2 className="h-3 w-3 text-white animate-spin" />
                        </span>
                      </span>
                    </div>
                    <div className="flex items-center gap-2 mt-0.5">
                      <p className="text-sm text-blue-400 font-semibold">Agent working</p>
                      <span className="flex gap-0.5">
                        <span className="h-1.5 w-1.5 rounded-full bg-blue-400 animate-bounce" style={{ animationDelay: "0ms" }} />
                        <span className="h-1.5 w-1.5 rounded-full bg-blue-400 animate-bounce" style={{ animationDelay: "150ms" }} />
                        <span className="h-1.5 w-1.5 rounded-full bg-blue-400 animate-bounce" style={{ animationDelay: "300ms" }} />
                      </span>
                    </div>
                    <p className="text-xs text-neutral-500 mt-0.5">Processing — new events will appear above</p>
                  </div>
                )}
              </div>
            )}

            {processedEvents.length === 0 && !isLoading && (
              <div className="flex flex-col items-center justify-center h-full text-neutral-500 pt-10">
                <Info className="h-6 w-6 mb-3" />
                <p className="text-sm">No activity to display.</p>
                <p className="text-xs text-neutral-600 mt-1">Timeline will update during processing.</p>
              </div>
            )}
          </CardContent>
        </ScrollArea>
      )}
    </Card>
  );
}
