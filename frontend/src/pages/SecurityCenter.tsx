/** Security and Provenance Center - Inspect permissions, verify integrity, and explore provenance chains. */

import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../services/api';
import type { Task } from '../types';
import { colors, typography, spacing, borderRadius } from '../styles/designTokens';
import { GlassCard, LiquidButton, LiquidTabs, LiquidBadge, LiquidSpinner } from '../components/LiquidGlass';
import { formatTimestamp } from '../utils/dates';

interface SecurityEvent {
  id: number;
  task_id: number | null;
  execution_id: number | null;
  event_type: string | null;
  actor: string | null;
  detail: Record<string, unknown>;
  created_at: string | null;
  sequence_no: number;
  chain_digest: string | null;
}

interface ToolPermission {
  tool_name: string;
  scope: string | null;
  granted: boolean;
  reason: string;
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

type ActiveTab = 'overview' | 'permissions' | 'provenance' | 'integrity' | 'events';

function renderOverviewTab(task: Task, integrityCheck: IntegrityCheck | null, onVerifyIntegrity: () => void) {
  return (
    <div style={styles.tabContent}>
      <div style={styles.overviewGrid}>
        <div className="glass-panel-elevated glass-specular" style={styles.overviewCard}>
          <h3 style={styles.sectionTitle}>Task Overview</h3>
          <div style={styles.summaryGrid}>
            <div style={styles.summaryItem} className="glass-panel-subtle">
              <span style={styles.summaryLabel}>Task ID</span>
              <span style={styles.summaryValue}>{task.id}</span>
            </div>
            <div style={styles.summaryItem} className="glass-panel-subtle">
              <span style={styles.summaryLabel}>Status</span>
              <span style={{ ...styles.summaryValue, color: colors.accent.cyan }}>{task.status}</span>
            </div>
            <div style={styles.summaryItem} className="glass-panel-subtle">
              <span style={styles.summaryLabel}>Created</span>
              <span style={styles.summaryValue}>{task.created_at ? formatTimestamp(task.created_at) : '—'}</span>
            </div>
            <div style={styles.summaryItem} className="glass-panel-subtle">
              <span style={styles.summaryLabel}>Updated</span>
              <span style={styles.summaryValue}>{task.updated_at ? formatTimestamp(task.updated_at) : '—'}</span>
            </div>
          </div>
        </div>

        <div className="glass-panel-elevated glass-specular" style={styles.overviewCard}>
          <h3 style={styles.sectionTitle}>Provenance Integrity</h3>
          {integrityCheck ? (
            <div style={styles.statusDisplay}>
              <LiquidBadge
                variant={
                  integrityCheck.verification_code === 'empty_chain' ? 'warning' :
                  integrityCheck.valid ? 'success' : 'error'
                }
                size="lg"
                style={{ marginBottom: spacing[4] }}
              >
                {integrityCheck.verification_code === 'empty_chain' ? '⚠ CHAIN EMPTY' :
                 integrityCheck.valid ? '✓ CHAIN VALID' : '✗ CHAIN INVALID'}
              </LiquidBadge>
              <p style={styles.sectionDescription}>
                Last verified: {integrityCheck.verified_at ? formatTimestamp(integrityCheck.verified_at) : 'just now'}
              </p>
              {integrityCheck.issues && integrityCheck.issues.length > 0 && (
                <div style={{ marginTop: spacing[4] }}>
                  <h4 style={{ fontSize: typography.fontSize.sm, fontWeight: typography.fontWeight.semibold, marginBottom: spacing[2] }}>
                    Issues ({integrityCheck.issues.length})
                  </h4>
                  {integrityCheck.issues && integrityCheck.issues.map((issue, i) => (
                    <div key={i} style={styles.issueItem} className="glass-panel-subtle">
                      <LiquidBadge variant={issue.severity === 'error' ? 'error' : 'warning'} size="sm">
                        {issue.severity.toUpperCase()}
                      </LiquidBadge>
                      <span style={{ fontSize: typography.fontSize.sm, color: colors.text.secondary }}>
                        Event #{issue.event_id}: {issue.issue}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div style={styles.statusDisplay}>
              <LiquidBadge variant="warning" size="lg">NOT VERIFIED</LiquidBadge>
              <p style={styles.sectionDescription}>Run integrity verification to check provenance chain.</p>
              <LiquidButton variant="primary" size="sm" onClick={onVerifyIntegrity} style={{ marginTop: spacing[3] }}>
                Verify Integrity
              </LiquidButton>
            </div>
          )}
        </div>
      </div>

      <div className="glass-panel-elevated glass-specular" style={styles.overviewCard}>
        <h3 style={styles.sectionTitle}>Quick Actions</h3>
        <div style={styles.actionGrid}>
          <LiquidButton variant="primary" onClick={onVerifyIntegrity}>
            Run Audit
          </LiquidButton>
          <LiquidButton variant="secondary">
            View Tool Permissions
          </LiquidButton>
          <LiquidButton variant="secondary">
            Export Security Report
          </LiquidButton>
        </div>
      </div>
    </div>
  );
}

function renderPermissionsTab(toolPermissions: ToolPermission[]) {
  return (
    <div style={styles.tabContent}>
      <div className="glass-panel-elevated glass-specular" style={styles.overviewCard}>
        <h3 style={styles.sectionTitle}>Tool Permissions</h3>
        <p style={styles.sectionDescription}>
          Tool grants and authorization decisions for this task. Grants are least-privilege and scoped to the task.
        </p>
        {toolPermissions.length === 0 ? (
          <div style={styles.emptyState} className="glass-panel-subtle">
            <p style={styles.emptyText}>No tool permissions configured for this task.</p>
          </div>
        ) : (
          <div style={styles.tableContainer}>
            <div style={styles.tableHeader}>
              <span style={styles.tableCellHeader}>Tool</span>
              <span style={styles.tableCellHeader}>Scope</span>
              <span style={styles.tableCellHeader}>Granted</span>
              <span style={styles.tableCellHeader}>Reason</span>
            </div>
            {toolPermissions.map((perm, i) => (
              <div key={i} style={styles.tableRow} className="glass-panel-subtle">
                <span style={styles.tableCell}>{perm.tool_name}</span>
                <span style={styles.tableCell}>{perm.scope || 'global'}</span>
                <span style={styles.tableCell}>
                  <LiquidBadge variant={perm.granted ? 'success' : 'error'} size="sm">
                    {perm.granted ? 'Yes' : 'No'}
                  </LiquidBadge>
                </span>
                <span style={styles.tableCell}>{perm.reason}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function renderProvenanceTab(securityEvents: SecurityEvent[]) {
  return (
    <div style={styles.tabContent}>
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
  );
}

function renderIntegrityTab(integrityCheck: IntegrityCheck | null, onVerifyIntegrity: () => void) {
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

function renderEventsTab(securityEvents: SecurityEvent[]) {
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

export function SecurityCenter() {
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [securityEvents, setSecurityEvents] = useState<SecurityEvent[]>([]);
  const [toolPermissions, setToolPermissions] = useState<ToolPermission[]>([]);
  const [integrityCheck, setIntegrityCheck] = useState<IntegrityCheck | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<ActiveTab>('overview');

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

  const fetchTaskSecurityData = useCallback(async (taskId: number) => {
    try {
      const [eventsRes, integrityRes] = await Promise.all([
        api.get<SecurityEvent[]>(`/api/tasks/${taskId}/provenance`),
        api.post<IntegrityCheck>(`/api/tasks/${taskId}/provenance/verify`, {}),
      ]);
      setSecurityEvents(eventsRes);
      setIntegrityCheck(integrityRes);
    } catch (err) {
      console.error('Failed to fetch security data:', err);
    }
  }, []);

  const fetchToolPermissions = useCallback(async (taskId: number) => {
    try {
      const planRes = await api.get<{ steps: Array<{ tool_id: string }> }>(`/api/tasks/${taskId}/plan`);
      if (planRes?.steps) {
        const tools = [...new Set(planRes.steps.map((s) => s.tool_id))];
        const permissions: ToolPermission[] = tools.map(toolId => ({
          tool_name: toolId,
          scope: `task:${taskId}`,
          granted: true,
          reason: 'Default analysis tool grant',
        }));
        setToolPermissions(permissions);
      } else {
        setToolPermissions([]);
      }
    } catch (err) {
      // Plan might not exist yet - this is not an error
      console.debug('No plan found for task, skipping tool permissions:', err);
      setToolPermissions([]);
    }
  }, []);

  useEffect(() => {
    fetchTasks();
    setLoading(false);
  }, [fetchTasks]);

  useEffect(() => {
    if (selectedTask) {
      fetchTaskSecurityData(selectedTask.id);
      fetchToolPermissions(selectedTask.id);
    } else {
      setSecurityEvents([]);
      setToolPermissions([]);
      setIntegrityCheck(null);
    }
  }, [selectedTask, fetchTaskSecurityData, fetchToolPermissions]);

  useEffect(() => {
    fetchTasks();
    const interval = setInterval(fetchTasks, 30000);
    return () => clearInterval(interval);
  }, [fetchTasks]);

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
          <p style={styles.loadingText}>Loading Security Center...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="security-center" style={styles.container}>
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
          <h1 style={styles.title}>Security Center</h1>
          <p style={styles.subtitle}>Inspect permissions, verify integrity, and explore provenance chains</p>
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
                  <GlassCard
                    key={task.id}
                    hoverable
                    onClick={() => setSelectedTask(task)}
                    style={{
                      ...styles.taskItem,
                      borderColor: selectedTask?.id === task.id ? colors.accent.cyan : colors.border.primary,
                      background: selectedTask?.id === task.id ? `rgba(0, 229, 255, 0.08)` : `rgba(255, 255, 255, 0.02)`,
                    }}
                    padding={3}
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
                  </GlassCard>
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
              </div>
              <div style={styles.tabContent}>
                <LiquidTabs
                  tabs={[
                    { id: 'overview', label: 'Overview' },
                    { id: 'permissions', label: 'Permissions' },
                    { id: 'provenance', label: 'Provenance' },
                    { id: 'integrity', label: 'Integrity' },
                    { id: 'events', label: 'Events' },
                  ]}
                  activeTab={activeTab}
                  onChange={(tabId: string) => setActiveTab(tabId as ActiveTab)}
                />
                {activeTab === 'overview' && renderOverviewTab(selectedTask, integrityCheck, () => handleVerifyIntegrity(selectedTask.id))}
                {activeTab === 'permissions' && renderPermissionsTab(toolPermissions)}
                {activeTab === 'provenance' && renderProvenanceTab(securityEvents)}
                {activeTab === 'integrity' && renderIntegrityTab(integrityCheck, () => handleVerifyIntegrity(selectedTask.id))}
                {activeTab === 'events' && renderEventsTab(securityEvents)}
              </div>
            </div>
          ) : (
            <div className="glass-panel-elevated glass-specular" style={styles.welcomePanel}>
              <div style={styles.welcomeContent}>
                <div style={styles.welcomeIcon}>🔐</div>
                <h2 style={styles.welcomeTitle}>Security & Provenance Center</h2>
                <p style={styles.welcomeText}>
                  Select a task from the sidebar to inspect its security posture,
                  tool permissions, provenance chain, and integrity verification.
                </p>
                <div style={styles.welcomeFeatures}>
                  {[
                    { icon: '🔍', title: 'Provenance Explorer', desc: 'Browse tamper-evident event chains with cryptographic integrity' },
                    { icon: '🛡️', title: 'Permission Matrix', desc: 'View least-privilege tool grants and authorization decisions' },
                    { icon: '✓', title: 'Integrity Verification', desc: 'Cryptographic verification of hash-linked provenance chains' },
                    { icon: '📋', title: 'Security Events', desc: 'Complete audit trail of all security-relevant operations' },
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
  tableContainer: {
    overflowX: 'auto',
  },
  tableHeader: {
    display: 'grid',
    gridTemplateColumns: '2fr 1fr 1fr 2fr',
    gap: spacing[4],
    padding: `${spacing[3]} ${spacing[4]}`,
    fontSize: typography.fontSize.xs,
    fontWeight: typography.fontWeight.bold,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
    color: colors.text.tertiary,
    borderBottom: `1px solid ${colors.border.tertiary}`,
    paddingBottom: spacing[3],
  },
  tableRow: {
    display: 'grid',
    gridTemplateColumns: '2fr 1fr 1fr 2fr',
    gap: spacing[4],
    padding: `${spacing[3]} ${spacing[4]}`,
    alignItems: 'center',
    borderBottom: `1px solid ${colors.border.tertiary}`,
  },
  tableCellHeader: {
    fontSize: typography.fontSize.xs,
    fontWeight: typography.fontWeight.bold,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
    color: colors.text.tertiary,
  },
  tableCell: {
    fontSize: typography.fontSize.sm,
    color: colors.text.primary,
  },
  eventTimeline: {
    display: 'flex',
    flexDirection: 'column',
    gap: spacing[3],
    maxHeight: '600px',
    overflowY: 'auto',
  },
  timelineEvent: {
    animation: 'fadeInUp 0.3s ease-out',
  },
  eventList: {
    display: 'flex',
    flexDirection: 'column',
    gap: spacing[3],
    maxHeight: '600px',
    overflowY: 'auto',
  },
  eventCard: {
    animation: 'fadeInUp 0.3s ease-out',
  },
  eventHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: spacing[4],
    marginBottom: spacing[3],
    flexWrap: 'wrap',
  },
  eventSequence: {
    padding: `${spacing[1]} ${spacing[3]}`,
    borderRadius: borderRadius.sm,
    fontSize: typography.fontSize.xs,
    fontWeight: typography.fontWeight.bold,
    background: `rgba(0, 229, 255, 0.1)`,
    color: colors.accent.cyan,
  },
  eventType: {
    padding: `${spacing[1]} ${spacing[3]}`,
    borderRadius: borderRadius.sm,
    fontSize: typography.fontSize.xs,
    fontWeight: typography.fontWeight.medium,
    textTransform: 'uppercase',
    background: `rgba(139, 92, 246, 0.1)`,
    color: colors.accent.violet,
  },
  eventActor: {
    fontSize: typography.fontSize.xs,
    color: colors.text.tertiary,
  },
  eventTime: {
    fontSize: typography.fontSize.xs,
    color: colors.text.muted,
    marginLeft: 'auto',
  },
  eventDetail: {
    marginTop: spacing[3],
  },
  detailsSummary: {
    cursor: 'pointer',
    fontSize: typography.fontSize.xs,
    fontWeight: typography.fontWeight.medium,
    color: colors.text.tertiary,
    marginBottom: spacing[2],
  },
  eventDetailJson: {
    background: `rgba(0, 0, 0, 0.3)`,
    border: `1px solid ${colors.border.tertiary}`,
    borderRadius: borderRadius.sm,
    padding: spacing[3],
    fontSize: typography.fontSize.xs,
    fontFamily: typography.fontFamily.mono,
    color: colors.text.primary,
    overflow: 'auto',
    maxHeight: '200px',
    margin: 0,
    whiteSpace: 'pre-wrap',
  },
  eventChain: {
    display: 'flex',
    alignItems: 'center',
    gap: spacing[3],
    marginTop: spacing[3],
    padding: spacing[3],
    background: `rgba(0, 0, 0, 0.2)`,
    borderRadius: borderRadius.sm,
  },
  chainLabel: {
    fontSize: typography.fontSize.xs,
    color: colors.text.tertiary,
  },
  chainDigest: {
    fontSize: typography.fontSize.xs,
    fontFamily: typography.fontFamily.mono,
    color: colors.accent.cyan,
    background: `rgba(0, 0, 0, 0.3)`,
    padding: `${spacing[1]} ${spacing[2]}`,
    borderRadius: borderRadius.sm,
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

export default SecurityCenter;
