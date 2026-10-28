/** Task detail page for ATLAS-X with complete task lifecycle. */



import React, { useEffect, useState, useCallback } from 'react';

import { useParams, useNavigate } from 'react-router-dom';

import { api } from '../services/api';

import type { Task } from '../types';

import { LiquidSpinner } from '../components/LiquidGlass';

import { AtlasXLogo } from '../components/LiquidGlassToggle';

import { LiquidButton, LiquidBadge } from '../components/LiquidGlass';

import { colors, typography, spacing, borderRadius, transitions } from '../styles/designTokens';

import { formatTimestamp } from '../utils/dates';



interface PlanStep {

  step_key: string;

  tool_id: string;

  input: Record<string, unknown>;

  depends_on: string[];

  produces_artifact_kind: string | null;

  action: string;

}



interface Plan {

  id: number;

  task_id: number;

  status: string;

  validated: boolean;

  model_id: string;

  steps: PlanStep[];

  created_at: string | null;

}



interface Execution {

  id: number;

  task_id: number;

  plan_id: number;

  plan_step_id: number | null;

  tool_id: string | null;

  invocation_id: string | null;

  status: string;

  result_json: string | null;

  error_code: string | null;

  error: string | null;

  origin: string;

  attempt: number;

  created_at: string | null;

  updated_at: string;

}



interface VerificationVerdict {

  execution_id: number;

  verification_id: number;

  plan_step_id: number | null;

  tool_id: string;

  step_key: string;

  passed: boolean;

  code: string;

  detail: string;

  result: Record<string, unknown> | null;

}



interface Verification {

  task_id: number;

  plan_id: number;

  verdict: string;

  task_status: string;

  verdicts: VerificationVerdict[];

  checked: number;

}



interface Artifact {

  id: number;

  execution_id: number;

  name: string;

  kind: string;

  size_bytes: number;

  source: string;

  metadata: Record<string, unknown> | null;

  created_at: string | null;

}



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

  detail_json: string | null;

  created_at: string | null;

}



interface ProvenanceVerification {

  task_id: number;

  verification_code: string;

  valid: boolean;

  failed_event_id: number | null;

  failed_event_sequence: number | null;

}



type ActiveTab = 'overview' | 'plan' | 'execution' | 'verification' | 'artifacts' | 'provenance';



export function TaskDetail() {

  const { id } = useParams<{ id: string }>();

  const navigate = useNavigate();

  const [task, setTask] = useState<Task | null>(null);

  const [plan, setPlan] = useState<Plan | null>(null);

  const [executions, setExecutions] = useState<Execution[]>([]);

  const [verification, setVerification] = useState<Verification | null>(null);

  const [artifacts, setArtifacts] = useState<Artifact[]>([]);

  const [provenance, setProvenance] = useState<ProvenanceEvent[]>([]);

  const [provenanceVerification, setProvenanceVerification] = useState<ProvenanceVerification | null>(null);

  const [loading, setLoading] = useState(true);

  const [error, setError] = useState('');

  const [activeTab, setActiveTab] = useState<ActiveTab>('overview');

  const [actionLoading, setActionLoading] = useState<string | null>(null);



  const fetchTask = useCallback(async () => {

    try {

      const taskData = await api.get<Task>(`/api/tasks/${id}`);

      setTask(taskData);

    } catch {

      setError('Failed to load task');

    }

  }, [id]);



  const fetchPlan = useCallback(async () => {

    try {

      const planData = await api.get<Plan>(`/api/tasks/${id}/plan`);

      setPlan(planData);

    } catch {

      setPlan(null);

    }

  }, [id]);



  const fetchExecutions = useCallback(async () => {

    try {

      const execData = await api.get<Execution[]>(`/api/tasks/${id}/executions`);

      setExecutions(execData);

    } catch {

      setExecutions([]);

    }

  }, [id]);



  const fetchVerification = useCallback(async () => {

    try {

      const verificationData = await api.post<Verification>(`/api/tasks/${id}/verify`, {});

      setVerification(verificationData);

    } catch {

      setVerification(null);

    }

  }, [id]);



  const fetchArtifacts = useCallback(async () => {

    try {

      const artifactData = await api.get<Artifact[]>(`/api/tasks/${id}/artifacts`);

      setArtifacts(artifactData);

    } catch {

      setArtifacts([]);

    }

  }, [id]);



  const fetchProvenance = useCallback(async () => {

    try {

      const provData = await api.get<ProvenanceEvent[]>(`/api/tasks/${id}/provenance`);

      setProvenance(provData);

    } catch {

      setProvenance([]);

    }

  }, [id]);



  const fetchProvenanceVerification = useCallback(async () => {

    try {

      const provVerify = await api.post<ProvenanceVerification>(`/api/tasks/${id}/provenance/verify`, {});

      setProvenanceVerification(provVerify);

    } catch {

      setProvenanceVerification(null);

    }

  }, [id]);



  useEffect(() => {

    const loadAll = async () => {

      setLoading(true);

      setError('');

      await Promise.all([

        fetchTask(),

        fetchPlan(),

        fetchExecutions(),

        fetchArtifacts(),

        fetchProvenance(),

        fetchProvenanceVerification(),

      ]);

      setLoading(false);

    };

    loadAll();

  }, [id, fetchTask, fetchPlan, fetchExecutions, fetchArtifacts, fetchProvenance, fetchProvenanceVerification]);



  // Fetch verification when verification tab becomes active

  useEffect(() => {

    if (activeTab === 'verification' && !verification) {

      fetchVerification();

    }

  }, [activeTab, verification, fetchVerification]);



  const handleGeneratePlan = useCallback(async () => {

    setActionLoading('plan');

    try {

      await api.post<{ id: number }>(`/api/tasks/${id}/plan`, {});

      await fetchPlan();

      await fetchTask(); // Refresh task status

    } catch {

      setError('Failed to generate plan');

    } finally {

      setActionLoading(null);

    }

  }, [id, fetchPlan, fetchTask]);



  const handleExecute = useCallback(async () => {

    setActionLoading('execute');

    try {

      await api.post<{ task_id: number }>(`/api/tasks/${id}/execute`, {});

      await Promise.all([fetchTask(), fetchPlan(), fetchExecutions(), fetchVerification()]);

    } catch {

      setError('Failed to execute task');

    } finally {

      setActionLoading(null);

    }

  }, [id, fetchTask, fetchPlan, fetchExecutions, fetchVerification]);



  const handleVerify = useCallback(async () => {

    setActionLoading('verify');

    try {

      await api.post<{ task_id: number }>(`/api/tasks/${id}/verify`, {});

      await Promise.all([fetchTask(), fetchVerification(), fetchProvenance()]);

    } catch {

      setError('Failed to verify task');

    } finally {

      setActionLoading(null);

    }

  }, [id, fetchTask, fetchVerification, fetchProvenance]);



  const handleVerifyProvenance = useCallback(async () => {

    try {

      await fetchProvenanceVerification();

    } catch {

      setError('Failed to verify provenance');

    }

  }, [fetchProvenanceVerification]);



  if (loading) {

    return (

      <div className="ambient-bg">

        <div className="ambient-grid"></div>

        <div className="ambient-orbs">

          <div className="ambient-orb ambient-orb-1"></div>

          <div className="ambient-orb ambient-orb-2"></div>

          <div className="ambient-orb ambient-orb-3"></div>

          <div className="ambient-orb ambient-orb-4"></div>

        </div>

        <div style={styles.loadingState}>

          <LiquidSpinner size="lg" color="cyan" />

          <p style={styles.loadingText}>Loading task...</p>

        </div>

      </div>

    );

  }



  if (error) {

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

        <div style={styles.errorState} className="glass-panel-elevated glass-specular">

          <div style={styles.errorIcon}>⚠</div>

          <h3 style={styles.errorTitle}>Error Loading Task</h3>

          <p style={styles.errorMessage}>{error}</p>

          <LiquidButton variant="secondary" onClick={() => navigate('/dashboard')} style={styles.retryButton}>

            Back to Dashboard

          </LiquidButton>

        </div>

      </div>

    );

  }



  if (!task) {

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

        <div style={styles.errorState} className="glass-panel-elevated glass-specular">

          <div style={styles.errorIcon}>📋</div>

          <h3 style={styles.errorTitle}>Task Not Found</h3>

          <p style={styles.errorMessage}>The requested task could not be found.</p>

          <LiquidButton variant="secondary" onClick={() => navigate('/dashboard')} style={styles.retryButton}>

            Back to Dashboard

          </LiquidButton>

        </div>

      </div>

    );

  }



  const statusColor = {

    pending: colors.accent.warning,

    planned: colors.accent.blue,

    executing: colors.accent.cyan,

    executed: colors.accent.blue,

    verifying: colors.accent.violet,

    verified: colors.accent.success,

    succeeded: colors.accent.success,

    failed: colors.accent.error,

  }[task.status] || colors.text.tertiary;



  const canGeneratePlan = task.status === 'pending';

  const canExecute = task.status === 'planned' && plan?.validated;

  const canVerify = task.status === 'executed';



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

      <header style={styles.header}>

        <LiquidButton variant="ghost" onClick={() => navigate('/dashboard')} icon="←" iconPosition="left" size="sm">

          Back to Dashboard

        </LiquidButton>

        <AtlasXLogo size="sm" animated={false} />

        <h1 style={styles.title}>{task.title}</h1>

        <LiquidBadge variant="cyan" style={{ ...styles.statusBadge, background: `${statusColor}1A`, color: statusColor }}>

          {task.status.toUpperCase()}

        </LiquidBadge>

      </header>



      <main style={styles.main}>

        {/* Task Overview */}

        <div className="glass-panel-elevated glass-specular" style={styles.glassPanel}>

          <div style={styles.panelHeader}>

            <h2 style={styles.panelTitle}>Task Overview</h2>

          </div>

          <div style={styles.taskInfo}>

            <div style={styles.infoItem} className="glass-panel-subtle">

              <span style={styles.infoLabel}>ID:</span>

              <span style={styles.infoValue}>{task.id}</span>

            </div>

            <div style={styles.infoItem} className="glass-panel-subtle">

              <span style={styles.infoLabel}>Created:</span>

              <span style={styles.infoValue}>{formatTimestamp(task.created_at)}</span>

            </div>

            <div style={styles.infoItem} className="glass-panel-subtle">

              <span style={styles.infoLabel}>Status:</span>

              <span style={{ ...styles.infoValue, color: statusColor, fontWeight: typography.fontWeight.semibold }}>{task.status}</span>

            </div>

          </div>

          <div style={styles.goalSection}>

            <h3 style={styles.goalTitle}>Research Goal</h3>

            <p style={styles.goalText}>{task.goal}</p>

          </div>



          {/* Action Buttons */}

          <div style={styles.actionBar}>

            {canGeneratePlan && (

              <LiquidButton

                onClick={handleGeneratePlan}

                disabled={actionLoading === 'plan'}

                loading={actionLoading === 'plan'}

                style={styles.primaryAction}

              >

                {actionLoading === 'plan' ? 'Generating Plan...' : 'Generate Plan'}

              </LiquidButton>

            )}

            {canExecute && (

              <LiquidButton

                onClick={handleExecute}

                disabled={actionLoading === 'execute'}

                loading={actionLoading === 'execute'}

                variant="danger"

                style={styles.dangerAction}

              >

                {actionLoading === 'execute' ? 'Executing...' : 'Execute Plan'}

              </LiquidButton>

            )}

            {canVerify && (

              <LiquidButton

                onClick={handleVerify}

                disabled={actionLoading === 'verify'}

                loading={actionLoading === 'verify'}

                style={styles.primaryAction}

              >

                {actionLoading === 'verify' ? 'Verifying...' : 'Verify Results'}

              </LiquidButton>

            )}

          </div>

        </div>



        {/* Tabs */}

        <div style={styles.tabs} className="glass-panel-subtle">

          {[

            { id: 'overview', label: 'Overview', disabled: false },

            { id: 'plan', label: 'Plan', disabled: !plan },

            { id: 'execution', label: 'Execution', disabled: executions.length === 0 },

            { id: 'verification', label: 'Verification', disabled: !verification },

            { id: 'artifacts', label: 'Artifacts', disabled: artifacts.length === 0 },

            { id: 'provenance', label: 'Provenance', disabled: provenance.length === 0 },

          ].map((tab) => (

            <button

              key={tab.id}

              onClick={() => !tab.disabled && setActiveTab(tab.id as ActiveTab)}

              disabled={tab.disabled}

              style={{

                ...styles.tab,

                ...(activeTab === tab.id ? styles.tabActive : {}),

                ...(tab.disabled ? styles.tabDisabled : {}),

              }}

            >

              {tab.label}

            </button>

          ))}

        </div>



        {/* Tab Content */}

        {activeTab === 'overview' && (

          <div className="glass-panel-elevated glass-specular" style={styles.glassPanel}>

            <h3 style={styles.sectionTitle}>Task Summary</h3>

            <div style={styles.summaryGrid}>

              <div style={styles.summaryItem} className="glass-panel-subtle">

                <span style={styles.summaryLabel}>Total Executions</span>

                <span style={styles.summaryValue}>{executions.length}</span>

              </div>

              <div style={styles.summaryItem} className="glass-panel-subtle">

                <span style={styles.summaryLabel}>Plan Steps</span>

                <span style={styles.summaryValue}>{plan?.steps.length || 0}</span>

              </div>

              <div style={styles.summaryItem} className="glass-panel-subtle">

                <span style={styles.summaryLabel}>Artifacts</span>

                <span style={styles.summaryValue}>{artifacts.length}</span>

              </div>

              <div style={styles.summaryItem} className="glass-panel-subtle">

                <span style={styles.summaryLabel}>Provenance Events</span>

                <span style={styles.summaryValue}>{provenance.length}</span>

              </div>

              <div style={styles.summaryItem} className="glass-panel-subtle">

                <span style={styles.summaryLabel}>Verification</span>

                <span style={{ ...styles.summaryValue, color: verification?.verdict === 'pass' ? colors.accent.success : verification?.verdict === 'fail' ? colors.accent.error : colors.text.tertiary }}>

                  {verification?.verdict?.toUpperCase() || 'PENDING'}

                </span>

              </div>

              <div style={styles.summaryItem} className="glass-panel-subtle">

                <span style={styles.summaryLabel}>Provenance Chain</span>

                <span style={{ ...styles.summaryValue, color: provenanceVerification?.valid ? colors.accent.success : colors.accent.error }}>

                  {provenanceVerification?.valid ? 'VALID' : provenanceVerification ? 'INVALID' : 'UNCHECKED'}

                </span>

              </div>

            </div>

          </div>

        )}



        {activeTab === 'plan' && plan && (

          <div className="glass-panel-elevated glass-specular" style={styles.glassPanel}>

            <div style={styles.panelHeader}>

              <h2 style={styles.panelTitle}>Execution Plan</h2>

              <div style={styles.planMeta}>

                <span style={styles.metaItem}>Model: <strong>{plan.model_id}</strong></span>

                <span style={styles.metaItem}>Status: <strong>{plan.status}</strong></span>

                <span style={styles.metaItem}>Validated: <strong style={{ color: plan.validated ? colors.accent.success : colors.accent.warning }}>{plan.validated ? 'Yes' : 'No'}</strong></span>

              </div>

            </div>

            {plan.steps.length === 0 ? (

              <div style={styles.placeholder} className="glass-panel-subtle">

                <div style={styles.placeholderIcon}>📋</div>

                <p style={styles.placeholderText}>This plan has no steps.</p>

              </div>

            ) : (

              <div style={styles.stepList}>

                {plan.steps.map((step, index) => (

                  <div key={step.step_key} className="glass-panel-subtle glass-specular" style={styles.stepCard}>

                    <div style={styles.stepHeader}>

                      <span style={styles.stepNumber}>Step {index + 1}</span>

                      <span style={styles.stepKey}>{step.step_key}</span>

                      <LiquidBadge variant="cyan" size="sm">{step.tool_id}</LiquidBadge>

                    </div>

                    <div style={styles.stepDetails}>

                      <div style={styles.detailRow}>

                        <span style={styles.detailLabel}>Action:</span>

                        <span style={styles.detailValue}>{step.action}</span>

                      </div>

                      <div style={styles.detailRow}>

                        <span style={styles.detailLabel}>Produces:</span>

                        <span style={styles.detailValue}>{step.produces_artifact_kind || 'None'}</span>

                      </div>

                      <div style={styles.detailRow}>

                        <span style={styles.detailLabel}>Depends on:</span>

                        <span style={styles.detailValue}>{(step.depends_on && step.depends_on.length > 0) ? step.depends_on.join(', ') : 'None'}</span>

                      </div>

                      <div style={styles.detailRow}>

                        <span style={styles.detailLabel}>Input:</span>

                        <pre style={styles.inputJson}>{JSON.stringify(step.input, null, 2)}</pre>

                      </div>

                    </div>

                  </div>

                ))}

              </div>

            )}

          </div>

        )}



        {activeTab === 'execution' && (

          <div className="glass-panel-elevated glass-specular" style={styles.glassPanel}>

            <div style={styles.panelHeader}>

              <h2 style={styles.panelTitle}>Execution Status</h2>

            </div>

            {executions.length === 0 ? (

              <div style={styles.placeholder} className="glass-panel-subtle">

                <div style={styles.placeholderIcon}>⚡</div>

                <p style={styles.placeholderText}>No executions yet. Execute the plan to run the task.</p>

              </div>

            ) : (

              <div style={styles.executionList}>

                {executions.map((exec) => (

                  <div key={exec.id} className="glass-panel-subtle glass-specular" style={styles.executionCard}>

                    <div style={styles.executionHeader}>

                      <span style={styles.executionId}>Execution #{exec.id}</span>

                      <LiquidBadge

                        variant={exec.status === 'succeeded' ? 'success' : exec.status === 'failed' ? 'error' : 'cyan'}

                        size="sm"

                      >

                        {exec.status.toUpperCase()}

                      </LiquidBadge>

                    </div>

                    <div style={styles.executionDetails}>

                      <div style={styles.detailRow}>

                        <span style={styles.detailLabel}>Tool:</span>

                        <span style={styles.detailValue}>{exec.tool_id || 'N/A'}</span>

                      </div>

                      <div style={styles.detailRow}>

                        <span style={styles.detailLabel}>Plan Step:</span>

                        <span style={styles.detailValue}>{exec.plan_step_id || 'N/A'}</span>

                      </div>

                      <div style={styles.detailRow}>

                        <span style={styles.detailLabel}>Invocation:</span>

                        <span style={styles.detailValue}>{exec.invocation_id || 'N/A'}</span>

                      </div>

                      <div style={styles.detailRow}>

                        <span style={styles.detailLabel}>Attempt:</span>

                        <span style={styles.detailValue}>{exec.attempt}</span>

                      </div>

                      {exec.error_code && (

                        <div style={styles.detailRow}>

                          <span style={styles.detailLabel}>Error:</span>

                          <span style={{ ...styles.detailValue, color: colors.accent.error }}>{exec.error_code}: {exec.error}</span>

                        </div>

                      )}

                      {exec.result_json && (

                        <div style={styles.detailRow}>

                          <span style={styles.detailLabel}>Result:</span>

                          <pre style={styles.inputJson}>{exec.result_json}</pre>

                        </div>

                      )}

                    </div>

                  </div>

                ))}

              </div>

            )}

          </div>

        )}



        {activeTab === 'verification' && verification && (

          <div className="glass-panel-elevated glass-specular" style={styles.glassPanel}>

            <div style={styles.panelHeader}>

              <h2 style={styles.panelTitle}>Verification Results</h2>

              <LiquidBadge

                variant={verification.verdict === 'pass' ? 'success' : 'error'}

                size="sm"

              >

                {verification.verdict.toUpperCase()}

              </LiquidBadge>

            </div>

            <div style={styles.verificationSummary}>

              <div style={styles.summaryItem} className="glass-panel-subtle">

                <span style={styles.summaryLabel}>Checked</span>

                <span style={styles.summaryValue}>{verification.checked}</span>

              </div>

              <div style={styles.summaryItem} className="glass-panel-subtle">

                <span style={styles.summaryLabel}>Passed</span>

                <span style={{ ...styles.summaryValue, color: colors.accent.success }}>{verification.verdicts.filter(v => v.passed).length}</span>

              </div>

              <div style={styles.summaryItem} className="glass-panel-subtle">

                <span style={styles.summaryLabel}>Failed</span>

                <span style={{ ...styles.summaryValue, color: colors.accent.error }}>{verification.verdicts.filter(v => !v.passed).length}</span>

              </div>

            </div>

            <div style={styles.verificationList}>

              {verification.verdicts.map((v) => (

                <div key={v.execution_id} className="glass-panel-subtle glass-specular" style={styles.verificationCard}>

                  <div style={styles.verificationHeader}>

                    <span style={styles.verificationStep}>{v.step_key}</span>

                    <LiquidBadge variant="cyan" size="sm">{v.tool_id}</LiquidBadge>

                    <LiquidBadge

                      variant={v.passed ? 'success' : 'error'}

                      size="sm"

                    >

                      {v.passed ? 'PASS' : 'FAIL'}

                    </LiquidBadge>

                  </div>

                  <div style={styles.verificationDetails}>

                    <div style={styles.detailRow}>

                      <span style={styles.detailLabel}>Code:</span>

                      <span style={styles.detailValue}>{v.code}</span>

                    </div>

                    <div style={styles.detailRow}>

                      <span style={styles.detailLabel}>Detail:</span>

                      <span style={styles.detailValue}>{v.detail}</span>

                    </div>

                    {v.result && (

                      <div style={styles.detailRow}>

                        <span style={styles.detailLabel}>Result:</span>

                        <pre style={styles.inputJson}>{JSON.stringify(v.result, null, 2)}</pre>

                      </div>

                    )}

                  </div>

                </div>

              ))}

            </div>

          </div>

        )}



        {activeTab === 'artifacts' && (

          <div className="glass-panel-elevated glass-specular" style={styles.glassPanel}>

            <div style={styles.panelHeader}>

              <h2 style={styles.panelTitle}>Artifacts</h2>

            </div>

            {artifacts.length === 0 ? (

              <div style={styles.placeholder} className="glass-panel-subtle">

                <div style={styles.placeholderIcon}>📦</div>

                <p style={styles.placeholderText}>No artifacts generated yet.</p>

              </div>

            ) : (

              <div style={styles.artifactList}>

                {artifacts.map((artifact) => (

                  <div key={artifact.id} className="glass-panel-subtle glass-specular" style={styles.artifactCard}>

                    <div style={styles.artifactHeader}>

                      <span style={styles.artifactName}>{artifact.name}</span>

                      <LiquidBadge variant="cyan" size="sm">{artifact.kind}</LiquidBadge>

                    </div>

                    <div style={styles.artifactDetails}>

                      <div style={styles.detailRow}>

                        <span style={styles.detailLabel}>Size:</span>

                        <span style={styles.detailValue}>{artifact.size_bytes} bytes</span>

                      </div>

                      <div style={styles.detailRow}>

                        <span style={styles.detailLabel}>Source:</span>

                        <span style={styles.detailValue}>{artifact.source}</span>

                      </div>

                      <div style={styles.detailRow}>

                        <span style={styles.detailLabel}>Created:</span>

                        <span style={styles.detailValue}>{formatTimestamp(artifact.created_at)}</span>

                      </div>

                      {artifact.metadata && (

                        <div style={styles.detailRow}>

                          <span style={styles.detailLabel}>Metadata:</span>

                          <pre style={styles.inputJson}>{JSON.stringify(artifact.metadata, null, 2)}</pre>

                        </div>

                      )}

                    </div>

                  </div>

                ))}

              </div>

            )}

          </div>

        )}



        {activeTab === 'provenance' && (

          <div className="glass-panel-elevated glass-specular" style={styles.glassPanel}>

            <div style={styles.panelHeader}>

              <h2 style={styles.panelTitle}>Provenance Chain</h2>

              <LiquidButton

                onClick={handleVerifyProvenance}

                variant="secondary"

                style={styles.secondaryAction}

              >

                Verify Chain Integrity

              </LiquidButton>

            </div>

            {provenanceVerification && (

              <div style={{

                ...styles.provenanceStatus,

                background: provenanceVerification.valid ? `${colors.accent.success}1A` : `${colors.accent.error}1A`,

                borderColor: provenanceVerification.valid ? colors.accent.success : colors.accent.error,

              }}>

                <span style={{ color: provenanceVerification.valid ? colors.accent.success : colors.accent.error, fontWeight: typography.fontWeight.semibold }}>

                  {provenanceVerification.valid ? '✓ CHAIN VALID' : '✗ CHAIN INVALID'}

                </span>

                {provenanceVerification.failed_event_id && (

                  <span style={{ color: colors.accent.error }}>

                    Failed at event #{provenanceVerification.failed_event_id} (sequence {provenanceVerification.failed_event_sequence})

                  </span>

                )}

              </div>

            )}

            {provenance.length === 0 ? (

              <div style={styles.placeholder} className="glass-panel-subtle">

                <div style={styles.placeholderIcon}>🔗</div>

                <p style={styles.placeholderText}>No provenance events recorded yet.</p>

              </div>

            ) : (

              <div style={styles.provenanceList}>

                {provenance.map((event) => (

                  <div key={event.id} className="glass-panel-subtle glass-specular" style={styles.provenanceCard}>

                    <div style={styles.provenanceHeader}>

                      <span style={styles.provenanceSequence}>#{event.sequence_no}</span>

                      <span style={styles.provenanceType}>{event.event_type}</span>

                      <span style={styles.provenanceActor}>{event.actor}</span>

                      <span style={styles.provenanceTime}>{formatTimestamp(event.created_at)}</span>

                    </div>

                    {event.detail_json && (

                      <div style={styles.provenanceDetail}>

                        <pre style={styles.inputJson}>{event.detail_json}</pre>

                      </div>

                    )}

                    <div style={styles.provenanceChain}>

                      <span style={styles.chainLabel}>Chain Digest:</span>

                      <code style={styles.chainDigest}>{event.chain_digest ? event.chain_digest.slice(0, 32) : '-'}...</code>

                    </div>

                  </div>

                ))}

              </div>

            )}

          </div>

        )}

      </main>

    </div>

  );

}



const styles: Record<string, React.CSSProperties> = {

  container: {

    minHeight: '100vh',

    backgroundColor: colors.background.primary,

    fontFamily: typography.fontFamily.primary,

    color: colors.text.primary,

  },

  loadingState: {

    display: 'flex',

    flexDirection: 'column',

    alignItems: 'center',

    justifyContent: 'center',

    minHeight: '60vh',

  },

  loadingText: {

    marginTop: spacing[4],

    color: colors.text.tertiary,

  },

  errorState: {

    display: 'flex',

    flexDirection: 'column',

    alignItems: 'center',

    justifyContent: 'center',

    minHeight: '60vh',

    padding: spacing[8],

  },

  errorIcon: {

    fontSize: typography.fontSize['4xl'],

    marginBottom: spacing[4],

  },

  errorTitle: {

    fontSize: typography.fontSize.xl,

    fontWeight: typography.fontWeight.semibold,

    margin: `0 0 ${spacing[3]} 0`,

    color: colors.text.secondary,

  },

  errorMessage: {

    color: colors.text.tertiary,

    marginBottom: spacing[6],

  },

  retryButton: {

    padding: `${spacing[3]} ${spacing[6]}`,

    borderRadius: borderRadius.base,

    border: `1px solid ${colors.accent.cyan}`,

    background: 'transparent',

    color: colors.accent.cyan,

    cursor: 'pointer',

    transition: `all ${transitions.base}`,

  },

  header: {

    padding: `${spacing[6]} ${spacing[12]}`,

    borderBottom: `1px solid ${colors.border.tertiary}`,

    display: 'flex',

    alignItems: 'center',

    gap: spacing[6],

  },

  backButton: {

    padding: `${spacing[3]} ${spacing[5]}`,

    fontSize: typography.fontSize.sm,

  },

  title: {

    fontSize: typography.fontSize['2xl'],

    fontWeight: typography.fontWeight.bold,

    margin: 0,

    flex: 1,

  },

  statusBadge: {

    padding: `${spacing[2]} ${spacing[4]}`,

    borderRadius: borderRadius.sm,

    fontSize: typography.fontSize.sm,

  },

  main: {

    padding: spacing[12],

    maxWidth: '1200px',

    margin: '0 auto',

  },

  glassPanel: {

    padding: spacing[8],

  },

  panelHeader: {

    display: 'flex',

    alignItems: 'center',

    justifyContent: 'space-between',

    marginBottom: spacing[6],

  },

  panelTitle: {

    fontSize: typography.fontSize.xl,

    fontWeight: typography.fontWeight.semibold,

    margin: 0,

  },

  taskInfo: {

    display: 'grid',

    gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',

    gap: spacing[6],

    marginBottom: spacing[8],

  },

  infoItem: {

    display: 'flex',

    flexDirection: 'column',

    gap: spacing[2],

  },

  infoLabel: {

    fontSize: typography.fontSize.xs,

    textTransform: 'uppercase',

    letterSpacing: '0.1em',

    color: colors.text.tertiary,

  },

  infoValue: {

    fontSize: typography.fontSize.base,

    fontWeight: typography.fontWeight.medium,

    color: colors.text.primary,

  },

  goalSection: {

    borderTop: `1px solid ${colors.border.tertiary}`,

    paddingTop: spacing[6],

  },

  goalTitle: {

    fontSize: typography.fontSize.base,

    fontWeight: typography.fontWeight.semibold,

    margin: `0 0 ${spacing[3]} 0`,

    color: colors.text.secondary,

  },

  goalText: {

    fontSize: typography.fontSize.base,

    lineHeight: typography.lineHeight.relaxed,

    color: colors.text.secondary,

  },

  actionBar: {

    display: 'flex',

    gap: spacing[4],

    marginTop: spacing[6],

    paddingTop: spacing[6],

    borderTop: `1px solid ${colors.border.tertiary}`,

  },

  tabs: {

    display: 'flex',

    gap: spacing[2],

    marginBottom: spacing[6],

    borderBottom: `1px solid ${colors.border.tertiary}`,

    paddingBottom: spacing[2],

    flexWrap: 'wrap',

  },

  tab: {

    padding: `${spacing[3]} ${spacing[6]}`,

    borderRadius: borderRadius.base,

    border: `1px solid ${colors.border.tertiary}`,

    background: 'transparent',

    color: colors.text.secondary,

    cursor: 'pointer',

    fontSize: typography.fontSize.sm,

    fontWeight: typography.fontWeight.medium,

    transition: `all ${transitions.base}`,

  },

  tabActive: {

    background: `rgba(0, 229, 255, 0.1)`,

    borderColor: colors.accent.cyan,

    color: colors.accent.cyan,

  },

  tabDisabled: {

    opacity: 0.4,

    cursor: 'not-allowed',

  },

  placeholder: {

    padding: spacing[12],

    textAlign: 'center',

  },

  placeholderIcon: {

    fontSize: typography.fontSize['4xl'],

    marginBottom: spacing[4],

  },

  placeholderText: {

    color: colors.text.tertiary,

    fontSize: typography.fontSize.base,

  },

  sectionTitle: {

    fontSize: typography.fontSize.lg,

    fontWeight: typography.fontWeight.semibold,

    margin: `0 0 ${spacing[4]} 0`,

    color: colors.text.primary,

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

  planMeta: {

    display: 'flex',

    gap: spacing[6],

    flexWrap: 'wrap',

    marginTop: spacing[4],

  },

  metaItem: {

    fontSize: typography.fontSize.sm,

    color: colors.text.secondary,

  },

  stepList: {

    display: 'flex',

    flexDirection: 'column',

    gap: spacing[4],

  },

  stepCard: {

    padding: spacing[6],

  },

  stepHeader: {

    display: 'flex',

    alignItems: 'center',

    gap: spacing[4],

    marginBottom: spacing[4],

  },

  stepNumber: {

    fontSize: typography.fontSize.sm,

    fontWeight: typography.fontWeight.bold,

    color: colors.accent.cyan,

  },

  stepKey: {

    fontSize: typography.fontSize.sm,

    fontWeight: typography.fontWeight.medium,

    color: colors.text.primary,

  },

  stepTool: {

    padding: `${spacing[1]} ${spacing[3]}`,

    borderRadius: borderRadius.sm,

    fontSize: typography.fontSize.xs,

    fontWeight: typography.fontWeight.medium,

    textTransform: 'uppercase',

  },

  stepDetails: {

    display: 'flex',

    flexDirection: 'column',

    gap: spacing[3],

  },

  detailRow: {

    display: 'flex',

    gap: spacing[4],

    alignItems: 'flex-start',

  },

  detailLabel: {

    fontSize: typography.fontSize.sm,

    color: colors.text.tertiary,

    minWidth: '120px',

  },

  detailValue: {

    fontSize: typography.fontSize.sm,

    color: colors.text.secondary,

    flex: 1,

    wordBreak: 'break-word',

  },

  inputJson: {

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

  executionList: {

    display: 'flex',

    flexDirection: 'column',

    gap: spacing[4],

  },

  executionCard: {

    padding: spacing[6],

  },

  executionHeader: {

    display: 'flex',

    justifyContent: 'space-between',

    alignItems: 'center',

    marginBottom: spacing[4],

  },

  executionId: {

    fontSize: typography.fontSize.base,

    fontWeight: typography.fontWeight.semibold,

    color: colors.text.primary,

  },

  executionStatus: {

    padding: `${spacing[1]} ${spacing[3]}`,

    borderRadius: borderRadius.sm,

    fontSize: typography.fontSize.xs,

    fontWeight: typography.fontWeight.bold,

    textTransform: 'uppercase',

  },

  executionDetails: {

    display: 'flex',

    flexDirection: 'column',

    gap: spacing[3],

  },

  verificationSummary: {

    display: 'flex',

    gap: spacing[6],

    marginBottom: spacing[6],

    padding: spacing[4],

  },

  verificationList: {

    display: 'flex',

    flexDirection: 'column',

    gap: spacing[4],

  },

  verificationCard: {

    padding: spacing[6],

  },

  verificationHeader: {

    display: 'flex',

    alignItems: 'center',

    gap: spacing[4],

    marginBottom: spacing[4],

  },

  verificationStep: {

    fontSize: typography.fontSize.sm,

    fontWeight: typography.fontWeight.medium,

    color: colors.text.primary,

  },

  verificationTool: {

    padding: `${spacing[1]} ${spacing[3]}`,

    borderRadius: borderRadius.sm,

    fontSize: typography.fontSize.xs,

    fontWeight: typography.fontWeight.medium,

    textTransform: 'uppercase',

  },

  verificationStatus: {

    padding: `${spacing[1]} ${spacing[3]}`,

    borderRadius: borderRadius.sm,

    fontSize: typography.fontSize.xs,

    fontWeight: typography.fontWeight.bold,

    textTransform: 'uppercase',

  },

  verificationDetails: {

    display: 'flex',

    flexDirection: 'column',

    gap: spacing[3],

  },

  artifactList: {

    display: 'flex',

    flexDirection: 'column',

    gap: spacing[4],

  },

  artifactCard: {

    padding: spacing[6],

  },

  artifactHeader: {

    display: 'flex',

    justifyContent: 'space-between',

    alignItems: 'center',

    marginBottom: spacing[4],

  },

  artifactName: {

    fontSize: typography.fontSize.base,

    fontWeight: typography.fontWeight.semibold,

    color: colors.text.primary,

  },

  artifactKind: {

    padding: `${spacing[1]} ${spacing[3]}`,

    borderRadius: borderRadius.sm,

    fontSize: typography.fontSize.xs,

    fontWeight: typography.fontWeight.medium,

    textTransform: 'uppercase',

  },

  artifactDetails: {

    display: 'flex',

    flexDirection: 'column',

    gap: spacing[3],

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

  provenanceList: {

    display: 'flex',

    flexDirection: 'column',

    gap: spacing[4],

  },

  provenanceCard: {

    padding: spacing[6],

  },

  provenanceHeader: {

    display: 'flex',

    alignItems: 'center',

    gap: spacing[4],

    marginBottom: spacing[3],

    flexWrap: 'wrap',

  },

  provenanceSequence: {

    padding: `${spacing[1]} ${spacing[3]}`,

    borderRadius: borderRadius.sm,

    fontSize: typography.fontSize.xs,

    fontWeight: typography.fontWeight.bold,

    background: `rgba(0, 229, 255, 0.1)`,

    color: colors.accent.cyan,

  },

  provenanceType: {

    padding: `${spacing[1]} ${spacing[3]}`,

    borderRadius: borderRadius.sm,

    fontSize: typography.fontSize.xs,

    fontWeight: typography.fontWeight.medium,

    textTransform: 'uppercase',

    background: `rgba(139, 92, 246, 0.1)`,

    color: colors.accent.violet,

  },

  provenanceActor: {

    fontSize: typography.fontSize.xs,

    color: colors.text.tertiary,

  },

  provenanceTime: {

    fontSize: typography.fontSize.xs,

    color: colors.text.muted,

    marginLeft: 'auto',

  },

  provenanceDetail: {

    marginTop: spacing[3],

  },

  provenanceChain: {

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

  secondaryAction: {

    padding: `${spacing[3]} ${spacing[6]}`,

    borderRadius: borderRadius.base,

    border: `1px solid ${colors.border.tertiary}`,

    background: 'transparent',

    color: colors.text.secondary,

    cursor: 'pointer',

    fontSize: typography.fontSize.sm,

    fontWeight: typography.fontWeight.medium,

    transition: `all ${transitions.base}`,

  },

};



export default TaskDetail;
