import { useWorkflowStore } from '../store/workflowStore';
import { NODE_TYPE_DEFS } from '../data/nodeTypes';

export function PropertiesPanel() {
  const { nodes, selectedNodeId, updateNodeConfig, nodeOutputs } = useWorkflowStore();
  const node = nodes.find((n) => n.id === selectedNodeId);

  if (!node) {
    return (
      <aside className="w-60 bg-slate-900 border-l border-slate-700 flex flex-col">
        <div className="px-3 py-3 border-b border-slate-700">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Properties</p>
        </div>
        <div className="flex-1 flex items-center justify-center p-4">
          <p className="text-xs text-slate-600 text-center">Click a node to configure it</p>
        </div>
      </aside>
    );
  }

  const data = node.data as { type: string; label: string; category: string; colour: string; config: Record<string, unknown> };
  const typeDef = NODE_TYPE_DEFS.find((d) => d.type === data.type);
  const output = nodeOutputs[node.id];

  const handleChange = (key: string, value: string | number) => {
    updateNodeConfig(node.id, { [key]: value });
  };

  return (
    <aside className="w-60 bg-slate-900 border-l border-slate-700 flex flex-col overflow-hidden">
      {/* Header */}
      <div className="px-3 py-3 border-b border-slate-700">
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full" style={{ background: data.colour }} />
          <p className="text-xs font-semibold text-slate-300 truncate">{data.label}</p>
        </div>
        <p className="text-[11px] text-slate-600 mt-0.5 capitalize">{data.category}</p>
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* Description */}
        {typeDef && (
          <div className="px-3 py-2 border-b border-slate-800">
            <p className="text-[11px] text-slate-500 leading-relaxed">{typeDef.description}</p>
          </div>
        )}

        {/* Config fields */}
        {typeDef && typeDef.config.length > 0 && (
          <div className="px-3 py-2 border-b border-slate-800">
            <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-2">Configuration</p>
            <div className="space-y-2">
              {typeDef.config.map((field) => {
                const val = (data.config?.[field.key] ?? field.default) as string | number;
                return (
                  <div key={field.key}>
                    <label className="block text-[11px] text-slate-400 mb-0.5">{field.label}</label>
                    {field.type === 'select' ? (
                      <select
                        value={String(val)}
                        onChange={(e) => handleChange(field.key, e.target.value)}
                        className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1 text-[11px] text-slate-200 focus:outline-none focus:border-slate-500"
                      >
                        {field.options?.map((opt) => (
                          <option key={opt} value={opt}>{opt}</option>
                        ))}
                      </select>
                    ) : (
                      <input
                        type={field.type}
                        value={String(val)}
                        onChange={(e) => handleChange(field.key, field.type === 'number' ? Number(e.target.value) : e.target.value)}
                        className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1 text-[11px] text-slate-200 focus:outline-none focus:border-slate-500"
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Ports */}
        {typeDef && (
          <div className="px-3 py-2 border-b border-slate-800">
            <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5">Ports</p>
            {typeDef.inputs.length > 0 && (
              <div className="mb-1">
                <span className="text-[10px] text-slate-600">IN: </span>
                <span className="text-[10px] text-slate-400">{typeDef.inputs.join(', ')}</span>
              </div>
            )}
            {typeDef.outputs.length > 0 && (
              <div>
                <span className="text-[10px] text-slate-600">OUT: </span>
                <span className="text-[10px] text-slate-400">{typeDef.outputs.join(', ')}</span>
              </div>
            )}
          </div>
        )}

        {/* Output preview */}
        {output && (
          <div className="px-3 py-2">
            <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wider mb-1.5">Last Output</p>
            <pre className="text-[10px] text-emerald-400 font-mono bg-slate-800 rounded p-2 overflow-auto max-h-40 whitespace-pre-wrap">
              {JSON.stringify(output, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </aside>
  );
}
