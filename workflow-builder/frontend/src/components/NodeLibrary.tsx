import { useState } from 'react';
import { NODE_TYPE_DEFS, CATEGORY_META, type NodeCategory } from '../data/nodeTypes';

export function NodeLibrary() {
  const [open, setOpen] = useState<NodeCategory | null>('trigger');

  const onDragStart = (e: React.DragEvent, type: string) => {
    e.dataTransfer.setData('application/surveillance-node', type);
    e.dataTransfer.effectAllowed = 'move';
  };

  const categories = Object.entries(CATEGORY_META) as [NodeCategory, typeof CATEGORY_META[NodeCategory]][];

  return (
    <aside className="w-56 bg-slate-900 border-r border-slate-700 flex flex-col overflow-hidden">
      <div className="px-3 py-3 border-b border-slate-700">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Node Library</p>
        <p className="text-[11px] text-slate-600 mt-0.5">Drag onto canvas</p>
      </div>

      <div className="flex-1 overflow-y-auto">
        {categories.map(([catKey, catMeta]) => {
          const nodes = NODE_TYPE_DEFS.filter((n) => n.category === catKey);
          const isOpen = open === catKey;
          return (
            <div key={catKey} className="border-b border-slate-800">
              {/* Category header */}
              <button
                onClick={() => setOpen(isOpen ? null : catKey)}
                className="w-full flex items-center gap-2 px-3 py-2 hover:bg-slate-800 transition-colors text-left"
              >
                <span className="text-sm">{catMeta.icon}</span>
                <span className="text-xs font-medium text-slate-300 flex-1">{catMeta.label}</span>
                <span
                  className="text-[10px] font-bold px-1.5 py-0.5 rounded"
                  style={{ background: catMeta.colour + '33', color: catMeta.colour }}
                >
                  {nodes.length}
                </span>
                <span className="text-slate-600 text-xs">{isOpen ? '▾' : '▸'}</span>
              </button>

              {/* Node items */}
              {isOpen && (
                <div className="pb-1">
                  {nodes.map((node) => (
                    <div
                      key={node.type}
                      draggable
                      onDragStart={(e) => onDragStart(e, node.type)}
                      className="mx-2 mb-1 px-2 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 cursor-grab active:cursor-grabbing border border-slate-700 hover:border-slate-500 transition-all group"
                    >
                      <div className="flex items-center gap-1.5">
                        <span
                          className="w-2 h-2 rounded-full flex-shrink-0"
                          style={{ background: node.colour }}
                        />
                        <span className="text-[11px] text-slate-300 group-hover:text-white leading-tight">
                          {node.label}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </aside>
  );
}
