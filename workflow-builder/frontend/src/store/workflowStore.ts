import { create } from 'zustand';
import { addEdge, applyNodeChanges, applyEdgeChanges } from '@xyflow/react';
import type { Node, Edge, NodeChange, EdgeChange, Connection } from '@xyflow/react';

export type NodeStatus = 'idle' | 'running' | 'done' | 'error';

export interface LogEntry {
  nodeId: string;
  label: string;
  status: NodeStatus;
  output?: Record<string, unknown>;
  error?: string;
  ts: number;
}

interface WorkflowStore {
  nodes: Node[];
  edges: Edge[];
  selectedNodeId: string | null;
  nodeStatuses: Record<string, NodeStatus>;
  nodeOutputs: Record<string, Record<string, unknown>>;
  executionLog: LogEntry[];
  isRunning: boolean;
  disposition: string | null;
  flagCount: number | null;

  setNodes: (nodes: Node[]) => void;
  setEdges: (edges: Edge[]) => void;
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;
  selectNode: (id: string | null) => void;
  updateNodeConfig: (id: string, config: Record<string, unknown>) => void;

  loadTemplate: (nodes: Node[], edges: Edge[]) => void;
  clearCanvas: () => void;

  setNodeStatus: (id: string, status: NodeStatus) => void;
  setNodeOutput: (id: string, output: Record<string, unknown>) => void;
  appendLog: (entry: LogEntry) => void;
  setRunning: (v: boolean) => void;
  setResult: (disposition: string, flagCount: number) => void;
  resetExecution: () => void;
}

export const useWorkflowStore = create<WorkflowStore>((set) => ({
  nodes: [],
  edges: [],
  selectedNodeId: null,
  nodeStatuses: {},
  nodeOutputs: {},
  executionLog: [],
  isRunning: false,
  disposition: null,
  flagCount: null,

  setNodes: (nodes) => set({ nodes }),
  setEdges: (edges) => set({ edges }),

  onNodesChange: (changes) =>
    set((s) => ({ nodes: applyNodeChanges(changes, s.nodes) })),

  onEdgesChange: (changes) =>
    set((s) => ({ edges: applyEdgeChanges(changes, s.edges) })),

  onConnect: (connection) =>
    set((s) => ({ edges: addEdge({ ...connection, type: 'smoothstep' }, s.edges) })),

  selectNode: (id) => set({ selectedNodeId: id }),

  updateNodeConfig: (id, config) =>
    set((s) => ({
      nodes: s.nodes.map((n) =>
        n.id === id ? { ...n, data: { ...n.data, config: { ...(n.data.config as object), ...config } } } : n
      ),
    })),

  loadTemplate: (nodes, edges) =>
    set({ nodes, edges, selectedNodeId: null, nodeStatuses: {}, nodeOutputs: {}, executionLog: [], disposition: null, flagCount: null }),

  clearCanvas: () =>
    set({ nodes: [], edges: [], selectedNodeId: null, nodeStatuses: {}, nodeOutputs: {}, executionLog: [], disposition: null, flagCount: null }),

  setNodeStatus: (id, status) =>
    set((s) => ({ nodeStatuses: { ...s.nodeStatuses, [id]: status } })),

  setNodeOutput: (id, output) =>
    set((s) => ({ nodeOutputs: { ...s.nodeOutputs, [id]: output } })),

  appendLog: (entry) =>
    set((s) => ({ executionLog: [...s.executionLog, entry] })),

  setRunning: (v) => set({ isRunning: v }),

  setResult: (disposition, flagCount) => set({ disposition, flagCount }),

  resetExecution: () =>
    set({ nodeStatuses: {}, nodeOutputs: {}, executionLog: [], isRunning: false, disposition: null, flagCount: null }),
}));
