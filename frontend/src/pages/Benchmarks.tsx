import React, { useEffect, useState, useCallback } from 'react';
import { colors, typography, spacing, borderRadius } from '../styles/designTokens';
import { LiquidBadge, LiquidButton } from '../components/LiquidGlass';
import { api } from '../services/api';

type Scenario = {
  scenario_id: string;
  name: string;
  description: string;
  category: string;
  difficulty: string;
};

type Baseline = { id: string; name: string; description: string };
type Ablation = { id: string; name: string; description: string };

type Experiment = {
  experiment_id: string;
  timestamp: string;
  status: string;
  scenarios_completed: number;
  scenarios_total: number;
  created_at: string;
};

type ResultRow = {
  id: number;
  experiment_id: string;
  scenario_id: string;
  baseline_configuration: string;
  ablation_mode: string | null;
  task_status: string;
  verification_result: string | null;
  total_latency_ms: number | null;
  attack_blocked: number | boolean;
  error: string | null;
  created_at: string;
};

const styles: Record<string, React.CSSProperties> = {
  container: { maxWidth: '1200px', margin: '0 auto', padding: spacing[6] },
  header: { marginBottom: spacing[6] },
  title: { fontSize: typography.fontSize['3xl'], fontWeight: typography.fontWeight.bold, color: colors.text.primary, margin: 0 },
  subtitle: { color: colors.text.secondary, marginTop: spacing[2] },
  section: { marginBottom: spacing[6], padding: spacing[6], background: colors.background.secondary, borderRadius: borderRadius.lg, border: `1px solid ${colors.border.primary}` },
  sectionTitle: { fontSize: typography.fontSize.xl, fontWeight: typography.fontWeight.semibold, color: colors.text.primary, margin: `0 0 ${spacing[4]} 0` },
  row: { display: 'flex', gap: spacing[4], flexWrap: 'wrap', alignItems: 'flex-end' },
  field: { display: 'flex', flexDirection: 'column', gap: spacing[2], minWidth: '220px', flex: 1 },
  label: { fontSize: typography.fontSize.sm, color: colors.text.secondary },
  select: { padding: spacing[3], borderRadius: borderRadius.base, border: `1px solid ${colors.border.primary}`, background: colors.background.tertiary, color: colors.text.primary },
  empty: { color: colors.text.tertiary, padding: spacing[4] },
  error: { color: colors.accent.error, padding: spacing[4] },
  table: { width: '100%', borderCollapse: 'collapse' as const },
  th: { textAlign: 'left' as const, padding: spacing[3], borderBottom: `1px solid ${colors.border.primary}`, color: colors.text.secondary, fontSize: typography.fontSize.sm },
  td: { padding: spacing[3], borderBottom: `1px solid ${colors.border.tertiary}`, color: colors.text.primary, fontSize: typography.fontSize.sm },
  chartWrap: { marginTop: spacing[4] },
  badgeRow: { display: 'flex', gap: spacing[3], flexWrap: 'wrap', marginBottom: spacing[4] },
};

function SimpleBarChart({ data, title, unit }: { data: { label: string; value: number }[]; title: string; unit: string }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <div style={styles.chartWrap}>
      <h3 style={styles.sectionTitle}>{title}</h3>
      {data.length === 0 ? (
        <p style={styles.empty}>No data available.</p>
      ) : (
        <svg width="100%" height={data.length * 36 + 20} viewBox={`0 0 600 ${data.length * 36 + 20}`}>
          {data.map((d, i) => {
            const width = (d.value / max) * 420;
            return (
              <g key={d.label + i} transform={`translate(0, ${i * 36})`}>
                <text x="0" y="20" fill={colors.text.secondary} fontSize="12">{d.label}</text>
                <rect x="150" y="6" width={width} height="18" fill={colors.accent.cyan} rx="4" />
                <text x={150 + width + 8} y="20" fill={colors.text.primary} fontSize="12">{d.value.toFixed(2)} {unit}</text>
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}

export default function Benchmarks() {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [baselines, setBaselines] = useState<Baseline[]>([]);
  const [ablations, setAblations] = useState<Ablation[]>([]);
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [scenarioId, setScenarioId] = useState('');
  const [baselineId, setBaselineId] = useState('atlas_x');
  const [selectedAblations, setSelectedAblations] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedExperimentId, setSelectedExperimentId] = useState<string | null>(null);
  const [results, setResults] = useState<ResultRow[]>([]);
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [sc, bl, ab, ex] = await Promise.all([
        api.get<Scenario[]>('/api/benchmarks/scenarios'),
        api.get<Baseline[]>('/api/benchmarks/baselines'),
        api.get<Ablation[]>('/api/benchmarks/ablations'),
        api.get<Experiment[]>('/api/benchmarks/experiments'),
      ]);
      setScenarios(sc);
      setBaselines(bl);
      setAblations(ab);
      setExperiments(ex);
      if (sc.length > 0 && !scenarioId) setScenarioId(sc[0].scenario_id);
      if (ex.length > 0 && !selectedExperimentId) setSelectedExperimentId(ex[0].experiment_id);
      setLastRefresh(new Date().toISOString());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load benchmark data');
    } finally {
      setLoading(false);
    }
  }, [scenarioId, selectedExperimentId]);

  useEffect(() => { loadAll(); }, [loadAll]);

  const loadExperimentDetail = async (id: string) => {
    try {
      const r = await api.get<ResultRow[]>(`/api/benchmarks/experiments/${id}/results`);
      setResults(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load experiment results');
    }
  };

  useEffect(() => {
    if (selectedExperimentId) loadExperimentDetail(selectedExperimentId);
  }, [selectedExperimentId]);

  const runExperiment = async () => {
    if (!scenarioId) return;
    setRunning(true);
    setError(null);
    try {
      const res = await api.post<{ experiment_id: string }>('/api/benchmarks/experiments', {
        scenario_id: scenarioId,
        baseline_configuration: baselineId,
        ablation_modes: selectedAblations,
      });
      await loadAll();
      setSelectedExperimentId(res.experiment_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Experiment failed');
    } finally {
      setRunning(false);
    }
  };

  const refreshVisualizations = async () => {
    await loadAll();
    if (selectedExperimentId) await loadExperimentDetail(selectedExperimentId);
  };

  // Aggregations from actual results
  const successByBaseline = Object.values(
    results.reduce<Record<string, { label: string; total: number; succeeded: number }>>((acc, r) => {
      const key = r.baseline_configuration;
      if (!acc[key]) acc[key] = { label: key, total: 0, succeeded: 0 };
      acc[key].total += 1;
      if (r.task_status === 'succeeded' || r.task_status === 'verified') acc[key].succeeded += 1;
      return acc;
    }, {})
  ).map((g) => ({ label: g.label, value: g.total > 0 ? (g.succeeded / g.total) * 100 : 0 }));

  const latencyByBaseline = Object.values(
    results.reduce<Record<string, { label: string; sum: number; n: number }>>((acc, r) => {
      const key = r.baseline_configuration;
      if (!acc[key]) acc[key] = { label: key, sum: 0, n: 0 };
      if (typeof r.total_latency_ms === 'number') { acc[key].sum += r.total_latency_ms; acc[key].n += 1; }
      return acc;
    }, {})
  ).map((g) => ({ label: g.label, value: g.n > 0 ? g.sum / g.n : 0 }));

  const verificationCounts = results.reduce<Record<string, number>>((acc, r) => {
    const key = r.verification_result || 'unknown';
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
  const verificationData = Object.entries(verificationCounts).map(([k, v]) => ({ label: k, value: v }));

  const completedCount = experiments.filter((e) => e.status === 'completed').length;
  const failedCount = experiments.filter((e) => e.status === 'failed').length;
  const latestTimestamp = experiments.length > 0 ? experiments[0].timestamp : null;

  return (
    <div style={styles.container}>
      <header style={styles.header}>
        <h1 style={styles.title}>ATLAS-X — Research Benchmarks</h1>
        <p style={styles.subtitle}>Experiments, reliability, security and verification — React workspace</p>
      </header>

      {error && <div style={styles.error}>{error}</div>}

      <section style={styles.section}>
        <h2 style={styles.sectionTitle}>Benchmark overview</h2>
        <div style={styles.badgeRow}>
          <LiquidBadge>Recorded experiments: {experiments.length}</LiquidBadge>
          <LiquidBadge>Completed: {completedCount}</LiquidBadge>
          <LiquidBadge>Failed: {failedCount}</LiquidBadge>
          <LiquidBadge>Scenarios available: {scenarios.length}</LiquidBadge>
          <LiquidBadge>Latest: {latestTimestamp || 'Unavailable'}</LiquidBadge>
          <LiquidBadge>Last refresh: {lastRefresh || 'Unavailable'}</LiquidBadge>
        </div>
      </section>

      <section style={styles.section}>
        <h2 style={styles.sectionTitle}>Run a benchmark</h2>
        <p style={{ color: colors.text.secondary, marginBottom: spacing[4] }}>Choose a real scenario and supported configuration.</p>
        <div style={styles.row}>
          <div style={styles.field}>
            <label style={styles.label}>Scenario</label>
            <select style={styles.select} value={scenarioId} onChange={(e) => setScenarioId(e.target.value)} disabled={loading || running}>
              <option value="">Select benchmark scenario…</option>
              {scenarios.map((s) => (
                <option key={s.scenario_id} value={s.scenario_id}>{s.scenario_id} — {s.category}</option>
              ))}
            </select>
          </div>
          <div style={styles.field}>
            <label style={styles.label}>Ablation configuration</label>
            <select style={styles.select} value={baselineId} onChange={(e) => setBaselineId(e.target.value)} disabled={loading || running}>
              {baselines.map((b) => (
                <option key={b.id} value={b.id}>{b.name}</option>
              ))}
            </select>
          </div>
          <div style={styles.field}>
            <label style={styles.label}>Ablation modes</label>
            <select multiple style={{ ...styles.select, minHeight: '90px' }} value={selectedAblations} onChange={(e) => setSelectedAblations(Array.from(e.target.selectedOptions, (o) => o.value))} disabled={loading || running}>
              {ablations.map((a) => (
                <option key={a.id} value={a.id}>{a.id}</option>
              ))}
            </select>
          </div>
        </div>
        <div style={{ marginTop: spacing[4] }}>
          <LiquidButton onClick={runExperiment} disabled={running || !scenarioId}>
            {running ? 'Running…' : 'Run Experiment'}
          </LiquidButton>
        </div>
      </section>

      <section style={styles.section}>
        <h2 style={styles.sectionTitle}>Experiment history</h2>
        {experiments.length === 0 ? (
          <p style={styles.empty}>No experiments yet. Run your first experiment above.</p>
        ) : (
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Experiment ID</th>
                <th style={styles.th}>Status</th>
                <th style={styles.th}>Completed</th>
                <th style={styles.th}>Total</th>
                <th style={styles.th}>Created</th>
              </tr>
            </thead>
            <tbody>
              {experiments.map((e) => (
                <tr key={e.experiment_id} style={{ cursor: 'pointer', background: selectedExperimentId === e.experiment_id ? colors.background.tertiary : 'transparent' }} onClick={() => setSelectedExperimentId(e.experiment_id)}>
                  <td style={styles.td}>{e.experiment_id}</td>
                  <td style={styles.td}>{e.status}</td>
                  <td style={styles.td}>{e.scenarios_completed}</td>
                  <td style={styles.td}>{e.scenarios_total}</td>
                  <td style={styles.td}>{e.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section style={styles.section}>
        <h2 style={styles.sectionTitle}>Results & visualizations</h2>
        <p style={{ color: colors.text.secondary, marginBottom: spacing[4] }}>Charts generated from actual results.</p>
        <div style={{ display: 'flex', gap: spacing[3], marginBottom: spacing[4] }}>
          <LiquidButton onClick={refreshVisualizations} disabled={loading || running}>Refresh data</LiquidButton>
        </div>
        {results.length === 0 ? (
          <p style={styles.empty}>Empty until real experiments are available. No made-up metrics.</p>
        ) : (
          <>
            <SimpleBarChart data={successByBaseline} title="Reliability comparison across configurations" unit="% success" />
            <SimpleBarChart data={latencyByBaseline} title="Execution latency (mean total, ms)" unit="ms" />
            <SimpleBarChart data={verificationData} title="Verification pass/fail outcomes" unit="runs" />
            <div style={{ marginTop: spacing[4] }}>
              <h3 style={styles.sectionTitle}>Result records ({results.length})</h3>
              <table style={styles.table}>
                <thead>
                  <tr>
                    <th style={styles.th}>Scenario</th>
                    <th style={styles.th}>Baseline</th>
                    <th style={styles.th}>Ablation</th>
                    <th style={styles.th}>Status</th>
                    <th style={styles.th}>Verification</th>
                    <th style={styles.th}>Latency ms</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((r) => (
                    <tr key={r.id}>
                      <td style={styles.td}>{r.scenario_id}</td>
                      <td style={styles.td}>{r.baseline_configuration}</td>
                      <td style={styles.td}>{r.ablation_mode || '—'}</td>
                      <td style={styles.td}>{r.task_status}</td>
                      <td style={styles.td}>{r.verification_result || '—'}</td>
                      <td style={styles.td}>{r.total_latency_ms ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
