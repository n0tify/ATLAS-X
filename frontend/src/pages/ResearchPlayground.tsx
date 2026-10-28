/** Research Playground - Execute tools, explore capabilities, and test research workflows. */

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { api } from '../services/api';
import type { Tool, ToolExecution, Task, ToolInputField, ToolInvokeResponse } from '../types';
import { colors, typography, spacing, borderRadius } from '../styles/designTokens';
import { LiquidButton, LiquidTabs, LiquidBadge, LiquidSpinner, LiquidInput, LiquidSelect } from '../components/LiquidGlass';
import { formatTimestamp } from '../utils/dates';

interface ToolWithExecution extends Tool {
  lastExecution?: ToolExecution;
  unavailable?: boolean;
  unavailableReason?: string;
}

interface BackendTool {
  tool_id: string;
  title: string;
  description: string;
  version: string;
  capability: string;
  determinism: string;
  input_schema?: {
    type: string;
    properties: Record<string, {
      type: string;
      description?: string;
      minimum?: number;
      maximum?: number;
      maxLength?: number;
      maxItems?: number;
      items?: Record<string, unknown>;
      enum?: string[];
    }>;
    required: string[];
    additionalProperties: boolean;
  };
}

type ActiveTab = 'tools' | 'executions' | 'results';

function inferCategory(toolId: string): string {
  if (toolId.includes('statistics') || toolId.includes('summary') || toolId.includes('inspect')) {
    return 'analysis';
  }
  if (toolId.includes('csv') || toolId.includes('json') || toolId.includes('artifact')) {
    return 'data';
  }
  if (toolId.includes('task') || toolId.includes('graph')) {
    return 'ml';
  }
  return 'utility';
}

function getToolInputFields(tool: ToolWithExecution): ToolInputField[] {
  if (!tool.parameters || typeof tool.parameters !== 'object') return [];
  const schema = tool.parameters as BackendTool['input_schema'];
  if (!schema || !schema.properties) return [];

  return Object.entries(schema.properties).map(([name, fieldSchema]) => {
    const label = name.charAt(0).toUpperCase() + name.slice(1).replace(/_/g, ' ');
    const fs = fieldSchema as {
      type: string;
      description?: string;
      minimum?: number;
      maximum?: number;
      maxLength?: number;
      minLength?: number;
      maxItems?: number;
      items?: Record<string, unknown>;
      enum?: string[];
    };

    let type: 'text' | 'number' | 'textarea' | 'select' = 'text';
    if (fs.type === 'integer' || fs.type === 'number') {
      type = 'number';
    } else if (fs.enum) {
      type = 'select';
    } else if (fs.maxLength && fs.maxLength > 100) {
      type = 'textarea';
    }

    return {
      name,
      type,
      label,
      placeholder: fs.description || `Enter ${label.toLowerCase()}`,
      required: schema.required?.includes(name) ?? false,
      maxLength: fs.maxLength,
      minLength: fs.minLength,
      min: fs.minimum,
      max: fs.maximum,
      rows: type === 'textarea' ? 4 : undefined,
      options: fs.enum ? fs.enum.map((v: string) => ({ value: v, label: v })) : undefined,
    };
  });
}

function renderInputField(
  field: ToolInputField,
  value: unknown,
  onChange: (name: string, value: unknown) => void,
  error?: string
) {
  const { name, type, label, placeholder, required, maxLength, minLength, min, max, rows, options } = field;

  const stringValue = value === undefined || value === null ? '' : String(value);

  if (type === 'select' && options) {
    return (
      <LiquidSelect
        key={name}
        label={label}
        value={stringValue}
        onChange={(v: string) => onChange(name, v)}
        options={options}
        placeholder={placeholder}
        required={required}
        error={error}
        style={{ width: '100%' }}
      />
    );
  }

  if (type === 'textarea') {
    return (
      <LiquidInput
        key={name}
        label={label}
        type="textarea"
        value={stringValue}
        onChange={(v: string) => onChange(name, v)}
        placeholder={placeholder}
        required={required}
        error={error}
        maxLength={maxLength}
        rows={rows}
        style={{ width: '100%' }}
      />
    );
  }

  if (type === 'number') {
    const numValue = value !== undefined && value !== null ? Number(value) : undefined;
    return (
      <LiquidInput
        key={name}
        label={label}
        type="number"
        value={numValue !== undefined && !isNaN(numValue) ? String(numValue) : ''}
        onChange={(v: string) => onChange(name, v === '' ? undefined : Number(v))}
        placeholder={placeholder}
        required={required}
        error={error}
        min={min}
        max={max}
        style={{ width: '100%' }}
      />
    );
  }

  return (
    <LiquidInput
      key={name}
      label={label}
      type="text"
      value={stringValue}
      onChange={(v: string) => onChange(name, v)}
      placeholder={placeholder}
      required={required}
      error={error}
      maxLength={maxLength}
      minLength={minLength}
      style={{ width: '100%' }}
    />
  );
}

function ToolCard({ tool, onSelect }: { tool: ToolWithExecution; onSelect: (tool: ToolWithExecution) => void }) {
  const isUnavailable = tool.unavailable;

  return (
    <div className="glass-panel-elevated glass-specular" style={styles.toolCard}>
      <div style={styles.toolHeader}>
        <div style={styles.toolIcon} role="img" aria-label={tool.category}>
          {tool.category === 'data' && '📊'}
          {tool.category === 'analysis' && '🔬'}
          {tool.category === 'ml' && '🤖'}
          {tool.category === 'web' && '🌐'}
          {tool.category === 'utility' && '🔧'}
        </div>
        <div style={styles.toolInfo}>
          <h4 style={styles.toolName}>{tool.name}</h4>
          <p style={styles.toolDescription}>{tool.description}</p>
        </div>
      </div>
      <div style={styles.toolMeta}>
        {isUnavailable ? (
          <LiquidBadge variant="warning" size="sm">Unavailable</LiquidBadge>
        ) : (
          <LiquidBadge variant="cyan" size="sm">{tool.category}</LiquidBadge>
        )}
        <span style={styles.toolVersion}>v{tool.version}</span>
      </div>
      {isUnavailable ? (
        <div style={styles.unavailableNotice}>
          <p style={styles.unavailableText}>{tool.unavailableReason}</p>
        </div>
      ) : (
        <LiquidButton
          variant="primary"
          onClick={() => onSelect(tool)}
          style={styles.selectButton}
        >
          Select Tool
        </LiquidButton>
      )}
    </div>
  );
}

function ExecutionPanel({
  execution,
  onClose,
  onRetry
}: {
  execution: ToolExecution | null;
  onClose: () => void;
  onRetry: () => void;
}) {
  if (!execution) return null;

  return (
    <div className="glass-panel-elevated glass-specular" style={styles.executionPanel}>
      <div style={styles.executionHeader}>
        <h3 style={styles.executionTitle}>Tool Execution</h3>
        <LiquidButton variant="ghost" size="sm" onClick={onClose}>
          ✕
        </LiquidButton>
      </div>

      <div style={styles.executionStatus} className="glass-panel-subtle">
        <LiquidBadge
          variant={
            execution.status === 'succeeded' ? 'success' :
            execution.status === 'failed' ? 'error' :
            execution.status === 'running' ? 'cyan' : 'warning'
          }
          size="lg"
        >
          {execution.status.toUpperCase()}
        </LiquidBadge>
        <span style={styles.executionMeta}>
          Tool: {execution.tool_name} • {formatTimestamp(execution.created_at)}
        </span>
      </div>

      {execution.status === 'running' && (
        <div style={styles.progressContainer} className="glass-panel-subtle">
          <LiquidSpinner size="lg" />
          <p style={styles.progressText}>Executing tool...</p>
        </div>
      )}

      {execution.status === 'succeeded' && execution.result && (
        <div style={styles.resultContainer}>
          <h4 style={styles.resultTitle}>Result</h4>
          <pre style={styles.resultJson}>{JSON.stringify(execution.result, null, 2)}</pre>
        </div>
      )}

      {execution.status === 'failed' && execution.error && (
        <div style={styles.errorContainer} className="glass-panel-subtle">
          <h4 style={styles.errorTitle}>Error</h4>
          <pre style={styles.errorText}>{execution.error}</pre>
          <LiquidButton variant="secondary" onClick={onRetry} style={{ marginTop: spacing[3] }}>
            Retry
          </LiquidButton>
        </div>
      )}

      {execution.status !== 'running' && execution.status !== 'pending' && (
        <div style={styles.executionActions}>
          <LiquidButton variant="secondary" onClick={onClose}>
            Close
          </LiquidButton>
        </div>
      )}
    </div>
  );
}

function ResultsTab({ executions }: { executions: ToolExecution[] }) {
  const completedExecutions = executions.filter(e => e.status === 'succeeded' || e.status === 'failed');

  if (completedExecutions.length === 0) {
    return (
      <div style={styles.emptyState} className="glass-panel-subtle">
        <p style={styles.emptyText}>No completed executions yet. Run some tools to see results here.</p>
      </div>
    );
  }

  return (
    <div style={styles.resultsList}>
      {completedExecutions.map(exec => (
        <div key={exec.id} className="glass-panel-elevated glass-specular" style={styles.resultCard}>
          <div style={styles.resultHeader}>
            <div style={styles.resultToolInfo}>
              <span style={styles.resultToolName}>{exec.tool_name}</span>
              <LiquidBadge
                variant={exec.status === 'succeeded' ? 'success' : 'error'}
                size="sm"
              >
                {exec.status}
              </LiquidBadge>
            </div>
            <span style={styles.resultTime}>{formatTimestamp(exec.created_at)}</span>
          </div>
          {exec.result && (
            <details style={styles.resultDetails}>
              <summary style={styles.resultSummary}>View Result</summary>
              <pre style={styles.resultJson}>{JSON.stringify(exec.result, null, 2)}</pre>
            </details>
          )}
          {exec.error && (
            <details style={styles.resultDetails}>
              <summary style={{ ...styles.resultSummary, color: colors.accent.error }}>View Error</summary>
              <pre style={{ ...styles.resultJson, color: colors.accent.error }}>{exec.error}</pre>
            </details>
          )}
        </div>
      ))}
    </div>
  );
}

export default function ResearchPlayground() {
  const [tools, setTools] = useState<ToolWithExecution[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [executions, setExecutions] = useState<ToolExecution[]>([]);
  const [activeTab, setActiveTab] = useState<ActiveTab>('tools');
  const [selectedTool, setSelectedTool] = useState<ToolWithExecution | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);
  const [currentExecution, setCurrentExecution] = useState<ToolExecution | null>(null);
  const [filterCategory, setFilterCategory] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [toolInputValues, setToolInputValues] = useState<Record<string, unknown>>({});
  const [toolInputErrors, setToolInputErrors] = useState<Record<string, string>>({});
  const [isExecuting, setIsExecuting] = useState(false);
  const [latestExecutionId, setLatestExecutionId] = useState<number | null>(null);
  useEffect(() => {
    setLatestExecutionId(null);
  }, [selectedTaskId]);

  const fetchTools = useCallback(async () => {
    try {
      const response = await api.get<BackendTool[]>('/api/tools/list');
      const mappedTools: ToolWithExecution[] = response.map(t => {
        const tool: ToolWithExecution = {
          name: t.tool_id,
          version: t.version,
          category: inferCategory(t.tool_id),
          description: t.description,
          capability: t.capability,
          determinism: t.determinism,
          parameters: t.input_schema || {},
          lastExecution: undefined,
        };
        // Mark csv_statistics as unavailable due to sandbox guest issue
        if (t.tool_id === 'csv_statistics') {
          tool.unavailable = true;
          tool.unavailableReason = 'Tool not available in sandbox guest. Use text_statistics for analysis.';
        }
        return tool;
      });
      setTools(mappedTools);
      const firstAvailable = mappedTools.find((t) => !t.unavailable);
      if (firstAvailable) {
        setSelectedTool((prev) => (prev ? prev : firstAvailable));
      }
    } catch (error) {
      console.error('Failed to fetch tools:', error);
    }
  }, []);

  const fetchTasks = useCallback(async () => {
    try {
      const response = await api.get<Task[]>('/api/tasks');
      setTasks(response);
      if (response.length > 0 && !selectedTaskId) {
        setSelectedTaskId(response[0].id);
      }
    } catch (error) {
      console.error('Failed to fetch tasks:', error);
    }
  }, [selectedTaskId]);

  useEffect(() => {
    fetchTools();
    fetchTasks();
  }, [fetchTools, fetchTasks]);

  const filteredTools = useMemo(() =>
    tools.filter(tool => {
      const matchesCategory = filterCategory === 'all' || tool.category === filterCategory;
      const matchesSearch = tool.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
                           tool.description.toLowerCase().includes(searchQuery.toLowerCase());
      return matchesCategory && matchesSearch;
    }), [tools, filterCategory, searchQuery]);

  const categories = useMemo(() =>
    ['all', ...new Set(tools.map(t => t.category))], [tools]);

  const selectedToolInputFields = useMemo(() =>
    selectedTool ? getToolInputFields(selectedTool) : [], [selectedTool]);

  const validateToolInput = useCallback((): boolean => {
    if (!selectedTool) return false;
    const fields = getToolInputFields(selectedTool);
    const newErrors: Record<string, string> = {};

    for (const field of fields) {
      const value = toolInputValues[field.name];
      const required = field.required;

      if (required && (value === undefined || value === null || value === '' || (Array.isArray(value) && value.length === 0))) {
        newErrors[field.name] = `${field.name} is required`;
      }
    }

    setToolInputErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }, [selectedTool, toolInputValues]);

  const handleExecute = useCallback(async () => {
    if (!selectedTool || !selectedTaskId || isExecuting) return;

    if (selectedTool.unavailable) {
      const errorMessage = selectedTool.unavailableReason || 'Tool is unavailable';
      const execution: ToolExecution = {
        id: Date.now(),
        tool_name: selectedTool.name,
        status: 'failed',
        input: toolInputValues,
        error: errorMessage,
        created_at: new Date().toISOString(),
      };
      setCurrentExecution(execution);
      setExecutions(prev => [execution, ...prev]);
      setActiveTab('executions');
      return;
    }

    if (!validateToolInput()) return;

    setIsExecuting(true);
    setToolInputErrors({});

    // Prepare input: convert comma strings to arrays for numeric_summary values,
    // and chain latest execution id into artifact_metadata when not provided.
    const preparedInput: Record<string, unknown> = { ...toolInputValues };
    if (selectedTool.name === 'numeric_summary') {
      const v = preparedInput.values;
      if (typeof v === 'string') {
        preparedInput.values = v
          .split(',')
          .map((s) => s.trim())
          .filter((s) => s !== '')
          .map((s) => Number(s));
      }
    }
    if (selectedTool.name === 'artifact_metadata') {
      if (preparedInput.execution_id === undefined || preparedInput.execution_id === null || preparedInput.execution_id === '') {
        if (latestExecutionId !== null) {
          preparedInput.execution_id = latestExecutionId;
        }
      } else if (typeof preparedInput.execution_id === 'string') {
        const n = Number(preparedInput.execution_id);
        if (!Number.isNaN(n)) preparedInput.execution_id = n;
      }
    }

    try {
      const response = await api.post<ToolInvokeResponse>(`/api/tools/invoke`, {
        tool_id: selectedTool.name,
        input: preparedInput,
        task_id: selectedTaskId,
      });

      if (response.execution_id !== undefined) {
        setLatestExecutionId(response.execution_id);
      }

      const execution: ToolExecution = {
        id: response.execution_id ?? response.provenance_event_id ?? Date.now(),
        tool_name: selectedTool.name,
        status: 'succeeded',
        input: preparedInput,
        result: response.result,
        created_at: new Date().toISOString(),
      };

      setCurrentExecution(execution);
      setExecutions(prev => [execution, ...prev]);
      setActiveTab('executions');
    } catch (error: unknown) {
      const errorMessage = error instanceof Error ? error.message : 'Execution failed';
      const execution: ToolExecution = {
        id: Date.now(),
        tool_name: selectedTool.name,
        status: 'failed',
        input: toolInputValues,
        error: errorMessage,
        created_at: new Date().toISOString(),
      };
      setCurrentExecution(execution);
      setExecutions(prev => [execution, ...prev]);
      setActiveTab('executions');
    } finally {
      setIsExecuting(false);
    }
  }, [selectedTool, selectedTaskId, toolInputValues, validateToolInput, isExecuting, latestExecutionId]);

  const handleInputChange = (name: string, value: unknown) => {
    setToolInputValues(prev => ({ ...prev, [name]: value }));
    if (toolInputErrors[name]) {
      setToolInputErrors(prev => ({ ...prev, [name]: '' }));
    }
  };

  const handleTaskChange = (taskId: number) => {
    setSelectedTaskId(taskId);
  };

  const handleToolSelect = (tool: ToolWithExecution) => {
    if (tool.unavailable) {
      // Don't select unavailable tools, just show the warning
      return;
    }
    setSelectedTool(tool);
    setToolInputValues({});
    setToolInputErrors({});
    setActiveTab('tools');
    setSidebarOpen(false);
  };

  return (
    <div className="research-playground" style={styles.container}>
      <header className="header" style={styles.header}>
        <div style={styles.headerLeft}>
          <button
            className="liquid-button liquid-button-ghost"
            onClick={() => setSidebarOpen(!sidebarOpen)}
            style={styles.menuButton}
            aria-label={sidebarOpen ? 'Close sidebar' : 'Open sidebar'}
          >
            ☰
          </button>
          <h1 style={styles.pageTitle}>Research Playground</h1>
        </div>
        <div style={styles.headerRight}>
          <LiquidButton variant="primary" onClick={() => { setActiveTab('tools'); setSidebarOpen(false); }}>
            + New Execution
          </LiquidButton>
        </div>
      </header>

      <div className="main" style={styles.mainGrid}>
        <aside className={`sidebar ${sidebarOpen ? 'open' : ''}`} style={{ ...styles.sidebar, display: sidebarOpen ? 'flex' : 'none' }}>
          <div style={styles.sidebarHeader}>
            <h2 style={styles.sidebarTitle}>Tools</h2>
          </div>

          <div style={styles.filterSection} className="glass-panel-subtle">
            <LiquidInput
              placeholder="Search tools..."
              value={searchQuery}
              onChange={setSearchQuery}
              style={styles.searchInput}
            />
            <LiquidSelect
              value={filterCategory}
              onChange={(v: string) => setFilterCategory(v)}
              options={categories.map(cat => ({ value: cat, label: cat === 'all' ? 'All Categories' : cat.charAt(0).toUpperCase() + cat.slice(1) }))}
              style={styles.nativeSelect}
            />
          </div>

          {/* Task Selector */}
          <div style={styles.taskSelectorSection} className="glass-panel-subtle">
            <label style={styles.taskSelectorLabel}>Task Context</label>
            <LiquidSelect
              value={String(selectedTaskId ?? '')}
              onChange={(v: string) => handleTaskChange(Number(v))}
              options={tasks.map(t => ({ value: String(t.id), label: `${t.title} (${t.status})` }))}
              placeholder="Select a task"
              required={true}
              style={styles.taskSelector}
            />
            {tasks.length === 0 && (
              <p style={styles.noTasksText}>No tasks available. <a href="/tasks/create" style={{ color: colors.accent.cyan }}>Create one</a>.</p>
            )}
          </div>

          <div style={styles.toolList}>
            {tools.length === 0 ? (
              <div style={styles.loadingContainer}>
                <LiquidSpinner />
                <p style={styles.loadingText}>Loading tools...</p>
              </div>
            ) : filteredTools.length === 0 ? (
              <div style={styles.emptyState} className="glass-panel-subtle">
                <p style={styles.emptyText}>No tools found matching your criteria.</p>
              </div>
            ) : (
              filteredTools.map(tool => (
                <ToolCard key={tool.name} tool={tool} onSelect={handleToolSelect} />
              ))
            )}
          </div>
        </aside>

        <div className={`sidebar-overlay ${sidebarOpen ? 'visible' : ''}`} onClick={() => setSidebarOpen(false)} />

        <main className="content" style={styles.mainContent}>
          <LiquidTabs
            tabs={[
              { id: 'tools', label: 'Tools' },
              { id: 'executions', label: 'Executions' },
              { id: 'results', label: 'Results' },
            ]}
            activeTab={activeTab}
            onChange={(tabId: string) => setActiveTab(tabId as ActiveTab)}
            style={styles.tabs}
          />

          {activeTab === 'tools' && (
            <div style={styles.tabContent}>
              {selectedTool ? (
                <div className="glass-panel-elevated glass-specular" style={styles.toolDetailPanel}>
                  <div style={styles.toolDetailHeader}>
                    <div style={styles.toolDetailIcon} role="img" aria-label={selectedTool.category}>
                      {selectedTool.category === 'data' && '📊'}
                      {selectedTool.category === 'analysis' && '🔬'}
                      {selectedTool.category === 'ml' && '🤖'}
                      {selectedTool.category === 'web' && '🌐'}
                      {selectedTool.category === 'utility' && '🔧'}
                    </div>
                    <div>
                      <h3 style={styles.toolDetailName}>{selectedTool.name}</h3>
                      <p style={styles.toolDetailDescription}>{selectedTool.description}</p>
                    </div>
                  </div>

                  <div style={styles.toolDetailMeta}>
                    <LiquidBadge variant="cyan" size="sm">{selectedTool.category}</LiquidBadge>
                    <span style={styles.toolDetailVersion}>v{selectedTool.version}</span>
                    <LiquidBadge variant="violet" size="sm">{selectedTool.determinism}</LiquidBadge>
                  </div>

                  {selectedToolInputFields.length > 0 && (
                    <div style={styles.inputFormSection}>
                      <h4 style={styles.inputFormTitle}>Input Parameters</h4>
                      <form onSubmit={(e) => { e.preventDefault(); handleExecute(); }} style={styles.inputForm}>
                        {selectedToolInputFields.map(field => (
                          <div key={field.name} style={styles.inputFieldWrapper}>
                            {renderInputField(
                              field,
                              toolInputValues[field.name],
                              handleInputChange,
                              toolInputErrors[field.name]
                            )}
                          </div>
                        ))}
                        <div style={styles.formActions}>
                          <LiquidButton
                            type="submit"
                            variant="primary"
                            disabled={isExecuting || !selectedTaskId}
                            loading={isExecuting}
                            size="lg"
                            fullWidth
                          >
                            {isExecuting ? 'Executing...' : 'Run Analysis'}
                          </LiquidButton>
                          {!selectedTaskId && (
                            <p style={styles.taskRequiredError}>Please select a task first</p>
                          )}
                        </div>
                      </form>
                    </div>
                  )}

                  {selectedToolInputFields.length === 0 && (
                    <div style={styles.noInputForm}>
                      <p style={styles.noInputText}>This tool requires no input parameters.</p>
                      <LiquidButton
                        variant="primary"
                        onClick={handleExecute}
                        disabled={isExecuting || !selectedTaskId}
                        loading={isExecuting}
                        size="lg"
                        fullWidth
                      >
                        {isExecuting ? 'Executing...' : 'Run Analysis'}
                      </LiquidButton>
                      {!selectedTaskId && (
                        <p style={styles.taskRequiredError}>Please select a task first</p>
                      )}
                    </div>
                  )}
                </div>
              ) : (
                <div style={styles.emptyToolState} className="glass-panel-subtle">
                  <div style={styles.emptyToolIcon}>🔧</div>
                  <h3 style={styles.emptyToolTitle}>Select a Tool</h3>
                  <p style={styles.emptyToolDescription}>
                    Choose a tool from the sidebar to configure and execute it.
                  </p>
                </div>
              )}
            </div>
          )}

          {activeTab === 'executions' && (
            <div style={styles.tabContent}>
              {executions.length === 0 ? (
                <div style={styles.emptyState} className="glass-panel-subtle">
                  <p style={styles.emptyText}>No executions yet. Run a tool to see it here.</p>
                </div>
              ) : (
                <div style={styles.executionsList}>
                  {executions.map(exec => (
                    <div key={exec.id} className="glass-panel-elevated glass-specular" style={styles.executionCard}>
                      <div style={styles.executionCardHeader}>
                        <div>
                          <span style={styles.executionToolName}>{exec.tool_name}</span>
                          <LiquidBadge
                            variant={
                              exec.status === 'succeeded' ? 'success' :
                              exec.status === 'failed' ? 'error' :
                              exec.status === 'running' ? 'cyan' : 'warning'
                            }
                            size="sm"
                          >
                            {exec.status}
                          </LiquidBadge>
                        </div>
                        <span style={styles.executionTime}>{formatTimestamp(exec.created_at)}</span>
                      </div>
                      {exec.status === 'running' && (
                        <div style={styles.executionProgress} className="glass-panel-subtle">
                          <LiquidSpinner size="sm" />
                          <span>Running...</span>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {activeTab === 'results' && (
            <div style={styles.tabContent}>
              <ResultsTab executions={executions} />
            </div>
          )}
        </main>
      </div>

      <ExecutionPanel
        execution={currentExecution}
        onClose={() => setCurrentExecution(null)}
        onRetry={() => selectedTool && handleExecute()}
      />
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
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: `0 ${spacing[6]}`,
    backgroundColor: colors.background.secondary,
    borderBottom: `1px solid ${colors.border.tertiary}`,
    position: 'sticky',
    top: 0,
    zIndex: 100,
  },
  headerLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: spacing[4],
  },
  headerRight: {
    display: 'flex',
    alignItems: 'center',
    gap: spacing[3],
  },
  menuButton: {
    padding: spacing[2],
    borderRadius: borderRadius.md,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  pageTitle: {
    fontSize: typography.fontSize.xl,
    fontWeight: typography.fontWeight.semibold,
    color: colors.text.primary,
    margin: 0,
  },
  mainGrid: {
    flex: 1,
    display: 'grid',
    gridTemplateColumns: '320px 1fr',
    gap: 0,
    minHeight: 'calc(100vh - 64px)',
  },
  sidebar: {
    position: 'sticky',
    top: '64px',
    height: 'calc(100vh - 64px)',
    overflowY: 'auto',
    backgroundColor: colors.background.secondary,
    borderRight: `1px solid ${colors.border.tertiary}`,
    display: 'flex',
    flexDirection: 'column',
    padding: spacing[4],
    gap: spacing[4],
  },
  sidebarHeader: {
    paddingBottom: spacing[3],
    borderBottom: `1px solid ${colors.border.tertiary}`,
  },
  sidebarTitle: {
    fontSize: typography.fontSize.base,
    fontWeight: typography.fontWeight.semibold,
    margin: 0,
    color: colors.text.primary,
  },
  filterSection: {
    display: 'flex',
    flexDirection: 'column',
    gap: spacing[3],
    padding: spacing[3],
  },
  searchInput: {
    width: '100%',
  },
  nativeSelect: {
    width: '100%',
    padding: spacing[2],
    borderRadius: borderRadius.md,
    backgroundColor: colors.background.tertiary,
    border: `1px solid ${colors.border.tertiary}`,
    color: colors.text.primary,
    fontFamily: typography.fontFamily.primary,
    fontSize: typography.fontSize.sm,
  },
  taskSelectorSection: {
    display: 'flex',
    flexDirection: 'column',
    gap: spacing[2],
    padding: spacing[3],
  },
  taskSelectorLabel: {
    fontSize: typography.fontSize.xs,
    fontWeight: typography.fontWeight.medium,
    color: colors.text.tertiary,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  taskSelector: {
    width: '100%',
  },
  noTasksText: {
    fontSize: typography.fontSize.xs,
    color: colors.text.tertiary,
    margin: 0,
  },
  toolList: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    gap: spacing[3],
    overflowY: 'auto',
  },
  loadingContainer: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing[8],
    gap: spacing[3],
  },
  loadingText: {
    color: colors.text.tertiary,
    fontSize: typography.fontSize.sm,
  },
  mainContent: {
    flex: 1,
    padding: spacing[6],
    overflowY: 'auto',
  },
  tabs: {
    marginBottom: spacing[6],
  },
  tabContent: {
    animation: 'fadeIn 0.2s ease-out',
  },
  toolsGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
    gap: spacing[4],
  },
  toolCard: {
    display: 'flex',
    flexDirection: 'column',
    padding: spacing[4],
    gap: spacing[3],
  },
  toolHeader: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: spacing[3],
  },
  toolIcon: {
    fontSize: '2rem',
    flexShrink: 0,
  },
  toolInfo: {
    flex: 1,
    minWidth: 0,
  },
  toolName: {
    fontSize: typography.fontSize.base,
    fontWeight: typography.fontWeight.semibold,
    margin: 0,
    color: colors.text.primary,
  },
  toolDescription: {
    fontSize: typography.fontSize.sm,
    color: colors.text.secondary,
    margin: spacing[1] + ' 0 0 0',
    display: '-webkit-box',
    WebkitLineClamp: 2,
    WebkitBoxOrient: 'vertical',
    overflow: 'hidden',
  },
  toolMeta: {
    display: 'flex',
    alignItems: 'center',
    gap: spacing[2],
    fontSize: typography.fontSize.xs,
    color: colors.text.tertiary,
  },
  toolVersion: {
    fontFamily: typography.fontFamily.mono,
  },
  selectButton: {
    width: '100%',
    marginTop: spacing[2],
  },
  unavailableNotice: {
    marginTop: spacing[2],
    padding: spacing[3],
    backgroundColor: `${colors.accent.warning}1A`,
    border: `1px solid ${colors.accent.warning}40`,
    borderRadius: borderRadius.base,
  },
  unavailableText: {
    fontSize: typography.fontSize.xs,
    color: colors.accent.warning,
    margin: 0,
    lineHeight: 1.4,
  },
  toolDetailPanel: {
    display: 'flex',
    flexDirection: 'column',
    gap: spacing[4],
    padding: spacing[6],
    maxWidth: '800px',
  },
  toolDetailHeader: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: spacing[4],
  },
  toolDetailIcon: {
    fontSize: '3rem',
    flexShrink: 0,
  },
  toolDetailName: {
    fontSize: typography.fontSize.xl,
    fontWeight: typography.fontWeight.semibold,
    margin: 0,
    color: colors.text.primary,
  },
  toolDetailDescription: {
    fontSize: typography.fontSize.base,
    color: colors.text.secondary,
    margin: spacing[1] + ' 0 0 0',
  },
  toolDetailMeta: {
    display: 'flex',
    alignItems: 'center',
    gap: spacing[2],
    fontSize: typography.fontSize.xs,
    color: colors.text.tertiary,
  },
  toolDetailVersion: {
    fontFamily: typography.fontFamily.mono,
  },
  inputFormSection: {
    marginTop: spacing[4],
    paddingTop: spacing[4],
    borderTop: `1px solid ${colors.border.tertiary}`,
  },
  inputFormTitle: {
    fontSize: typography.fontSize.base,
    fontWeight: typography.fontWeight.semibold,
    marginBottom: spacing[4],
    color: colors.text.primary,
  },
  inputForm: {
    display: 'flex',
    flexDirection: 'column',
    gap: spacing[4],
  },
  inputFieldWrapper: {
    display: 'flex',
    flexDirection: 'column',
    gap: spacing[1],
  },
  formActions: {
    display: 'flex',
    flexDirection: 'column',
    gap: spacing[2],
    marginTop: spacing[2],
  },
  taskRequiredError: {
    fontSize: typography.fontSize.sm,
    color: colors.accent.error,
    margin: 0,
    textAlign: 'center',
  },
  noInputForm: {
    marginTop: spacing[4],
    paddingTop: spacing[4],
    borderTop: `1px solid ${colors.border.tertiary}`,
    textAlign: 'center',
  },
  noInputText: {
    marginBottom: spacing[4],
    color: colors.text.secondary,
  },
  emptyToolState: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing[12],
    textAlign: 'center',
    minHeight: '300px',
  },
  emptyToolIcon: {
    fontSize: '4rem',
    marginBottom: spacing[4],
    opacity: 0.5,
  },
  emptyToolTitle: {
    fontSize: typography.fontSize.xl,
    fontWeight: typography.fontWeight.semibold,
    marginBottom: spacing[2],
    color: colors.text.primary,
  },
  emptyToolDescription: {
    color: colors.text.tertiary,
    maxWidth: '400px',
    margin: 0,
  },
  executionsList: {
    display: 'flex',
    flexDirection: 'column',
    gap: spacing[3],
  },
  executionCard: {
    padding: spacing[4],
  },
  executionCardHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing[3],
  },
  executionToolName: {
    fontSize: typography.fontSize.base,
    fontWeight: typography.fontWeight.medium,
    color: colors.text.primary,
  },
  executionTime: {
    fontSize: typography.fontSize.sm,
    color: colors.text.tertiary,
    fontFamily: typography.fontFamily.mono,
  },
  executionProgress: {
    display: 'flex',
    alignItems: 'center',
    gap: spacing[2],
    padding: spacing[3],
    marginTop: spacing[3],
    fontSize: typography.fontSize.sm,
    color: colors.text.secondary,
  },
  resultsList: {
    display: 'flex',
    flexDirection: 'column',
    gap: spacing[3],
  },
  resultCard: {
    padding: spacing[4],
  },
  resultHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing[3],
  },
  resultToolInfo: {
    display: 'flex',
    alignItems: 'center',
    gap: spacing[2],
  },
  resultToolName: {
    fontSize: typography.fontSize.base,
    fontWeight: typography.fontWeight.semibold,
    color: colors.text.primary,
  },
  resultTime: {
    fontSize: typography.fontSize.sm,
    color: colors.text.tertiary,
    fontFamily: typography.fontFamily.mono,
  },
  resultDetails: {
    marginTop: spacing[2],
  },
  resultSummary: {
    cursor: 'pointer',
    fontSize: typography.fontSize.sm,
    color: colors.accent.cyan,
    fontWeight: typography.fontWeight.medium,
    padding: spacing[1] + ' 0',
  },
  emptyState: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing[8],
    textAlign: 'center',
    minHeight: '200px',
  },
  emptyText: {
    color: colors.text.tertiary,
    margin: 0,
    fontSize: typography.fontSize.base,
  },
  executionPanel: {
    position: 'fixed',
    bottom: spacing[6],
    right: spacing[6],
    left: 'auto',
    width: '380px',
    maxWidth: 'calc(100vw - 32px)',
    maxHeight: '60vh',
    overflowY: 'auto',
    zIndex: 200,
    padding: spacing[4],
    boxShadow: '0 20px 40px rgba(0,0,0,0.3)',
    border: `1px solid ${colors.glass.border}`,
    animation: 'slideUp 0.3s ease-out',
  },
  executionHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing[3],
  },
  executionTitle: {
    fontSize: typography.fontSize.base,
    fontWeight: typography.fontWeight.semibold,
    margin: 0,
  },
  executionStatus: {
    display: 'flex',
    alignItems: 'center',
    gap: spacing[3],
    padding: spacing[3],
    marginBottom: spacing[3],
  },
  executionMeta: {
    fontSize: typography.fontSize.sm,
    color: colors.text.secondary,
  },
  progressContainer: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: spacing[3],
    padding: spacing[6],
  },
  progressText: {
    color: colors.text.secondary,
    margin: 0,
  },
  resultContainer: {
    marginBottom: spacing[4],
  },
  resultTitle: {
    fontSize: typography.fontSize.sm,
    fontWeight: typography.fontWeight.semibold,
    marginBottom: spacing[2],
  },
  resultJson: {
    fontSize: typography.fontSize.xs,
    fontFamily: typography.fontFamily.mono,
    backgroundColor: colors.background.tertiary,
    padding: spacing[3],
    borderRadius: borderRadius.md,
    overflowX: 'auto',
    maxHeight: '300px',
    overflowY: 'auto',
    margin: 0,
    color: colors.text.primary,
  },
  errorContainer: {
    marginBottom: spacing[4],
  },
  errorTitle: {
    fontSize: typography.fontSize.sm,
    fontWeight: typography.fontWeight.semibold,
    marginBottom: spacing[2],
    color: colors.accent.error,
  },
  errorText: {
    fontSize: typography.fontSize.xs,
    fontFamily: typography.fontFamily.mono,
    backgroundColor: `${colors.accent.error}1A`,
    padding: spacing[3],
    borderRadius: borderRadius.md,
    overflowX: 'auto',
    maxHeight: '200px',
    overflowY: 'auto',
    margin: 0,
    color: colors.accent.error,
  },
  executionActions: {
    display: 'flex',
    justifyContent: 'flex-end',
    paddingTop: spacing[3],
    borderTop: `1px solid ${colors.border.tertiary}`,
  },
};