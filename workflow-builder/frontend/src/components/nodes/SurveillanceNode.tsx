import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import { useWorkflowStore } from '../../store/workflowStore';

interface NodeData {
  type: string;
  label: string;
  category: string;
  colour: string;
  config: Record<string, unknown>;
}

const STATUS_RING: Record<string, string> = {
  idle:    'ring-transparent',
  running: 'ring-yellow-400 ring-2 animate-pulse',
  done:    'ring-emerald-400 ring-2',
  error:   'ring-red-500 ring-2',
};

const STATUS_DOT: Record<string, string> = {
  idle:    'bg-slate-600',
  running: 'bg-yellow-400 animate-pulse',
  done:    'bg-emerald-400',
  error:   'bg-red-500',
};

const CATEGORY_ICONS: Record<string, string> = {
  trigger:   '⚡',
  collector: '📥',
  extractor: '🔬',
  analyser:  '📊',
  filter:    '🔀',
  output:    '📤',
};

export const SurveillanceNode = memo(({ id, data, selected }: {
  id: string;
  data: NodeData;
  selected?: boolean;
}) => {
  const status = useWorkflowStore((s) => s.nodeStatuses[id] ?? 'idle');
  const output = useWorkflowStore((s) => s.nodeOutputs[id]);
  const hasInputs = data.category !== 'trigger';
  const hasOutputs = data.category !== 'output';

  return (
    <div
      className={`
        relative rounded-xl min-w-[170px] max-w-[200px] cursor-pointer
        bg-slate-800 border border-slate-600
        shadow-lg shadow-black/40
        ${STATUS_RING[status]}
        ${selected ? 'border-white/50' : ''}
        transition-all duration-150
      `}
    >
      {/* Colour accent top bar */}
      <div
        className="h-1 rounded-t-xl w-full"
        style={{ background: data.colour }}
      />

      {/* Header */}
      <div className="px-3 pt-2 pb-1 flex items-center gap-2">
        <span className="text-base leading-none">{CATEGORY_ICONS[data.category] ?? '▪'}</span>
        <span className="text-xs font-semibold text-slate-200 leading-tight flex-1 truncate">
          {data.label}
        </span>
        {/* Status dot */}
        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${STATUS_DOT[status]}`} />
      </div>

      {/* Output preview (shown when done) */}
      {output && status === 'done' && (
        <div className="mx-3 mb-2 px-2 py-1 rounded bg-slate-900/80 text-[10px] text-slate-400 font-mono max-h-16 overflow-hidden">
          {Object.entries(output).slice(0, 3).map(([k, v]) => (
            <div key={k} className="truncate">
              <span className="text-slate-500">{k}:</span>{' '}
              <span className="text-emerald-400">{String(v).slice(0, 30)}</span>
            </div>
          ))}
        </div>
      )}

      {/* Error preview */}
      {status === 'error' && (
        <div className="mx-3 mb-2 px-2 py-1 rounded bg-red-950/60 text-[10px] text-red-400 font-mono">
          error
        </div>
      )}

      {/* Input handle (left) */}
      {hasInputs && (
        <Handle
          type="target"
          position={Position.Left}
          style={{ background: '#475569', border: '2px solid #334155', width: 10, height: 10 }}
        />
      )}

      {/* Output handle (right) */}
      {hasOutputs && (
        <Handle
          type="source"
          position={Position.Right}
          style={{ background: data.colour, border: `2px solid ${data.colour}88`, width: 10, height: 10 }}
        />
      )}
    </div>
  );
});

SurveillanceNode.displayName = 'SurveillanceNode';
