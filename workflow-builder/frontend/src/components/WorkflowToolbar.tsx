import { TEMPLATES } from '../templates';
import { useWorkflowStore } from '../store/workflowStore';
import type { Node, Edge } from '@xyflow/react';

interface Props {
  onRun: () => void;
}

const DISPOSITION_COLOURS: Record<string, string> = {
  'CLOSE':        'bg-emerald-500/20 text-emerald-400 border-emerald-500/40',
  'HUMAN REVIEW': 'bg-yellow-500/20 text-yellow-400 border-yellow-500/40',
  'ESCALATE':     'bg-red-500/20 text-red-400 border-red-500/40',
};

export function WorkflowToolbar({ onRun }: Props) {
  const { loadTemplate, clearCanvas, isRunning, nodes, disposition, flagCount } = useWorkflowStore();

  const handleLoadTemplate = (key: keyof typeof TEMPLATES) => {
    const t = TEMPLATES[key];
    loadTemplate(t.template.nodes as Node[], t.template.edges as Edge[]);
  };

  return (
    <header className="h-12 bg-slate-900 border-b border-slate-700 flex items-center px-4 gap-3 flex-shrink-0">
      {/* Brand */}
      <div className="flex items-center gap-2 mr-2">
        <span className="text-lg">🛡️</span>
        <span className="text-sm font-bold text-slate-200">Surveillance</span>
        <span className="text-xs text-slate-500 font-mono">workflow builder</span>
      </div>

      <div className="w-px h-6 bg-slate-700" />

      {/* Templates */}
      <span className="text-xs text-slate-500">Load:</span>
      {Object.entries(TEMPLATES).map(([key, t]) => (
        <button
          key={key}
          onClick={() => handleLoadTemplate(key as keyof typeof TEMPLATES)}
          disabled={isRunning}
          className="px-2.5 py-1 rounded text-xs font-medium border transition-colors disabled:opacity-40"
          style={{
            background: t.colour + '22',
            borderColor: t.colour + '55',
            color: t.colour,
          }}
        >
          {t.label}
        </button>
      ))}

      <div className="w-px h-6 bg-slate-700" />

      {/* Clear */}
      <button
        onClick={clearCanvas}
        disabled={isRunning}
        className="px-2.5 py-1 rounded text-xs font-medium border border-slate-700 text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition-colors disabled:opacity-40"
      >
        Clear
      </button>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Disposition badge */}
      {disposition && (
        <div className={`px-3 py-1 rounded-full text-xs font-semibold border ${DISPOSITION_COLOURS[disposition] ?? 'bg-slate-700 text-slate-300 border-slate-600'}`}>
          {disposition}
          {flagCount !== null && <span className="ml-1.5 opacity-70">{flagCount} flags</span>}
        </div>
      )}

      {/* Run button */}
      <button
        onClick={onRun}
        disabled={isRunning || nodes.length === 0}
        className={`
          px-4 py-1.5 rounded-lg text-xs font-bold transition-all
          ${isRunning
            ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/40 cursor-not-allowed'
            : 'bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-40 disabled:cursor-not-allowed'
          }
        `}
      >
        {isRunning ? '⏳ Running…' : '▶ Run Workflow'}
      </button>
    </header>
  );
}
