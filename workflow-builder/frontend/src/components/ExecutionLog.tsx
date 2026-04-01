import { useWorkflowStore } from '../store/workflowStore';

const STATUS_STYLES: Record<string, string> = {
  running: 'text-yellow-400',
  done:    'text-emerald-400',
  error:   'text-red-400',
};

const STATUS_ICON: Record<string, string> = {
  running: '⏳',
  done:    '✓',
  error:   '✗',
};

export function ExecutionLog() {
  const { executionLog, isRunning, disposition, flagCount } = useWorkflowStore();

  if (executionLog.length === 0 && !isRunning) {
    return (
      <div className="h-28 bg-slate-950 border-t border-slate-800 flex items-center justify-center">
        <p className="text-xs text-slate-700">Execution log will appear here when you run the workflow</p>
      </div>
    );
  }

  return (
    <div className="h-36 bg-slate-950 border-t border-slate-800 flex flex-col">
      <div className="flex items-center gap-3 px-3 py-1.5 border-b border-slate-800 flex-shrink-0">
        <span className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider">Execution Log</span>
        {isRunning && <span className="text-[10px] text-yellow-400 animate-pulse">● running</span>}
        {disposition && (
          <span className="text-[10px] font-bold text-slate-300">
            → <span className={
              disposition === 'ESCALATE' ? 'text-red-400' :
              disposition === 'HUMAN REVIEW' ? 'text-yellow-400' : 'text-emerald-400'
            }>{disposition}</span>
            {flagCount !== null && <span className="text-slate-500 ml-1">({flagCount} flags)</span>}
          </span>
        )}
      </div>
      <div className="flex-1 overflow-y-auto px-3 py-1 font-mono text-[11px] space-y-0.5">
        {executionLog.map((entry, i) => (
          <div key={i} className="flex items-start gap-2">
            <span className="text-slate-600 w-16 flex-shrink-0 tabular-nums">
              {new Date(entry.ts).toISOString().slice(11, 19)}
            </span>
            <span className={STATUS_STYLES[entry.status] ?? 'text-slate-400'}>
              {STATUS_ICON[entry.status]}
            </span>
            <span className="text-slate-400">{entry.label}</span>
            {entry.output && entry.status === 'done' && (
              <span className="text-slate-600 truncate">
                — {Object.entries(entry.output).slice(0,2).map(([k,v]) => `${k}=${String(v).slice(0,20)}`).join(', ')}
              </span>
            )}
            {entry.error && <span className="text-red-500">{entry.error}</span>}
          </div>
        ))}
      </div>
    </div>
  );
}
