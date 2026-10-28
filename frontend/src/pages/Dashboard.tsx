/** Dashboard for ATLAS-X research platform. */

import { useEffect, useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { useTutorial } from '../hooks/useTutorial';
import { api } from '../services/api';
import type { SystemStatus, Task } from '../types';
import { LiquidSpinner } from '../components/LiquidGlass';

export function Dashboard() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { replayTutorial } = useTutorial();
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const [statusRes, tasksRes] = await Promise.all([
          api.get<SystemStatus>('/api/system/status'),
          api.get<Task[]>('/api/tasks'),
        ]);
        setSystemStatus(statusRes);
        setTasks(tasksRes);
      } catch (err) {
        console.error('Failed to fetch dashboard data:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  // Compute system map states from actual task data
  const systemMapStates = useMemo(() => {
    if (tasks.length === 0) {
      return {
        Task: 'pending',
        Plan: 'pending',
        Authorization: 'pending',
        Tool: 'pending',
        Sandbox: 'pending',
        Execution: 'pending',
        Verification: 'pending',
        Artifact: 'pending',
        Provenance: 'pending',
      };
    }

    return {
      Task: tasks.length > 0 ? 'active' : 'pending',
      Plan: tasks.some(t => t.status === 'planned' || t.status === 'executing' || t.status === 'executed' || t.status === 'verified' || t.status === 'succeeded' || t.status === 'failed') ? 'active' : 'pending',
      Authorization: tasks.some(t => t.status !== 'pending') ? 'active' : 'pending',
      Tool: tasks.some(t => t.status === 'executed' || t.status === 'executing' || t.status === 'succeeded' || t.status === 'failed') ? 'active' : 'pending',
      Sandbox: tasks.some(t => t.status === 'executed' || t.status === 'executing' || t.status === 'succeeded' || t.status === 'failed') ? 'active' : 'pending',
      Execution: tasks.some(t => t.status === 'executed' || t.status === 'executing' || t.status === 'succeeded' || t.status === 'failed') ? 'active' : 'pending',
      Verification: tasks.some(t => t.status === 'verified' || t.status === 'verifying') ? 'active' : 'pending',
      Artifact: 'pending',
      Provenance: 'pending',
    };
  }, [tasks]);

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
          <p style={styles.loadingText}>Loading dashboard...</p>
        </div>
      </div>
    );
  }

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

      <header className="dashboard-topbar" style={styles.topBar}>
        <div style={styles.topBarLeft}>
          <span style={styles.logoIcon}>⬡</span>
          <span style={styles.logoText}>ATLAS-X</span>
          <span style={styles.badge}>Research Platform</span>
        </div>
        <div className="dashboard-topbar-right" style={styles.topBarRight}>
          <button onClick={replayTutorial} style={styles.helpButton}>
            Quick Tour
          </button>
          <div style={styles.userInfo}>
            <span style={styles.userName}>{user?.username}</span>
          </div>
          <button onClick={logout} style={styles.logoutButton}>
            Sign out
          </button>
        </div>
      </header>

      <div className="dashboard-layout">
        <aside style={styles.navRail}>
          <nav style={styles.nav}>
            <button style={styles.navItemActive}>Dashboard</button>
            <button onClick={() => navigate('/tasks/create')} style={styles.navItem}>
              Create Task
            </button>
            <button onClick={() => navigate('/playground')} style={styles.navItem}>
              Research Playground
            </button>
            <button onClick={() => navigate('/benchmarks')} style={styles.navItem}>
              Benchmarks
            </button>
            <button onClick={() => navigate('/security')} style={styles.navItem}>
              Security
            </button>
            <button onClick={() => navigate('/provenance')} style={styles.navItem}>
              Provenance
            </button>
          </nav>
        </aside>

        <div style={styles.contentWrapper}>
          <main style={styles.researchCanvas}>
            <div style={styles.hero}>
              <h1 style={styles.heroTitle}>Living Research Environment</h1>
              <p style={styles.heroText}>
                Investigate how authorization, sandboxing, independent verification, provenance integrity,
                and bounded recovery affect multi-step AI agent reliability and security.
              </p>
            </div>

            <div style={styles.systemMap}>
              <div style={styles.mapHeader}>
                <h2 style={styles.mapTitle}>Living System Map</h2>
                <span style={styles.mapSubtitle}>Interactive lifecycle visualization</span>
              </div>
              <div style={styles.mapContainer} className="glass-panel-elevated glass-specular">
                <div style={styles.mapGrid}>
                  {['Task', 'Plan', 'Authorization', 'Tool', 'Sandbox', 'Execution', 'Verification', 'Artifact', 'Provenance'].map((stage, index) => {
                    const state = systemMapStates[stage as keyof typeof systemMapStates] || 'pending';
                    const stateColors: Record<string, { bg: string; color: string; label: string; glow: string }> = {
                      active: {
                        bg: 'rgba(16, 185, 129, 0.15)',
                        color: '#10b981',
                        label: 'active',
                        glow: 'rgba(16, 185, 129, 0.4)'
                      },
                      pending: {
                        bg: 'rgba(245, 158, 11, 0.15)',
                        color: '#f59e0b',
                        label: 'pending',
                        glow: 'rgba(245, 158, 11, 0.4)'
                      },
                      failed: {
                        bg: 'rgba(239, 68, 68, 0.15)',
                        color: '#ef4444',
                        label: 'failed',
                        glow: 'rgba(239, 68, 68, 0.4)'
                      },
                    };
                    const stateStyle = stateColors[state] || stateColors.pending;
                    return (
                      <div key={stage} style={styles.mapNode} className="glass-panel-subtle glass-specular">
                        <div style={styles.nodeIcon}>{['📋', '📊', '🔐', '🔧', '🛡️', '⚡', '✓', '📦', '🔗'][index]}</div>
                        <span style={styles.nodeLabel}>{stage}</span>
                        <span style={{
                          ...styles.nodeStatus,
                          background: stateStyle.bg,
                          color: stateStyle.color,
                          boxShadow: `0 0 12px ${stateStyle.glow}`
                        }}>
                          {stateStyle.label}
                        </span>
                      </div>
                    );
                  })}
                </div>
                <div style={styles.mapOverlay}>
                  <p style={styles.mapOverlayText}>
                    Select a stage to inspect details. Real states will appear after task execution.
                  </p>
                </div>
              </div>
            </div>

            <div style={styles.quickActions}>
              <button onClick={() => navigate('/tasks/create')} style={styles.primaryAction}>
                Start Research Task
              </button>
              <button onClick={() => navigate('/playground')} style={styles.secondaryAction}>Research Playground</button>
              <button onClick={() => navigate('/benchmarks')} style={styles.secondaryAction}>View Benchmarks</button>
              <button onClick={() => navigate('/provenance')} style={styles.secondaryAction}>Inspect Provenance</button>
            </div>
          </main>

          <aside style={styles.inspectorPanel}>
            <div className="glass-panel glass-specular" style={styles.inspectorSection}>
              <h3 style={styles.inspectorTitle}>System Status</h3>
              {systemStatus && (
                <div style={styles.statusList}>
                  <div style={styles.statusItem}>
                    <span style={styles.statusLabel}>Sandbox</span>
                    <span style={styles.statusValue}>{systemStatus.sandbox}</span>
                  </div>
                  <div style={styles.statusItem}>
                    <span style={styles.statusLabel}>Verifier</span>
                    <span style={styles.statusValue}>{systemStatus.verifier}</span>
                  </div>
                  <div style={styles.statusItem}>
                    <span style={styles.statusLabel}>Provenance</span>
                    <span style={styles.statusValue}>{systemStatus.provenance}</span>
                  </div>
                  <div style={styles.statusItem}>
                    <span style={styles.statusLabel}>Model</span>
                    <span style={styles.statusValue}>{systemStatus.model}</span>
                  </div>
                </div>
              )}
            </div>

            <div className="glass-panel glass-specular" style={styles.inspectorSection}>
              <h3 style={styles.inspectorTitle}>Recent Tasks</h3>
              {tasks.length === 0 ? (
                <div style={styles.emptyState}>
                  <span style={styles.emptyIcon}>📋</span>
                  <p style={styles.emptyText}>No tasks yet</p>
                  <button onClick={() => navigate('/tasks/create')} style={styles.emptyButton}>
                    Create Task
                  </button>
                </div>
              ) : (
                <div style={styles.taskList}>
                  {tasks.slice(0, 5).map((task) => (
                    <div
                      key={task.id}
                      onClick={() => navigate(`/tasks/${task.id}`)}
                      style={styles.taskItem}
                      className="glass-card"
                    >
                      <span style={styles.taskTitle}>{task.title}</span>
                      <span style={styles.taskStatus}>{task.status}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="glass-panel glass-specular" style={styles.inspectorSection}>
              <h3 style={styles.inspectorTitle}>Research Overview</h3>
              <div style={styles.statsGrid}>
                <div style={styles.statItem} className="glass-panel-subtle">
                  <span style={styles.statValue}>{tasks.length}</span>
                  <span style={styles.statLabel}>Total Tasks</span>
                </div>
                <div style={styles.statItem} className="glass-panel-subtle">
                  <span style={styles.statValue}>0</span>
                  <span style={styles.statLabel}>Verified</span>
                </div>
                <div style={styles.statItem} className="glass-panel-subtle">
                  <span style={styles.statValue}>0</span>
                  <span style={styles.statLabel}>Failed</span>
                </div>
              </div>
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    minHeight: '100vh',
    width: '100%',
    minWidth: 0,
    backgroundColor: '#05070d',
    fontFamily: '"Times New Roman", Times, serif',
    color: '#f8fafc',
    display: 'flex',
    flexDirection: 'column',
  },
  topBar: {
    height: '64px',
    padding: '0 1.5rem',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    background: 'linear-gradient(180deg, rgba(10, 13, 23, 0.9) 0%, rgba(5, 7, 13, 0.95) 100%)',
    backdropFilter: 'blur(20px)',
    WebkitBackdropFilter: 'blur(20px)',
    borderBottom: '1px solid rgba(139, 92, 246, 0.15)',
    position: 'sticky',
    top: 0,
    zIndex: 100,
  },
  topBarLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: '1.5rem',
  },
  logoIcon: {
    fontSize: '1.5rem',
    color: '#00e5ff',
    textShadow: '0 0 20px rgba(0, 229, 255, 0.3)',
  },
  logoText: {
    fontSize: '1.25rem',
    fontWeight: '700',
    letterSpacing: '0.15em',
  },
  badge: {
    fontSize: '0.7rem',
    textTransform: 'uppercase',
    letterSpacing: '0.1em',
    color: '#94a3b8',
    padding: '0.25rem 0.5rem',
    background: 'rgba(255, 255, 255, 0.04)',
    borderRadius: '0.375rem',
    border: '1px solid rgba(139, 92, 246, 0.15)',
  },
  topBarRight: {
    display: 'flex',
    alignItems: 'center',
    gap: '1rem',
  },
  helpButton: {
    padding: '0.5rem 1rem',
    borderRadius: '0.5rem',
    border: '1px solid rgba(139, 92, 246, 0.15)',
    background: 'rgba(255, 255, 255, 0.04)',
    color: '#cbd5e1',
    cursor: 'pointer',
    fontSize: '0.8rem',
    fontWeight: '500',
    fontFamily: '"Times New Roman", Times, serif',
    transition: 'all 180ms ease-out',
  },
  userInfo: {
    padding: '0.5rem 1rem',
    borderRadius: '0.5rem',
    background: 'rgba(255, 255, 255, 0.04)',
  },
  userName: {
    fontSize: '0.8rem',
    fontWeight: '500',
    color: '#cbd5e1',
  },
  logoutButton: {
    padding: '0.5rem 1rem',
    borderRadius: '0.5rem',
    border: '1px solid rgba(0, 229, 255, 0.3)',
    background: 'transparent',
    color: '#00e5ff',
    cursor: 'pointer',
    fontSize: '0.75rem',
    fontFamily: '"Times New Roman", Times, serif',
    transition: 'all 180ms ease-out',
  },
  mainLayout: {
    display: 'grid',
    gridTemplateColumns: '240px 1fr 320px',
    flex: 1,
    minWidth: 0,
    minHeight: 0,
    gap: '1.5rem',
    padding: '1.5rem',
    alignItems: 'start',
  },
  navRail: {
    width: '100%',
    padding: '1.5rem',
    background: 'rgba(10, 13, 23, 0.6)',
    backdropFilter: 'blur(20px)',
    WebkitBackdropFilter: 'blur(20px)',
    borderRight: '1px solid rgba(139, 92, 246, 0.12)',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.5rem',
    minWidth: 0,
  },
  nav: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.5rem',
  },
  navItem: {
    padding: '0.75rem 1rem',
    borderRadius: '0.5rem',
    border: 'none',
    background: 'transparent',
    color: '#94a3b8',
    cursor: 'pointer',
    fontSize: '0.8rem',
    fontWeight: '500',
    fontFamily: '"Times New Roman", Times, serif',
    textAlign: 'left',
    transition: 'all 180ms ease-out',
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  },
  navItemActive: {
    padding: '0.75rem 1rem',
    borderRadius: '0.5rem',
    border: 'none',
    background: 'rgba(0, 229, 255, 0.1)',
    color: '#00e5ff',
    cursor: 'pointer',
    fontSize: '0.8rem',
    fontWeight: '600',
    fontFamily: '"Times New Roman", Times, serif',
    textAlign: 'left',
    boxShadow: 'inset 3px 0 0 #00e5ff',
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  },
  researchCanvas: {
    flex: 1,
    padding: '2.5rem',
    overflow: 'auto',
    minWidth: 0,
  },
  hero: {
    marginBottom: '2.5rem',
  },
  heroTitle: {
    fontSize: '2.5rem',
    fontWeight: '700',
    marginBottom: '1rem',
    marginTop: 0,
    background: 'linear-gradient(135deg, #f8fafc 0%, #00e5ff 50%, #8b5cf6 100%)',
    WebkitBackgroundClip: 'text',
    WebkitTextFillColor: 'transparent',
    backgroundClip: 'text',
    letterSpacing: '-0.02em',
  },
  heroText: {
    fontSize: '1.05rem',
    lineHeight: '1.75',
    color: '#cbd5e1',
    maxWidth: '700px',
  },
  systemMap: {
    marginBottom: '2.5rem',
  },
  mapHeader: {
    marginBottom: '1.5rem',
  },
  mapTitle: {
    fontSize: '1.25rem',
    fontWeight: '600',
    margin: 0,
  },
  mapSubtitle: {
    fontSize: '0.8rem',
    color: '#94a3b8',
  },
  mapContainer: {
    position: 'relative',
    minHeight: '320px',
    padding: '2rem',
  },
  mapGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
    gap: '1.25rem',
  },
  mapNode: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: '0.75rem',
    padding: '1.25rem',
    borderRadius: '0.75rem',
    cursor: 'pointer',
    transition: 'all 180ms ease-out',
  },
  nodeIcon: {
    fontSize: '2.25rem',
    filter: 'drop-shadow(0 0 12px currentColor)',
  },
  nodeLabel: {
    fontSize: '0.8rem',
    fontWeight: '500',
    color: '#cbd5e1',
    textAlign: 'center',
  },
  nodeStatus: {
    fontSize: '0.65rem',
    textTransform: 'uppercase',
    padding: '0.25rem 0.625rem',
    borderRadius: '9999px',
    fontWeight: 600,
    letterSpacing: '0.05em',
  },
  mapOverlay: {
    position: 'absolute',
    bottom: '1.5rem',
    left: '1.5rem',
    right: '1.5rem',
    padding: '1rem',
    borderRadius: '0.5rem',
    background: 'rgba(0, 0, 0, 0.5)',
    backdropFilter: 'blur(16px)',
    WebkitBackdropFilter: 'blur(16px)',
    border: '1px solid rgba(139, 92, 246, 0.15)',
  },
  mapOverlayText: {
    fontSize: '0.8rem',
    color: '#94a3b8',
    margin: 0,
  },
  quickActions: {
    display: 'flex',
    gap: '1rem',
    flexWrap: 'wrap',
    marginTop: '1rem',
  },
  primaryAction: {
    padding: '1rem 2rem',
    borderRadius: '0.5rem',
    border: 'none',
    background: 'linear-gradient(135deg, #00e5ff 0%, #3b82f6 100%)',
    color: '#05070d',
    fontSize: '0.95rem',
    fontWeight: '600',
    fontFamily: '"Times New Roman", Times, serif',
    cursor: 'pointer',
    boxShadow: '0 0 24px rgba(0, 229, 255, 0.4), 0 4px 16px rgba(0, 0, 0, 0.3)',
    transition: 'all 180ms ease-out',
  },
  secondaryAction: {
    padding: '1rem 2rem',
    borderRadius: '0.5rem',
    border: '1px solid rgba(139, 92, 246, 0.18)',
    background: 'rgba(255, 255, 255, 0.03)',
    backdropFilter: 'blur(16px)',
    WebkitBackdropFilter: 'blur(16px)',
    color: '#cbd5e1',
    fontSize: '0.95rem',
    fontWeight: '500',
    fontFamily: '"Times New Roman", Times, serif',
    cursor: 'pointer',
    transition: 'all 180ms ease-out',
  },
  inspectorPanel: {
    width: '100%',
    maxWidth: '360px',
    padding: '1.5rem',
    background: 'rgba(10, 13, 23, 0.6)',
    backdropFilter: 'blur(20px)',
    WebkitBackdropFilter: 'blur(20px)',
    borderLeft: '1px solid rgba(139, 92, 246, 0.12)',
    display: 'flex',
    flexDirection: 'column',
    gap: '1.25rem',
    overflow: 'auto',
    minWidth: 0,
  },
  inspectorSection: {
    padding: '1.5rem',
  },
  inspectorTitle: {
    fontSize: '0.95rem',
    fontWeight: '600',
    margin: '0 0 1rem 0',
    color: '#f8fafc',
  },
  statusList: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.75rem',
  },
  statusItem: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: '0.8rem',
  },
  statusLabel: {
    color: '#94a3b8',
  },
  statusValue: {
    color: '#cbd5e1',
    fontWeight: '500',
  },
  emptyState: {
    textAlign: 'center',
    padding: '1.5rem',
  },
  emptyIcon: {
    fontSize: '2.5rem',
    marginBottom: '0.75rem',
  },
  emptyText: {
    color: '#64748b',
    fontSize: '0.8rem',
    marginBottom: '1rem',
  },
  emptyButton: {
    padding: '0.5rem 1rem',
    borderRadius: '0.5rem',
    border: '1px solid rgba(0, 229, 255, 0.3)',
    background: 'transparent',
    color: '#00e5ff',
    cursor: 'pointer',
    fontSize: '0.75rem',
    fontFamily: '"Times New Roman", Times, serif',
    transition: 'all 180ms ease-out',
  },
  taskList: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.5rem',
  },
  taskItem: {
    padding: '0.75rem 1rem',
    borderRadius: '0.5rem',
    background: 'rgba(255, 255, 255, 0.02)',
    border: '1px solid rgba(139, 92, 246, 0.12)',
    cursor: 'pointer',
    transition: 'all 180ms ease-out',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  taskTitle: {
    fontSize: '0.8rem',
    fontWeight: '500',
    color: '#f8fafc',
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    maxWidth: '200px',
  },
  taskStatus: {
    fontSize: '0.7rem',
    color: '#64748b',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  statsGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(3, 1fr)',
    gap: '0.75rem',
  },
  statItem: {
    textAlign: 'center',
    padding: '1rem',
  },
  statValue: {
    fontSize: '1.5rem',
    fontWeight: '700',
    color: '#00e5ff',
    display: 'block',
  },
  statLabel: {
    fontSize: '0.65rem',
    color: '#64748b',
    textTransform: 'uppercase',
    letterSpacing: '0.1em',
    marginTop: '0.25rem',
  },
};

export default Dashboard;