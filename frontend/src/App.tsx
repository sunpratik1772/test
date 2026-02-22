import { useState, useRef, useCallback, useEffect } from "react";
import { v4 as uuidv4 } from 'uuid';
import { WelcomeScreen } from "@/components/WelcomeScreen";
import { ChatMessagesView } from "@/components/ChatMessagesView";

// Update DisplayData to be a string type
type DisplayData = string | null;
interface MessageWithAgent {
  type: "human" | "ai";
  content: string;
  id: string;
  agent?: string;
  finalReportWithCitations?: boolean;
}


interface ProcessedEvent {
  title: string;
  data: any;
}

export default function App() {
  const [userId, setUserId] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [appName, setAppName] = useState<string | null>(null);
  const [messages, setMessages] = useState<MessageWithAgent[]>([]);
  const [displayData, setDisplayData] = useState<DisplayData | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [messageEvents, setMessageEvents] = useState<Map<string, ProcessedEvent[]>>(new Map());
  const [websiteCount, setWebsiteCount] = useState<number>(0);
  const [xlsxPath, setXlsxPath] = useState<string | null>(null);
  const [isBackendReady, setIsBackendReady] = useState(false);
  const [isCheckingBackend, setIsCheckingBackend] = useState(true);
  const currentAgentRef = useRef('');
  const accumulatedTextRef = useRef("");
  const currentAiMessageIdRef = useRef<string | null>(null);
  const finalReportMessageIdRef = useRef<string | null>(null);
  const seenRateLimitTsRef = useRef<number>(0);
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const activeWorkflowInitializedRef = useRef(false);

  // Poll rate-limit status while a request is in flight
  useEffect(() => {
    if (!isLoading) return;
    const interval = setInterval(async () => {
      try {
        const res = await fetch('/api/rate-limit-status');
        if (!res.ok) return;
        const data = await res.json();
        const msgId = currentAiMessageIdRef.current;
        if (!msgId) return;
        for (const ev of (data.events as any[])) {
          if (ev.ts <= seenRateLimitTsRef.current) continue;
          seenRateLimitTsRef.current = ev.ts;
          if (ev.type === 'retry') {
            addTimelineEvent(msgId, `Rate limit — trying combo ${ev.attempt + 1} of ${ev.total}`, {
              type: 'rate_limit_retry',
              attempt: ev.attempt,
              total: ev.total,
              failed_combo: ev.failed_combo,
            });
          } else if (ev.type === 'exhausted') {
            addTimelineEvent(msgId, 'All quotas exhausted — please refresh', {
              type: 'rate_limit_exhausted',
              total: ev.total,
              failed: ev.failed,
            });
          }
        }
      } catch { /* ignore */ }
    }, 600);
    return () => clearInterval(interval);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoading]);

  const retryWithBackoff = async (
    fn: () => Promise<any>,
    maxRetries: number = 10,
    maxDuration: number = 120000 // 2 minutes
  ): Promise<any> => {
    const startTime = Date.now();
    let lastError: Error;
    
    for (let attempt = 0; attempt < maxRetries; attempt++) {
      if (Date.now() - startTime > maxDuration) {
        throw new Error(`Retry timeout after ${maxDuration}ms`);
      }
      
      try {
        return await fn();
      } catch (error) {
        lastError = error as Error;
        const delay = Math.min(1000 * Math.pow(2, attempt), 5000); // Exponential backoff, max 5s
        console.log(`Attempt ${attempt + 1} failed, retrying in ${delay}ms...`, error);
        await new Promise(resolve => setTimeout(resolve, delay));
      }
    }
    
    throw lastError!;
  };

  const createSession = async (): Promise<{userId: string, sessionId: string, appName: string}> => {
    const generatedSessionId = uuidv4();
    const response = await fetch(`/api/apps/app/users/u_999/sessions/${generatedSessionId}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      }
    });
    
    if (!response.ok) {
      throw new Error(`Failed to create session: ${response.status} ${response.statusText}`);
    }
    
    const data = await response.json();
    return {
      userId: data.userId,
      sessionId: data.id,
      appName: data.appName
    };
  };

  const checkBackendHealth = async (): Promise<boolean> => {
    try {
      // Use the docs endpoint or root endpoint to check if backend is ready
      const response = await fetch("/api/docs", {
        method: "GET",
        headers: {
          "Content-Type": "application/json"
        }
      });
      return response.ok;
    } catch (error) {
      console.log("Backend not ready yet:", error);
      return false;
    }
  };

  // Attempt to parse a JSON string; strips markdown code fences if present.
  const tryParseJson = (s: string): any | null => {
    try { return JSON.parse(s); } catch { /* fall through to fence-strip */ }
    try {
      const stripped = s.replace(/^```(?:json)?\s*/m, '').replace(/\s*```\s*$/m, '').trim();
      return JSON.parse(stripped);
    } catch { return null; }
  };

  // Parse numbered-list prose from fx_plan_generator into structured goals
  const parsePlanGoals = (text: string): any[] => {
    const re = /^\s*\d+\.\s+\*\*(\w+)\*\*\s+(.+?)\s*\[([A-Z]+)\](?:\s*:\s*(.+))?/gm;
    const goals: any[] = [];
    let m: RegExpExecArray | null;
    let step = 1;
    while ((m = re.exec(text)) !== null) {
      goals.push({
        step,
        action: m[1],
        description: m[4] ? `${m[2]}: ${m[4].trim()}` : m[2].trim(),
        tag: m[3],
      });
      step++;
    }
    return goals;
  };

  // Build a rich investigator_result event from a parallel investigator's JSON output
  const buildInvestigatorEvent = (agentName: string, raw: any): any => {
    const labelMap: Record<string, string> = {
      orders_investigator: 'Orders',
      trades_investigator: 'Trades',
      market_data_investigator: 'Market Data',
      comms_investigator: 'Comms',
      data_investigator: 'Data Investigation',
    };
    return {
      type: 'investigator_result',
      agent: agentName,
      label: labelMap[agentName] ?? agentName,
      anomaly_score: Math.max(
        raw.orders_anomaly_score ?? 0,
        raw.trades_anomaly_score ?? 0,
        raw.market_data_anomaly_score ?? 0,
        raw.comms_coordination_score ?? 0,
      ),
      spoofing_flag:       raw.spoofing_flag ?? false,
      layering_count:      (raw.layering_patterns ?? []).length,
      wash_pairs:          (raw.wash_trade_pairs ?? []).length,
      front_run_count:     (raw.front_running_signals ?? []).length,
      keyword_hits:        raw.keyword_hits ?? 0,
      comms_categories:    raw.comms_categories_hit ?? [],
      volume_zscore:       raw.volume_zscore ?? null,
      price_change_pct:    raw.price_change_pct ?? null,
      volume_anomaly_flag: raw.volume_anomaly_flag ?? false,
      spread_widening:     raw.spread_widening_flag ?? false,
      cancel_rate:         raw.cancel_rate ?? null,
      total_orders:        raw.total_orders ?? null,
      total_trades:        raw.total_trades ?? null,
      total_comms:         raw.total_comms ?? null,
    };
  };

  // Function to extract text and metadata from SSE data
  const extractDataFromSSE = (data: string) => {
    try {
      const parsed = JSON.parse(data);

      let textParts: string[] = [];
      let agent = '';
      let finalReportWithCitations = undefined;
      let functionCall = null;
      let functionResponse = null;
      let sources = null;
      let surveillanceEvent: any = null;

      if (parsed.content && parsed.content.parts) {
        textParts = parsed.content.parts
          .filter((part: any) => part.text)
          .map((part: any) => part.text);

        const functionCallPart = parsed.content.parts.find((part: any) => part.functionCall);
        if (functionCallPart) functionCall = functionCallPart.functionCall;

        const functionResponsePart = parsed.content.parts.find((part: any) => part.functionResponse);
        if (functionResponsePart) functionResponse = functionResponsePart.functionResponse;
      }

      if (parsed.author) agent = parsed.author;

      if (parsed.actions?.stateDelta?.final_surveillance_report) {
        const raw: string = parsed.actions.stateDelta.final_surveillance_report;
        // ADK injects state as "For context:[key] said: {...}" — strip those lines
        // and start from the first markdown heading (#)
        const lines = raw.split('\n');
        const firstHeading = lines.findIndex((l: string) => l.startsWith('#'));
        const cleaned = firstHeading >= 0 ? lines.slice(firstHeading).join('\n').trim() : raw.trim();
        if (cleaned) finalReportWithCitations = cleaned;
      }

      // ── Surveillance-specific event extraction ───────────────────────────

      // 1. Parallel investigators — parse JSON output for a rich result card
      const investigatorAgents = [
        'orders_investigator', 'trades_investigator',
        'market_data_investigator', 'comms_investigator',
        'data_investigator', // unified single-agent replacement
      ];
      if (investigatorAgents.includes(agent)) {
        // data_investigator writes to surveillance_findings; legacy agents use <name>_findings
        const deltaKey = agent === 'data_investigator'
          ? 'surveillance_findings'
          : agent.replace('_investigator', '_findings');
        const findings = parsed.actions?.stateDelta?.[deltaKey]
          ?? (textParts[0] ? tryParseJson(textParts[0]) : null);
        if (findings) {
          surveillanceEvent = buildInvestigatorEvent(agent, findings);
          setWebsiteCount(prev => prev + 1);
        }
      }

      // 2. Escalation evaluator — score + reasoning card
      if (agent === 'escalation_evaluator') {
        const sd = parsed.actions?.stateDelta?.escalation_score_data
          ?? (textParts[0] ? tryParseJson(textParts[0]) : null);
        if (sd) {
          const score = sd.score ?? 0;
          surveillanceEvent = {
            type: 'escalation_score',
            score,
            reasoning: sd.reasoning ?? '',
            follow_up_queries: sd.follow_up_queries ?? [],
            decision: score >= 0.80 ? 'ESCALATE'
              : score >= 0.60 ? 'INVESTIGATE_FURTHER' : 'MONITOR',
          };
        }
      }

      // 3. EscalationChecker — threshold decision banner
      if (agent === 'escalation_checker' && textParts[0]) {
        const d = tryParseJson(textParts[0]);
        if (d?.__type === 'escalation_check') {
          surveillanceEvent = { type: 'escalation_check', ...d };
        }
      }

      // 4. Agentic investigator — SOP + refinement card (backward compat)
      if (agent === 'agentic_investigator') {
        const findings = parsed.actions?.stateDelta?.surveillance_findings
          ?? (textParts[0] ? tryParseJson(textParts[0]) : null);
        if (findings?.refined_workflow) {
          surveillanceEvent = { type: 'sop_invoked', ...findings.refined_workflow };
          setWebsiteCount(prev => prev + 1);
        }
      }

      // 4a. Agentic planner — plan card shown before tool calls
      if (agent === 'agentic_planner') {
        const planRaw = parsed.actions?.stateDelta?.agentic_plan;
        const plan = planRaw ? tryParseJson(planRaw) : null;
        if (plan && typeof plan === 'object') {
          surveillanceEvent = { type: 'agentic_plan', ...plan };
        }
      }

      // 4b. Agentic executor — SOP + refinement card (same shape as agentic_investigator)
      if (agent === 'agentic_executor') {
        const findings = parsed.actions?.stateDelta?.surveillance_findings
          ?? (textParts[0] ? tryParseJson(textParts[0]) : null);
        if (findings?.refined_workflow) {
          surveillanceEvent = { type: 'sop_invoked', ...findings.refined_workflow };
          setWebsiteCount(prev => prev + 1);
        }
      }

      // 5. Evidence compiler — artifact_written card with YAML preview
      // Check textParts first (direct callback return), then stateDelta (fallback)
      if (agent === 'evidence_compiler' && textParts[0]) {
        const d = tryParseJson(textParts[0]);
        if (d?.__type === 'artifact_written') {
          surveillanceEvent = { type: 'artifact_written', ...d };
        }
      }
      // Fallback: detect artifact from stateDelta.last_artifact_paths (any agent)
      if (!surveillanceEvent && parsed.actions?.stateDelta?.last_artifact_paths) {
        const paths = parsed.actions.stateDelta.last_artifact_paths;
        const scoreData = parsed.actions?.stateDelta?.escalation_score_data;
        const score = typeof scoreData === 'number' ? scoreData
          : (scoreData?.score ?? 0);
        const attempt = parsed.actions?.stateDelta?.current_attempt ?? '?';
        surveillanceEvent = {
          type: 'artifact_written',
          attempt_n: attempt,
          score,
          decision: score >= 0.80 ? 'ESCALATE' : score >= 0.60 ? 'INVESTIGATE_FURTHER' : 'MONITOR',
          xlsx_path: paths.xlsx_path ?? '',
          yaml_path: paths.yaml_path ?? '',
          closure_path: paths.closure_path ?? '',
        };
      }

      // Legacy sources
      if (parsed.actions?.stateDelta?.sources) {
        sources = parsed.actions.stateDelta.sources;
      }

      // ── active_workflow state delta ──────────────────────────────────────
      const activeWorkflowDelta = parsed.actions?.stateDelta?.active_workflow ?? null;

      return {
        textParts, agent, finalReportWithCitations,
        functionCall, functionResponse, sourceCount: 0, sources,
        surveillanceEvent, activeWorkflowDelta,
      };
    } catch (error) {
      const truncatedData = data.length > 200 ? data.substring(0, 200) + "..." : data;
      console.error('Error parsing SSE data:', truncatedData, error);
      return {
        textParts: [], agent: '', finalReportWithCitations: undefined,
        functionCall: null, functionResponse: null, sourceCount: 0, sources: null,
        surveillanceEvent: null, activeWorkflowDelta: null,
      };
    }
  };

  // Define getEventTitle here or ensure it's in scope from where it's used
  const getEventTitle = (agentName: string): string => {
    switch (agentName) {
      case "fx_plan_generator":
        return "Planning Investigation Strategy";
      case "orders_investigator":
        return "Investigating Orders (Spoofing / Layering)";
      case "trades_investigator":
        return "Investigating Trades (Wash / Front-Running)";
      case "market_data_investigator":
        return "Analysing Market Data Impact";
      case "comms_investigator":
        return "Reviewing Communications";
      case "parallel_investigators":
        return "Running Parallel Investigators";
      case "data_investigator":
        return "Running Data Investigation (Orders / Trades / Market Data / Comms)";
      case "escalation_evaluator":
        return "Computing Escalation Score";
      case "escalation_checker":
      case "EscalationChecker":
        return "Escalation Check";
      case "agentic_investigator":
        return "Agentic Investigation Cycle";
      case "agentic_planner":
        return "Generating Agentic Investigation Plan";
      case "agentic_executor":
        return "Executing Investigation Plan";
      case "investigation_loop":
        return "Investigation Loop";
      case "evidence_compiler":
        return "Compiling Evidence Report";
      case "surveillance_pipeline":
        return "Executing Surveillance Pipeline";
      case "workflow_initializer_agent":
      case "root_agent":
        return "Surveillance Planning";
      default:
        return `Processing (${agentName || 'Unknown Agent'})`;
    }
  };

  const addTimelineEvent = (aiMessageId: string, title: string, data: any) => {
    setMessageEvents(prev => new Map(prev).set(
      aiMessageId, [...(prev.get(aiMessageId) || []), { title, data }]
    ));
  };

  const processSseEventData = (jsonData: string, aiMessageId: string) => {
    const {
      textParts, agent, finalReportWithCitations,
      functionCall, functionResponse, sources, surveillanceEvent, activeWorkflowDelta,
    } = extractDataFromSSE(jsonData);

    if (agent && agent !== currentAgentRef.current) {
      currentAgentRef.current = agent;
    }

    // ── Function call / response (tool invocations) ───────────────────────
    if (functionCall) {
      if (functionCall.name === 'fx_plan_generator') {
        // Show a clean "generating plan" spinner instead of raw JSON
        addTimelineEvent(aiMessageId, 'Generating Investigation Plan', {
          type: 'plan_generating',
          request: functionCall.args?.request ?? '',
        });
      } else {
        addTimelineEvent(aiMessageId, `Function Call: ${functionCall.name}`, {
          type: 'functionCall', name: functionCall.name,
          args: functionCall.args, id: functionCall.id,
        });
      }
    }
    if (functionResponse) {
      if (functionResponse.name === 'fx_plan_generator') {
        const result = functionResponse.response?.result ?? functionResponse.response;

        // Tier 1: Already a structured object with investigation_goals (output_schema path)
        const asObj: any = typeof result === 'object' && result !== null ? result : null;
        if (asObj && Array.isArray(asObj.investigation_goals)) {
          addTimelineEvent(aiMessageId, 'Investigation Plan Ready', {
            type: 'plan_structured', ...asObj,
          });
        } else {
          // Tier 2: Plain text prose — always try regex parse
          const prose = typeof result === 'string'
            ? result
            : (asObj ? JSON.stringify(asObj, null, 2) : '');
          const goals = parsePlanGoals(prose);

          if (goals.length > 0) {
            // Regex found goals → show structured card (prose visible + YAML)
            addTimelineEvent(aiMessageId, 'Investigation Plan Ready', {
              type: 'plan_structured',
              prose,
              investigation_goals: goals,
            });
          } else {
            // Tier 3: Last resort — raw text fallback (no YAML, no structure)
            addTimelineEvent(aiMessageId, 'Investigation Plan Ready', {
              type: 'plan_generated',
              plan: prose,
            });
          }
        }
      } else {
        addTimelineEvent(aiMessageId, `Function Response: ${functionResponse.name}`, {
          type: 'functionResponse', name: functionResponse.name,
          response: functionResponse.response, id: functionResponse.id,
        });
      }
    }

    // ── Surveillance-specific rich events (take priority over plain text) ──
    const surveillanceAgents = [
      'orders_investigator', 'trades_investigator',
      'market_data_investigator', 'comms_investigator',
      'data_investigator', // unified single-agent replacement
      'escalation_evaluator', 'escalation_checker',
      'agentic_investigator', // kept for backward compat
      'agentic_planner',      // NEW
      'agentic_executor',     // NEW
      'evidence_compiler',
    ];

    if (surveillanceEvent?.type === 'artifact_written' && surveillanceEvent.xlsx_path) {
      setXlsxPath(surveillanceEvent.xlsx_path);
    }

    if (surveillanceEvent) {
      const titleMap: Record<string, string> = {
        investigator_result:   `${surveillanceEvent.label ?? agent} — Findings`,
        escalation_score:      `Escalation Score: ${(surveillanceEvent.score * 100).toFixed(0)}%`,
        escalation_check:      surveillanceEvent.decision === 'ESCALATE'
                                 ? '⬆ Escalating — threshold reached'
                                 : `↩ Continuing loop (attempt ${surveillanceEvent.attempt})`,
        sop_invoked:           `SOP Cycle — Attempt ${surveillanceEvent.attempt}`,
        artifact_written:      `Evidence Package — Attempt ${surveillanceEvent.attempt_n}`,
        workflow_initialized:  'Active Workflow Initialized',
        workflow_updated:      'Workflow Parameters Updated',
        agentic_plan:          `Investigation Plan — Attempt ${surveillanceEvent.attempt}`,
      };
      addTimelineEvent(
        aiMessageId,
        titleMap[surveillanceEvent.type] ?? getEventTitle(agent),
        surveillanceEvent,
      );
    }

    // ── Active workflow delta (independent of surveillanceEvent) ─────────────
    if (activeWorkflowDelta && typeof activeWorkflowDelta === 'object') {
      if (!activeWorkflowInitializedRef.current) {
        activeWorkflowInitializedRef.current = true;
        addTimelineEvent(aiMessageId, 'Active Workflow Initialized', {
          type: 'workflow_initialized',
          investigation_type: activeWorkflowDelta.investigation_type,
          thresholds: activeWorkflowDelta.thresholds,
          parameter_ranges: activeWorkflowDelta.parameter_ranges,
        });
      } else if (
        activeWorkflowDelta.last_time_window_expanded ||
        activeWorkflowDelta.last_expansion_rules_fired?.length
      ) {
        addTimelineEvent(aiMessageId, 'Workflow Parameters Updated', {
          type: 'workflow_updated',
          thresholds: activeWorkflowDelta.thresholds,
          last_time_window_expanded: activeWorkflowDelta.last_time_window_expanded,
          last_expansion_rules_fired: activeWorkflowDelta.last_expansion_rules_fired,
        });
      }
    }

    if (!surveillanceEvent && textParts.length > 0 && !surveillanceAgents.includes(agent)) {
      // Non-surveillance agents — plain text fallback
      if (agent !== 'workflow_initializer_agent') {
        addTimelineEvent(aiMessageId, getEventTitle(agent), {
          type: 'text', content: textParts.join(' '),
        });
      } else {
        for (const text of textParts) {
          accumulatedTextRef.current += text + ' ';
          setMessages(prev => prev.map(msg =>
            msg.id === aiMessageId
              ? { ...msg, content: accumulatedTextRef.current.trim(), agent: currentAgentRef.current || msg.agent }
              : msg
          ));
          setDisplayData(accumulatedTextRef.current.trim());
        }
      }
    } else if (textParts.length > 0 && agent === 'workflow_initializer_agent') {
      for (const text of textParts) {
        accumulatedTextRef.current += text + ' ';
        setMessages(prev => prev.map(msg =>
          msg.id === aiMessageId
            ? { ...msg, content: accumulatedTextRef.current.trim(), agent: currentAgentRef.current || msg.agent }
            : msg
        ));
        setDisplayData(accumulatedTextRef.current.trim());
      }
    }

    if (sources) {
      addTimelineEvent(aiMessageId, 'Retrieved Sources', { type: 'sources', content: sources });
    }

    if (agent === 'evidence_compiler' && finalReportWithCitations) {
      const finalReportMessageId = Date.now().toString() + '_final';
      finalReportMessageIdRef.current = finalReportMessageId;   // ← store for effect
      setMessages(prev => [...prev, {
        type: 'ai', content: finalReportWithCitations as string,
        id: finalReportMessageId, agent: currentAgentRef.current,
        finalReportWithCitations: true,
      }]);
      setDisplayData(finalReportWithCitations as string);
      // Download button will be attached by the xlsxPath useEffect (Fix 3)
      // which fires when the artifact_written SSE event arrives shortly after
    }
  };

  const handleSubmit = useCallback(async (query: string) => {
    if (!query.trim()) return;

    setIsLoading(true);
    try {
      // Create session if it doesn't exist
      let currentUserId = userId;
      let currentSessionId = sessionId;
      let currentAppName = appName;
      
      if (!currentSessionId || !currentUserId || !currentAppName) {
        console.log('Creating new session...');
        const sessionData = await retryWithBackoff(createSession);
        currentUserId = sessionData.userId;
        currentSessionId = sessionData.sessionId;
        currentAppName = sessionData.appName;
        
        setUserId(currentUserId);
        setSessionId(currentSessionId);
        setAppName(currentAppName);
        console.log('Session created successfully:', { currentUserId, currentSessionId, currentAppName });
      }

      // Add user message to chat
      const userMessageId = Date.now().toString();
      setMessages(prev => [...prev, { type: "human", content: query, id: userMessageId }]);

      // Create AI message placeholder
      const aiMessageId = Date.now().toString() + "_ai";
      currentAgentRef.current = ''; // Reset current agent
      currentAiMessageIdRef.current = aiMessageId;
      activeWorkflowInitializedRef.current = false; // Reset for new conversation turn
      seenRateLimitTsRef.current = Date.now() / 1000; // only show events from now on
      // Clear previous rate-limit events on the backend
      fetch('/api/rate-limit-status', { method: 'DELETE' }).catch(() => {});
      accumulatedTextRef.current = ''; // Reset accumulated text

      setMessages(prev => [...prev, {
        type: "ai",
        content: "",
        id: aiMessageId,
        agent: '',
      }]);

      // Send the message with retry logic
      const sendMessage = async () => {
        const response = await fetch("/api/run_sse", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            appName: currentAppName,
            userId: currentUserId,
            sessionId: currentSessionId,
            newMessage: {
              parts: [{ text: query }],
              role: "user"
            },
            streaming: false
          }),
        });

        if (!response.ok) {
          throw new Error(`Failed to send message: ${response.status} ${response.statusText}`);
        }
        
        return response;
      };

      const response = await retryWithBackoff(sendMessage);

      // Handle SSE streaming
      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let lineBuffer = ""; 
      let eventDataBuffer = "";

      if (reader) {
        // eslint-disable-next-line no-constant-condition
        while (true) {
          const { done, value } = await reader.read();

          if (value) {
            lineBuffer += decoder.decode(value, { stream: true });
          }
          
          let eolIndex;
          // Process all complete lines in the buffer, or the remaining buffer if 'done'
          while ((eolIndex = lineBuffer.indexOf('\n')) >= 0 || (done && lineBuffer.length > 0)) {
            let line: string;
            if (eolIndex >= 0) {
              line = lineBuffer.substring(0, eolIndex);
              lineBuffer = lineBuffer.substring(eolIndex + 1);
            } else { // Only if done and lineBuffer has content without a trailing newline
              line = lineBuffer;
              lineBuffer = "";
            }

            if (line.trim() === "") { // Empty line: dispatch event
              if (eventDataBuffer.length > 0) {
                // Remove trailing newline before parsing
                const jsonDataToParse = eventDataBuffer.endsWith('\n') ? eventDataBuffer.slice(0, -1) : eventDataBuffer;
                console.log('[SSE DISPATCH EVENT]:', jsonDataToParse.substring(0, 200) + "..."); // DEBUG
                processSseEventData(jsonDataToParse, aiMessageId);
                eventDataBuffer = ""; // Reset for next event
              }
            } else if (line.startsWith('data:')) {
              eventDataBuffer += line.substring(5).trimStart() + '\n'; // Add newline as per spec for multi-line data
            } else if (line.startsWith(':')) {
              // Comment line, ignore
            } // Other SSE fields (event, id, retry) can be handled here if needed
          }

          if (done) {
            // If the loop exited due to 'done', and there's still data in eventDataBuffer
            // (e.g., stream ended after data lines but before an empty line delimiter)
            if (eventDataBuffer.length > 0) {
              const jsonDataToParse = eventDataBuffer.endsWith('\n') ? eventDataBuffer.slice(0, -1) : eventDataBuffer;
              console.log('[SSE DISPATCH FINAL EVENT]:', jsonDataToParse.substring(0,200) + "..."); // DEBUG
              processSseEventData(jsonDataToParse, aiMessageId);
              eventDataBuffer = ""; // Clear buffer
            }
            break; // Exit the while(true) loop
          }
        }
      }

      setIsLoading(false);

    } catch (error) {
      console.error("Error:", error);
      // Update the AI message placeholder with an error message
      const aiMessageId = Date.now().toString() + "_ai_error";
      setMessages(prev => [...prev, { 
        type: "ai", 
        content: `Sorry, there was an error processing your request: ${error instanceof Error ? error.message : 'Unknown error'}`, 
        id: aiMessageId 
      }]);
      setIsLoading(false);
    }
  }, [processSseEventData]);

  useEffect(() => {
    if (scrollAreaRef.current) {
      const scrollViewport = scrollAreaRef.current.querySelector(
        "[data-radix-scroll-area-viewport]"
      );
      if (scrollViewport) {
        scrollViewport.scrollTop = scrollViewport.scrollHeight;
      }
    }
  }, [messages]);

  // Retroactively attach download button when xlsxPath arrives (race-condition fix)
  useEffect(() => {
    if (!xlsxPath || !finalReportMessageIdRef.current) return;
    const msgId = finalReportMessageIdRef.current;
    setMessageEvents(prev => {
      const existing = prev.get(msgId) ?? [];
      const withoutOld = existing.filter(e => e.data?.type !== 'artifact_written');
      return new Map(prev).set(msgId, [
        ...withoutOld,
        {
          title: 'Download Evidence Package',
          data: { type: 'artifact_written', xlsx_path: xlsxPath, decision: '', score: 0 },
        },
      ]);
    });
  }, [xlsxPath]);

  useEffect(() => {
    const checkBackend = async () => {
      setIsCheckingBackend(true);
      
      // Check if backend is ready with retry logic
      const maxAttempts = 60; // 2 minutes with 2-second intervals
      let attempts = 0;
      
      while (attempts < maxAttempts) {
        const isReady = await checkBackendHealth();
        if (isReady) {
          setIsBackendReady(true);
          setIsCheckingBackend(false);
          return;
        }
        
        attempts++;
        await new Promise(resolve => setTimeout(resolve, 2000)); // Wait 2 seconds between checks
      }
      
      // If we get here, backend didn't come up in time
      setIsCheckingBackend(false);
      console.error("Backend failed to start within 2 minutes");
    };
    
    checkBackend();
  }, []);

  const handleCancel = useCallback(() => {
    setMessages([]);
    setDisplayData(null);
    setMessageEvents(new Map());
    setWebsiteCount(0);
    window.location.reload();
  }, []);


  const BackendLoadingScreen = () => (
    <div className="flex-1 flex flex-col items-center justify-center p-4 overflow-hidden relative">
      <div className="w-full max-w-2xl z-10
                      bg-neutral-900/50 backdrop-blur-md 
                      p-8 rounded-2xl border border-neutral-700 
                      shadow-2xl shadow-black/60">
        
        <div className="text-center space-y-6">
          <h1 className="text-4xl font-bold text-white flex items-center justify-center gap-3">
            FX-FRO Surveillance
          </h1>
          
          <div className="flex flex-col items-center space-y-4">
            {/* Spinning animation */}
            <div className="relative">
              <div className="w-16 h-16 border-4 border-neutral-600 border-t-blue-500 rounded-full animate-spin"></div>
              <div className="absolute inset-0 w-16 h-16 border-4 border-transparent border-r-purple-500 rounded-full animate-spin" style={{animationDirection: 'reverse', animationDuration: '1.5s'}}></div>
            </div>
            
            <div className="space-y-2">
              <p className="text-xl text-neutral-300">
                Waiting for backend to be ready...
              </p>
              <p className="text-sm text-neutral-400">
                This may take a moment on first startup
              </p>
            </div>
            
            {/* Animated dots */}
            <div className="flex space-x-1">
              <div className="w-2 h-2 bg-blue-500 rounded-full animate-bounce" style={{animationDelay: '0ms'}}></div>
              <div className="w-2 h-2 bg-purple-500 rounded-full animate-bounce" style={{animationDelay: '150ms'}}></div>
              <div className="w-2 h-2 bg-pink-500 rounded-full animate-bounce" style={{animationDelay: '300ms'}}></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );

  return (
    <div className="flex h-screen bg-neutral-800 text-neutral-100 font-sans antialiased">
      <main className="flex-1 flex flex-col overflow-hidden w-full">
        <div className={`flex-1 overflow-y-auto ${(messages.length === 0 || isCheckingBackend) ? "flex" : ""}`}>
          {isCheckingBackend ? (
            <BackendLoadingScreen />
          ) : !isBackendReady ? (
            <div className="flex-1 flex flex-col items-center justify-center p-4">
              <div className="text-center space-y-4">
                <h2 className="text-2xl font-bold text-red-400">Backend Unavailable</h2>
                <p className="text-neutral-300">
                  Unable to connect to backend services at localhost:8000
                </p>
                <button 
                  onClick={() => window.location.reload()} 
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors"
                >
                  Retry
                </button>
              </div>
            </div>
          ) : messages.length === 0 ? (
            <WelcomeScreen
              handleSubmit={handleSubmit}
              isLoading={isLoading}
              onCancel={handleCancel}
            />
          ) : (
            <ChatMessagesView
              messages={messages}
              isLoading={isLoading}
              scrollAreaRef={scrollAreaRef}
              onSubmit={handleSubmit}
              onCancel={handleCancel}
              displayData={displayData}
              messageEvents={messageEvents}
              websiteCount={websiteCount}
            />
          )}
        </div>
      </main>
    </div>
  );
}
