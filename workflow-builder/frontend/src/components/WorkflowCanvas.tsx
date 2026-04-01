import { useCallback, useRef } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
  useReactFlow,
} from '@xyflow/react';
import { SurveillanceNode } from './nodes/SurveillanceNode';
import { useWorkflowStore } from '../store/workflowStore';
import { NODE_TYPE_DEFS } from '../data/nodeTypes';

const NODE_TYPES = { surveillanceNode: SurveillanceNode };

let _idCounter = 100;
const newId = () => `node_${++_idCounter}`;

export function WorkflowCanvas() {
  const {
    nodes, edges,
    onNodesChange, onEdgesChange, onConnect,
    selectNode, setNodes,
  } = useWorkflowStore();
  const { screenToFlowPosition } = useReactFlow();
  const wrapperRef = useRef<HTMLDivElement>(null);

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const type = e.dataTransfer.getData('application/surveillance-node');
    if (!type) return;

    const def = NODE_TYPE_DEFS.find((d) => d.type === type);
    if (!def) return;

    const position = screenToFlowPosition({ x: e.clientX, y: e.clientY });
    const id = newId();

    const defaultConfig: Record<string, unknown> = {};
    def.config.forEach((f) => { defaultConfig[f.key] = f.default; });

    const newNode = {
      id,
      type: 'surveillanceNode',
      position,
      data: {
        type: def.type,
        label: def.label,
        category: def.category,
        colour: def.colour,
        config: defaultConfig,
      },
    };

    setNodes([...nodes, newNode]);
    selectNode(id);
  }, [nodes, screenToFlowPosition, selectNode, setNodes]);

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  }, []);

  return (
    <div ref={wrapperRef} className="flex-1 relative">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={(_, node) => selectNode(node.id)}
        onPaneClick={() => selectNode(null)}
        onDrop={onDrop}
        onDragOver={onDragOver}
        nodeTypes={NODE_TYPES}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        minZoom={0.2}
        maxZoom={2}
        deleteKeyCode="Backspace"
        className="bg-slate-950"
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={20}
          size={1}
          color="#1e293b"
        />
        <Controls position="bottom-right" />
        <MiniMap
          position="bottom-left"
          nodeColor={(n) => {
            const d = n.data as { colour?: string };
            return d.colour ?? '#475569';
          }}
          maskColor="#0f111799"
        />
      </ReactFlow>

      {/* Drop hint when canvas empty */}
      {nodes.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="text-center">
            <p className="text-slate-700 text-sm font-medium">Canvas is empty</p>
            <p className="text-slate-800 text-xs mt-1">Load a template or drag nodes from the library</p>
          </div>
        </div>
      )}
    </div>
  );
}
