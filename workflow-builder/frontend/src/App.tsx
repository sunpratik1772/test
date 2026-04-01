import { ReactFlowProvider } from '@xyflow/react';
import { WorkflowToolbar } from './components/WorkflowToolbar';
import { NodeLibrary } from './components/NodeLibrary';
import { WorkflowCanvas } from './components/WorkflowCanvas';
import { PropertiesPanel } from './components/PropertiesPanel';
import { ExecutionLog } from './components/ExecutionLog';
import { useWorkflowStore } from './store/workflowStore';
import type { NodeStatus } from './store/workflowStore';

function App() {
  const {
    nodes, edges,
    setRunning, setNodeStatus, setNodeOutput, appendLog, setResult, resetExecution,
  } = useWorkflowStore();

  const handleRun = async () => {
    if (nodes.length === 0) return;
    resetExecution();
    setRunning(true);

    try {
      const res = await fetch('/api/workflow/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nodes, edges }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail ?? `HTTP ${res.status}`);
      }

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice(6).trim();
          if (raw === '[DONE]') { setRunning(false); break; }
          try {
            handleEvent(JSON.parse(raw));
          } catch {
            // ignore malformed lines
          }
        }
      }
    } catch (err) {
      console.error('Execution error:', err);
    } finally {
      setRunning(false);
    }
  };

  const handleEvent = (event: Record<string, unknown>) => {
    const type   = event.type as string;
    const nodeId = event.node_id as string | undefined;
    const label  = (event.label as string) ?? nodeId ?? '';

    if (type === 'node_start' && nodeId) {
      setNodeStatus(nodeId, 'running' as NodeStatus);
      appendLog({ nodeId, label, status: 'running', ts: Date.now() });
    }
    if (type === 'node_complete' && nodeId) {
      const output = (event.output as Record<string, unknown>) ?? {};
      setNodeStatus(nodeId, 'done' as NodeStatus);
      setNodeOutput(nodeId, output);
      appendLog({ nodeId, label, status: 'done', output, ts: Date.now() });
    }
    if (type === 'node_error' && nodeId) {
      setNodeStatus(nodeId, 'error' as NodeStatus);
      appendLog({ nodeId, label, status: 'error', error: event.error as string, ts: Date.now() });
    }
    if (type === 'workflow_done') {
      setResult(event.disposition as string, event.flag_count as number);
    }
  };

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-slate-950">
      <WorkflowToolbar onRun={handleRun} />
      <div className="flex flex-1 overflow-hidden">
        <NodeLibrary />
        <ReactFlowProvider>
          <WorkflowCanvas />
        </ReactFlowProvider>
        <PropertiesPanel />
      </div>
      <ExecutionLog />
    </div>
  );
}

export default App;
