/** Provenance Explorer - Browse and verify provenance chains. */

import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../services/api';
import type { Task } from '../types';
import { LiquidButton, LiquidBadge, LiquidTabs, LiquidSpinner } from '../components/LiquidGlass';
import { colors, typography, spacing, borderRadius } from '../styles/designTokens';
import { formatTimestamp } from '../utils/dates';

interface ProvenanceEvent {
  id: number;
  task_id: number | null;
  execution_id: number | null;
  plan_id: number | null;
  plan_step_id: number | null;
  tool_id: string | null;
  invocation_id: string | null;
  sequence_no: number;
  chain_digest: string | null;
  event_type: string | null;
  actor: string | null;
  detail: Record<string, unknown>;
  created_at: string | null;
}

interface IntegrityCheck {
  task_id: number;
  valid: boolean;
  verification_code: string;
  failed_event_id?: number | null;
  failed_event_sequence?: number | null;
  verified_at?: string;
  issues?: Array<{ event_id: number; issue: string; severity: 'warning' | 'error' }>;
}

type ActiveTab = 'chain' | 'verification' | 'events';

export function ProvenanceExplorer() {
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [securityEvents, setSecurityEvents] = useState<ProvenanceEvent[]>([]);
  const [integrityCheck, setIntegrityCheck] = useState<IntegrityCheck | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<ActiveTab>('chain');

  const fetchTasks = useCallback(async () => {
    try {
      const data = await api.get<Task[]>('/api/tasks');
      setTasks(data);
      if (data.length > 0) {
        setSelectedTask((prev) => (prev ? prev : data[0]));
      }
    } catch (err) {
      console.error('Failed to fetch tasks:', err);
    }
  }, []);

  const fetchTaskProvenanceData = useCallback(async (taskId: number) => {
    try {
      const [eventsRes, integrityRes] = await Promise.all([
        api.get<ProvenanceEvent[]>(`/api/tasks/${taskId}/provenance`),
        api.post<IntegrityCheck>(`/api/tasks/${taskId}/provenance/verify`, {}),
      ]);
      setSecurityEvents(eventsRes);
      setIntegrityCheck(integrityRes);
    } catch (err) {
      console.error('Failed to fetch provenance data:', err);
    }
  }, []);

  useEffect(() => {
    fetchTasks();
    setLoading(false);
  }, [fetchTasks]);

  useEffect(() => {
    if (selectedTask) {
      fetchTaskProvenanceData(selectedTask.id);
    } else {
      setSecurityEvents([]);
      setIntegrityCheck(null);
    }
  }, [selectedTask, fetchTaskProvenanceData]);

  const handleVerifyIntegrity = async (taskId: number) => {
    try {
      const result = await api.post<IntegrityCheck>(`/api/tasks/${taskId}/provenance/verify`, {});
      setIntegrityCheck(result);
    } catch (err) {
      console.error('Integrity verification failed:', err);
    }
  };

  if (loading) {
    return (
      <div style={styles.container}>
        <div className="ambient-bg">
          <div className="ambient-grid"></div>
          <div className="ambient-orbs">
            <div className="ambient-orb ambient-orb-1"></div>
            <div className="ambient-orb ambient-orb-2"></div>
            <div className="ambient-orb ambient-orb-3"></div>
            <div className="ambient-orb ambient-orb-4"></div>
          </div>
        </div>
        <div style={styles.loadingOverlay}>
          <LiquidSpinner size="lg" color="cyan" />
          <p style={styles.loadingText}>Loading Provenance Explorer...</p>
        </div>
      </div>
    );
  }

return (
    <div className="provenance-explorer" style={styles.container}>
      <div className="ambient-bg">
        <div className="ambient-grid"></div>
        <div className="ambient-orbs">
          <div className="ambient-orb ambient-orb-1"></div>
          <div className="ambient-orb ambient-orb-2"></div>
          <div className="ambient-orb ambient-orb-3"></div>
          <div className="ambient-orb ambient-orb-4"></div>
        </div>
      </div>
      <header style={styles.header}>
        <LiquidButton variant="ghost" onClick={() => navigate('/dashboard')} icon="←" iconPosition="left" size="sm">
          Back to Dashboard
        </LiquidButton>
        <div style={styles.headerCenter}>
          <h1 style={styles.title}>Provenance Explorer</h1>
          <p style={styles.subtitle}>Browse and verify tamper-evident provenance chains</p>
        </div>
      </header>

      <div style={styles.main}>
        <aside style={styles.sidebar}>
          <div style={styles.sidebarHeader}>
            <h2 style={styles.sidebarTitle}>Select Task</h2>
            <LiquidButton variant="secondary" size="sm" onClick={() => setSelectedTask(null)} style={{ width: '100%' }}>
              Clear Selection
            </LiquidButton>
          </div>
          <div style={styles.taskSelector}>
            {tasks.length === 0 ? (
              <div style={styles.emptyState} className="glass-panel-subtle">
                <p style={styles.emptyText}>No tasks available</p>
                <LiquidButton variant="primary" size="sm" onClick={() => navigate('/tasks/create')}>
                  Create Task
                </LiquidButton>
              </div>
            ) : (
              <div style={styles.taskList}>
                {tasks.map(task => (
                  <div
                    key={task.id}
                    className="glass-card"
                    style={{
                      ...styles.taskItem,
                      borderColor: selectedTask?.id === task.id ? colors.accent.cyan : colors.border.primary,
                      background: selectedTask?.id === task.id ? `rgba(0, 229, 255, 0.08)` : `rgba(255, 255, 255, 0.02)`,
                      padding: spacing[3],
                    }}
                    onClick={() => setSelectedTask(task)}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <span style={styles.taskTitle}>{task.title}</span>
                      <LiquidBadge variant={getStatusBadge(task.status)} size="sm">
                        {task.status.toUpperCase()}
                      </LiquidBadge>
                    </div>
                    <div style={{ fontSize: typography.fontSize.xs, color: colors.text.muted }}>
                      {task.updated_at ? formatTimestamp(task.updated_at) : ''}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside>

        <div style={styles.content}>
          <div className="sidebar-overlay" />
          {selectedTask ? (
            <div className="glass-panel-elevated glass-specular" style={styles.detailContainer}>
              <div style={styles.detailHeader}>
                <h2 style={styles.detailTitle}>{selectedTask.title}</h2>
                <span className="glass-badge glass-badge-cyan" style={styles.detailBadge}>
                  {selectedTask.status.toUpperCase()}
                </span>
                <LiquidButton variant="primary" size="sm" onClick={() => handleVerifyIntegrity(selectedTask.id)} style={{ marginLeft: 'auto' }}>
                  Verify Chain
                </LiquidButton>
              </div>
              <div style={styles.tabContent}>
                <LiquidTabs
                  tabs={[
                    { id: 'chain', label: 'Provenance Chain' },
                    { id: 'verification', label: 'Verification' },
                    { id: 'events', label: 'Events' },
                  ]}
                  activeTab={activeTab}
                  onChange={(tabId: string) => setActiveTab(tabId as ActiveTab)}
                />
                {activeTab === 'chain' && renderChainTab(securityEvents)}
                {activeTab === 'verification' && renderVerificationTab(integrityCheck, () => handleVerifyIntegrity(selectedTask.id))}
                {activeTab === 'events' && renderEventsTab(securityEvents)}
              </div>
            </div>
          ) : (
            <div className="glass-panel-elevated glass-specular" style={styles.welcomePanel}>
              <div style={styles.welcomeContent}>
                <div style={styles.welcomeIcon}>🔗</div>
                <h2 style={styles.welcomeTitle}>Select a Task to Begin</h2>
                <p style={styles.welcomeText}>
                  Select a task from the sidebar to explore its provenance chain,
                  verify chain integrity, and inspect security events.
                </p>
                <div style={styles.welcomeFeatures}>
                  {[
                    { icon: '🔗', title: 'Provenance Chain', desc: 'Browse the complete tamper-evident event chain' },
                    { icon: '✓', title: 'Chain Verification', desc: 'Cryptographic verification of hash-linked event sequences' },
                    { icon: '📋', title: 'Event Log', desc: 'Complete audit trail of all security-relevant operations' },
                  ].map((f, i) => (
                    <div key={i} className="glass-card" style={styles.featureCard}>
                      <span style={{ fontSize: typography.fontSize.xl }}>{f.icon}</span>
                      <div>
                        <h4 style={styles.featureTitle}>{f.title}</h4>
                        <p style={styles.featureDesc}>{f.desc}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function getStatusBadge(status: string) {
  const variants: Record<string, 'success' | 'error' | 'warning' | 'info' | 'cyan' | 'violet' | 'default'> = {
    verified: 'success',
    succeeded: 'success',
    executed: 'info',
    executing: 'cyan',
    verifying: 'violet',
    planned: 'warning',
    pending: 'warning',
    failed: 'error',
  };
  return variants[status] || 'default';
}

function renderChainTab(securityEvents: ProvenanceEvent[]) {
  return (
    <div style={styles.tabContent}>
      <div style={styles.overviewGrid}>
        <div className="glass-panel-elevated glass-specular" style={styles.overviewCard}>
          <h3 style={styles.sectionTitle}>Provenance Chain</h3>
          <p style={styles.sectionDescription}>
            Tamper-evident event chain showing all security-relevant operations for this task.
          </p>
          {securityEvents.length === 0 ? (
            <div style={styles.emptyState} className="glass-panel-subtle">
              <p style={styles.emptyText}>No provenance events recorded for this task.</p>
            </div>
          ) : (
            <div style={styles.eventTimeline}>
              {securityEvents.map(event => (
                <div key={event.id} className="glass-panel-subtle glass-specular" style={styles.timelineEvent}>
                  <div style={styles.eventHeader}>
                    <span style={styles.eventSequence}>#{event.sequence_no}</span>
                    <span style={styles.eventType}>{event.event_type}</span>
                    <span style={styles.eventActor}>{event.actor}</span>
                    <span style={styles.eventTime}>{event.created_at ? formatTimestamp(event.created_at) : ''}</span>
                  </div>
                  {event.detail && Object.keys(event.detail).length > 0 && (
                    <details style={styles.eventDetail}>
                      <summary style={styles.detailsSummary}>Details</summary>
                      <pre style={styles.eventDetailJson}>{JSON.stringify(event.detail, null, 2)}</pre>
                    </details>
                  )}
                  <div style={styles.eventChain}>
                    <span style={styles.chainLabel}>Chain Digest:</span>
                    <code style={styles.chainDigest}>{event.chain_digest ? event.chain_digest.slice(0, 32) : '-'}...</code>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function renderVerificationTab(integrityCheck: IntegrityCheck | null, onVerifyIntegrity: () => void) {
  return (
    <div style={styles.tabContent}>
      <div className="glass-panel-elevated glass-specular" style={styles.overviewCard}>
        <h3 style={styles.sectionTitle}>Integrity Verification</h3>
        <p style={styles.sectionDescription}>
          Cryptographic verification of the provenance chain integrity using hash-linked event sequences.
        </p>
        {integrityCheck ? (
          <div>
            <div style={{
              ...styles.provenanceStatus,
              background: integrityCheck.valid ? `${colors.accent.success}1A` : `${colors.accent.error}1A`,
              borderColor: integrityCheck.valid ? colors.accent.success : colors.accent.error,
            }}>
              <span style={{ color: integrityCheck.valid ? colors.accent.success : colors.accent.error, fontWeight: typography.fontWeight.semibold }}>
                {integrityCheck.valid ? '✓ CHAIN VALID' : '✗ CHAIN INVALID'}
              </span>
              {integrityCheck.issues && integrityCheck.issues.length > 0 && (
                <span style={{ color: colors.accent.error }}>
                  {integrityCheck.issues.length} issue(s) found
                </span>
              )}
            </div>
            <div style={styles.summaryGrid}>
              <div style={styles.summaryItem} className="glass-panel-subtle">
                <span style={styles.summaryLabel}>Verified At</span>
                <span style={styles.summaryValue}>{integrityCheck.verified_at ? formatTimestamp(integrityCheck.verified_at) : 'just now'}</span>
              </div>
              <div style={styles.summaryItem} className="glass-panel-subtle">
                <span style={styles.summaryLabel}>Task ID</span>
                <span style={styles.summaryValue}>{integrityCheck.task_id}</span>
              </div>
              <div style={styles.summaryItem} className="glass-panel-subtle">
                <span style={styles.summaryLabel}>Issues</span>
                <span style={{ ...styles.summaryValue, color: integrityCheck.issues && integrityCheck.issues.length > 0 ? colors.accent.error : colors.accent.success }}>
                  {integrityCheck.issues?.length || 0}
                </span>
              </div>
            </div>
            {integrityCheck.issues && integrityCheck.issues.length > 0 && (
              <div style={{ marginTop: spacing[6] }}>
                <h4 style={{ fontSize: typography.fontSize.sm, fontWeight: typography.fontWeight.semibold, marginBottom: spacing[3] }}>
                  Verification Issues
                </h4>
                {integrityCheck.issues.map((issue, i) => (
                  <div key={i} className="glass-panel-subtle" style={styles.issueCard}>
                    <div style={styles.issueHeader}>
                      <LiquidBadge variant={issue.severity === 'error' ? 'error' : 'warning'} size="sm">
                        {issue.severity.toUpperCase()}
                      </LiquidBadge>
                      <span style={styles.issueEvent}>Event #{issue.event_id}</span>
                    </div>
                    <p style={styles.issueDescription}>{issue.issue}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div style={styles.emptyState} className="glass-panel-subtle">
            <p style={styles.emptyText}>Integrity has not been verified yet.</p>
            <LiquidButton variant="primary" onClick={onVerifyIntegrity} style={{ marginTop: spacing[3] }}>
              Verify Integrity
            </LiquidButton>
          </div>
        )}
      </div>
    </div>
  );
}

function renderEventsTab(securityEvents: ProvenanceEvent[]) {
  return (
    <div style={styles.tabContent}>
      <div className="glass-panel-elevated glass-specular" style={styles.overviewCard}>
        <h3 style={styles.sectionTitle}>Security Events</h3>
        <p style={styles.sectionDescription}>
          Complete audit trail of all security-relevant events for this task.
        </p>
        {securityEvents.length === 0 ? (
          <div style={styles.emptyState} className="glass-panel-subtle">
            <p style={styles.emptyText}>No security events recorded for this task.</p>
          </div>
        ) : (
          <div style={styles.eventList}>
            {securityEvents.map(event => (
              <div key={event.id} className="glass-panel-subtle glass-specular" style={styles.eventCard}>
                <div style={styles.eventHeader}>
                  <span style={styles.eventSequence}>#{event.sequence_no}</span>
                  <span style={styles.eventType}>{event.event_type}</span>
                  <span style={styles.eventActor}>{event.actor}</span>
                  <span style={styles.eventTime}>{event.created_at ? formatTimestamp(event.created_at) : ''}</span>
                </div>
                {event.detail && Object.keys(event.detail).length > 0 && (
                  <details style={styles.eventDetail}>
                    <summary style={styles.detailsSummary}>Details</summary>
                    <pre style={styles.eventDetailJson}>{JSON.stringify(event.detail, null, 2)}</pre>
                  </details>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    minHeight: '100vh',
    backgroundColor: colors.background.primary,
    fontFamily: typography.fontFamily.primary,
    color: colors.text.primary,
    display: 'flex',
    flexDirection: 'column',
  },
  header: {
    height: '64px',
    padding: `0 ${spacing[8]}`,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    background: `rgba(10, 13, 23, 0.9)`,
    backdropFilter: 'blur(20px)',
    WebkitBackdropFilter: 'blur(20px)',
    borderBottom: `1px solid ${colors.border.tertiary}`,
    position: 'sticky',
    top: 0,
    zIndex: 100,
  },
  headerCenter: {
    flex: 1,
    textAlign: 'center',
  },
  title: {
    fontSize: typography.fontSize['2xl'],
    fontWeight: typography.fontWeight.bold,
    margin: 0,
    background: `linear-gradient(135deg, ${colors.text.primary} 0%, ${colors.accent.cyan} 100%)`,
    WebkitBackgroundClip: 'text',
    WebkitTextFillColor: 'transparent',
    backgroundClip: 'text',
  },
  subtitle: {
    color: colors.text.tertiary,
    marginTop: spacing[1],
  },
  main: {
    display: 'grid',
    gridTemplateColumns: 'minmax(0, 280px) 1fr',
    gap: spacing[6],
    flex: 1,
    minHeight: 0,
    minWidth: 0,
  },
  sidebar: {
    width: '100%',
    maxWidth: '280px',
    minWidth: 0,
    padding: spacing[6],
    background: `rgba(10, 13, 23, 0.8)`,
    backdropFilter: 'blur(20px)',
    WebkitBackdropFilter: 'blur(20px)',
    borderRight: `1px solid ${colors.border.tertiary}`,
    display: 'flex',
    flexDirection: 'column',
    overflowY: 'auto',
  },
  sidebarHeader: {
    marginBottom: spacing[6],
  },
  sidebarTitle: {
    fontSize: typography.fontSize.lg,
    fontWeight: typography.fontWeight.semibold,
    marginBottom: spacing[4],
  },
  taskSelector: {
    flex: 1,
    overflowY: 'auto',
  },
  taskList: {
    display: 'flex',
    flexDirection: 'column',
    gap: spacing[2],
  },
  taskItem: {
    display: 'flex',
    flexDirection: 'column',
    gap: spacing[1],
    cursor: 'pointer',
    transition: 'all 200ms ease',
    padding: spacing[3],
  },
  taskTitle: {
    fontSize: typography.fontSize.sm,
    fontWeight: typography.fontWeight.medium,
    color: colors.text.primary,
  },
  content: {
    flex: 1,
    padding: spacing[8],
    overflow: 'auto',
  },
  welcomePanel: {
    maxWidth: '800px',
    margin: '0 auto',
  },
  welcomeContent: {
    textAlign: 'center',
  },
  welcomeIcon: {
    fontSize: '64px',
    marginBottom: spacing[6],
    animation: 'pulse 2s ease-in-out infinite',
  },
  welcomeTitle: {
    fontSize: typography.fontSize['3xl'],
    fontWeight: typography.fontWeight.bold,
    marginBottom: spacing[4],
    background: `linear-gradient(135deg, ${colors.text.primary} 0%, ${colors.accent.cyan} 100%)`,
    WebkitBackgroundClip: 'text',
    WebkitTextFillColor: 'transparent',
    backgroundClip: 'text',
  },
  welcomeText: {
    color: colors.text.secondary,
    fontSize: typography.fontSize.lg,
    lineHeight: typography.lineHeight.relaxed,
    marginBottom: spacing[8],
    maxWidth: '600px',
    margin: '0 auto ' + spacing[8],
  },
  welcomeFeatures: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
    gap: spacing[4],
    marginTop: spacing[8],
  },
  featureCard: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: spacing[4],
    textAlign: 'left',
    padding: spacing[4],
  },
  featureTitle: {
    fontSize: typography.fontSize.base,
    fontWeight: typography.fontWeight.semibold,
    margin: '0 0 ' + spacing[1] + ' 0',
    color: colors.text.primary,
  },
  featureDesc: {
    color: colors.text.tertiary,
    fontSize: typography.fontSize.sm,
    lineHeight: 1.5,
    margin: 0,
  },
  detailContainer: {
    maxWidth: '1200px',
    margin: '0 auto',
  },
  detailHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing[6],
    paddingBottom: spacing[4],
    borderBottom: `1px solid ${colors.border.tertiary}`,
    flexWrap: 'wrap',
    gap: spacing[4],
  },
  detailTitle: {
    fontSize: typography.fontSize['2xl'],
    fontWeight: typography.fontWeight.bold,
    margin: 0,
  },
  detailBadge: {
    padding: `${spacing[1]} ${spacing[3]}`,
    fontSize: typography.fontSize.xs,
  },
  tabContent: {
    animation: 'fadeInUp 0.3s ease-out',
  },
  overviewGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
    gap: spacing[4],
    marginBottom: spacing[6],
  },
  overviewCard: {
    animation: 'fadeInUp 0.4s ease-out',
  },
  sectionTitle: {
    fontSize: typography.fontSize.lg,
    fontWeight: typography.fontWeight.semibold,
    margin: `0 0 ${spacing[4]} 0`,
    color: colors.text.primary,
  },
  sectionDescription: {
    color: colors.text.tertiary,
    marginBottom: spacing[4],
  },
  statusDisplay: {
    textAlign: 'center',
  },
  summaryGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
    gap: spacing[4],
  },
  summaryItem: {
    display: 'flex',
    flexDirection: 'column',
    gap: spacing[2],
    padding: spacing[4],
  },
  summaryLabel: {
    fontSize: typography.fontSize.xs,
    textTransform: 'uppercase',
    letterSpacing: '0.1em',
    color: colors.text.tertiary,
  },
  summaryValue: {
    fontSize: typography.fontSize.xl,
    fontWeight: typography.fontWeight.bold,
    color: colors.accent.cyan,
  },
  emptyText: {
    color: colors.text.tertiary,
    textAlign: 'center',
    padding: spacing[6],
  },
  emptyState: {
    textAlign: 'center',
    padding: spacing[6],
    color: colors.text.tertiary,
  },
  actionGrid: {
    display: 'flex',
    gap: spacing[3],
    flexWrap: 'wrap',
    marginTop: spacing[4],
  },
  provenanceStatus: {
    display: 'flex',
    alignItems: 'center',
    gap: spacing[4],
    padding: spacing[4],
    borderRadius: borderRadius.base,
    borderWidth: '1px',
    borderStyle: 'solid',
    marginBottom: spacing[6],
  },
  issueItem: {
    display: 'flex',
    alignItems: 'center',
    gap: spacing[2],
    marginBottom: spacing[2],
    padding: spacing[2],
  },
  issueCard: {
    background: `rgba(255, 255, 255, 0.02)`,
    border: `1px solid ${colors.border.primary}`,
    borderRadius: borderRadius.base,
  },
  issueHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: spacing[3],
    marginBottom: spacing[2],
  },
  issueEvent: {
    fontSize: typography.fontSize.sm,
    fontWeight: typography.fontWeight.medium,
    color: colors.text.secondary,
  },
  issueDescription: {
    fontSize: typography.fontSize.sm,
    color: colors.text.secondary,
    margin: 0,
  },
  loadingOverlay: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: '100vh',
    gap: spacing[4],
  },
  loadingText: {
    color: colors.text.tertiary,
    fontSize: typography.fontSize.base,
  },
};

export default ProvenanceExplorer;
