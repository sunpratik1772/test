import type { Node, Edge } from '@xyflow/react';

type WFNode = Node<{ type: string; label: string; category: string; colour: string; config: Record<string, unknown> }>;
type WFEdge = Edge;

function n(id: string, type: string, label: string, category: string, colour: string,
           x: number, y: number, config: Record<string, unknown> = {}): WFNode {
  return { id, type: 'surveillanceNode', position: { x, y },
           data: { type, label, category, colour, config } };
}
function e(id: string, src: string, tgt: string): WFEdge {
  return { id, source: src, target: tgt, type: 'smoothstep' };
}

// ── FX FRONT-RUNNING ─────────────────────────────────────────────────────────
export const FX_FRO_TEMPLATE: { nodes: WFNode[]; edges: WFEdge[] } = {
  nodes: [
    n('t1',   'trigger',                  'Alert Trigger',          'trigger',   '#f97316',  360, 20,  { alert_type: 'fx_front_running', alert_id: 'FRO-001', trader_id: 'TRADER_001', instrument: 'EUR/USD', window_minutes: 60 }),
    n('c1',   'order_collector',          'Order Collector',        'collector', '#3b82f6',  80,  160),
    n('c2',   'book_collector',           'Book Collector',         'collector', '#3b82f6',  360, 160),
    n('c3',   'market_collector',         'Market Data Collector',  'collector', '#3b82f6',  640, 160),
    n('c4',   'comms_collector',          'Comms Collector',        'collector', '#3b82f6',  920, 160),
    n('e1',   'order_extractor',          'Order Extractor',        'extractor', '#8b5cf6',  80,  310),
    n('e2',   'book_extractor',           'Book Extractor',         'extractor', '#8b5cf6',  360, 310),
    n('e3',   'market_extractor',         'Market Extractor',       'extractor', '#8b5cf6',  640, 310),
    n('a1',   'order_lifecycle_analyser', 'Order Lifecycle',        'analyser',  '#14b8a6',  80,  460),
    n('a2',   'trade_metrics_analyser',   'Trade Metrics',          'analyser',  '#14b8a6',  360, 460),
    n('f1',   'indicator_filter',         'Indicator Filter',       'filter',    '#f59e0b',  360, 610),
    n('f2',   'routing_engine',           'Routing Engine',         'filter',    '#f59e0b',  360, 760),
    n('o1',   'summary_builder',          'Summary Builder',        'output',    '#64748b',  80,  910),
    n('o2',   'ai_summary',               'AI Summary (Gemini)',    'output',    '#64748b',  360, 910),
    n('o3',   'excel_builder',            'Excel Builder',          'output',    '#64748b',  640, 910),
    n('o4',   'audit_record',             'Audit Record',           'output',    '#64748b',  920, 910),
  ],
  edges: [
    e('e-t1-c1','t1','c1'), e('e-t1-c2','t1','c2'), e('e-t1-c3','t1','c3'), e('e-t1-c4','t1','c4'),
    e('e-c1-e1','c1','e1'), e('e-c2-e2','c2','e2'), e('e-c3-e3','c3','e3'),
    e('e-e1-a1','e1','a1'), e('e-e2-a2','e2','a2'), e('e-a1-a2','a1','a2'),
    e('e-a1-f1','a1','f1'), e('e-a2-f1','a2','f1'),
    e('e-f1-f2','f1','f2'),
    e('e-f2-o1','f2','o1'), e('e-f2-o2','f2','o2'), e('e-f2-o3','f2','o3'), e('e-f2-o4','f2','o4'),
  ],
};

// ── FI SPOOFING ──────────────────────────────────────────────────────────────
export const FI_SPOOF_TEMPLATE: { nodes: WFNode[]; edges: WFEdge[] } = {
  nodes: [
    n('t1',  'trigger',                        'Alert Trigger',            'trigger',   '#f97316',  440, 20,  { alert_type: 'fi_spoofing', alert_id: 'SPOOF-001', trader_id: 'TRADER_002', instrument: 'UST', tenor: '10yr', window_minutes: 60 }),
    n('c1',  'order_collector',                'FI Order Collector',       'collector', '#3b82f6',  80,  160),
    n('c2',  'book_collector',                 'FI Execution Collector',   'collector', '#3b82f6',  360, 160),
    n('c3',  'market_collector',               'Market Data Collector',    'collector', '#3b82f6',  640, 160),
    n('c4',  'fi_auction_collector',           'Auction Calendar',         'collector', '#3b82f6',  920, 160),
    n('e1',  'fi_order_extractor',             'FI Order Extractor',       'extractor', '#8b5cf6',  80,  310),
    n('e2',  'fi_execution_extractor',         'FI Execution Extractor',   'extractor', '#8b5cf6',  360, 310),
    n('e3',  'market_extractor',               'Market Extractor',         'extractor', '#8b5cf6',  640, 310),
    n('a1',  'fi_otr_analyser',                'OTR by Tenor',             'analyser',  '#14b8a6',  80,  460),
    n('a2',  'fi_cancel_latency_analyser',     'Cancel Latency',           'analyser',  '#14b8a6',  300, 460),
    n('a3',  'fi_yield_displacement_analyser', 'Yield Displacement',       'analyser',  '#14b8a6',  520, 460),
    n('a4',  'fi_book_imbalance_analyser',     'Book Imbalance',           'analyser',  '#14b8a6',  740, 460),
    n('a5',  'fi_directional_reversal_analyser','Directional Reversal',    'analyser',  '#14b8a6',  960, 460),
    n('a6',  'fi_auction_analyser',            'Auction Analyser',         'analyser',  '#14b8a6',  1180,460),
    n('f1',  'indicator_filter',               'Indicator Filter',         'filter',    '#f59e0b',  440, 620),
    n('f2',  'routing_engine',                 'Routing Engine',           'filter',    '#f59e0b',  440, 770),
    n('o1',  'summary_builder',                'Summary Builder',          'output',    '#64748b',  80,  920),
    n('o2',  'ai_summary',                     'AI Summary (Gemini)',      'output',    '#64748b',  360, 920),
    n('o3',  'excel_builder',                  'Excel Builder',            'output',    '#64748b',  640, 920),
    n('o4',  'audit_record',                   'Audit Record',             'output',    '#64748b',  920, 920),
  ],
  edges: [
    e('e-t1-c1','t1','c1'), e('e-t1-c2','t1','c2'), e('e-t1-c3','t1','c3'), e('e-t1-c4','t1','c4'),
    e('e-c1-e1','c1','e1'), e('e-c2-e2','c2','e2'), e('e-c3-e3','c3','e3'),
    e('e-e1-a1','e1','a1'), e('e-e1-a2','e1','a2'), e('e-e2-a5','e2','a5'),
    e('e-e3-a3','e3','a3'), e('e-e3-a4','e3','a4'),
    e('e-c4-a6','c4','a6'),
    e('e-a1-f1','a1','f1'), e('e-a2-f1','a2','f1'), e('e-a3-f1','a3','f1'),
    e('e-a4-f1','a4','f1'), e('e-a5-f1','a5','f1'), e('e-a6-f1','a6','f1'),
    e('e-f1-f2','f1','f2'),
    e('e-f2-o1','f2','o1'), e('e-f2-o2','f2','o2'), e('e-f2-o3','f2','o3'), e('e-f2-o4','f2','o4'),
  ],
};

// ── FI WASH TRADING ──────────────────────────────────────────────────────────
export const FI_WASH_TEMPLATE: { nodes: WFNode[]; edges: WFEdge[] } = {
  nodes: [
    n('t1',  'trigger',                    'Alert Trigger',          'trigger',   '#f97316',  420, 20,  { alert_type: 'fi_wash_trading', alert_id: 'WASH-001', trader_id: 'TRADER_003', instrument: 'UST', tenor: '5yr', window_minutes: 60 }),
    n('c1',  'book_collector',             'Wash Trade Collector',   'collector', '#3b82f6',  80,  160),
    n('c2',  'order_collector',            'Wash Order Collector',   'collector', '#3b82f6',  340, 160),
    n('c3',  'comms_collector',            'Comms Collector',        'collector', '#3b82f6',  600, 160),
    n('c4',  'counterparty_collector',     'Counterparty Collector', 'collector', '#3b82f6',  860, 160),
    n('e1',  'wash_trade_extractor',       'Wash Trade Extractor',   'extractor', '#8b5cf6',  80,  310),
    n('e2',  'order_extractor',            'Wash Order Extractor',   'extractor', '#8b5cf6',  340, 310),
    n('a1',  'wash_pair_detector',         'Wash Pair Detector',     'analyser',  '#14b8a6',  80,  460),
    n('a2',  'volume_inflation_analyser',  'Volume Inflation',       'analyser',  '#14b8a6',  340, 460),
    n('a3',  'price_marking_analyser',     'Price Marking',          'analyser',  '#14b8a6',  600, 460),
    n('f1',  'indicator_filter',           'Indicator Filter',       'filter',    '#f59e0b',  340, 610),
    n('f2',  'routing_engine',             'Routing Engine',         'filter',    '#f59e0b',  340, 760),
    n('o1',  'summary_builder',            'Summary Builder',        'output',    '#64748b',  80,  910),
    n('o2',  'ai_summary',                 'AI Summary (Gemini)',    'output',    '#64748b',  340, 910),
    n('o3',  'excel_builder',              'Excel Builder',          'output',    '#64748b',  600, 910),
    n('o4',  'audit_record',               'Audit Record',           'output',    '#64748b',  860, 910),
  ],
  edges: [
    e('e-t1-c1','t1','c1'), e('e-t1-c2','t1','c2'), e('e-t1-c3','t1','c3'), e('e-t1-c4','t1','c4'),
    e('e-c1-e1','c1','e1'), e('e-c4-e1','c4','e1'), e('e-c2-e2','c2','e2'),
    e('e-e1-a1','e1','a1'), e('e-a1-a2','a1','a2'), e('e-a1-a3','a1','a3'),
    e('e-a1-f1','a1','f1'), e('e-a2-f1','a2','f1'), e('e-a3-f1','a3','f1'),
    e('e-f1-f2','f1','f2'),
    e('e-f2-o1','f2','o1'), e('e-f2-o2','f2','o2'), e('e-f2-o3','f2','o3'), e('e-f2-o4','f2','o4'),
  ],
};

export const TEMPLATES = {
  fx_fro:   { label: 'FX Front-Running',  template: FX_FRO_TEMPLATE,   colour: '#f97316' },
  fi_spoof: { label: 'FI Spoofing',       template: FI_SPOOF_TEMPLATE,  colour: '#3b82f6' },
  fi_wash:  { label: 'FI Wash Trading',   template: FI_WASH_TEMPLATE,   colour: '#8b5cf6' },
};
