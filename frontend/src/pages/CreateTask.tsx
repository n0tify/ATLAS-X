/** Task creation page for ATLAS-X. */

import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../services/api';
import type { Task } from '../types';
import { AtlasXLogo } from '../components/LiquidGlassToggle';
import { LiquidButton, LiquidInput } from '../components/LiquidGlass';
import { colors, typography, spacing, borderRadius } from '../styles/designTokens';

export function CreateTask() {
  const [title, setTitle] = useState('');
  const [goal, setGoal] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const task = await api.post<Task>('/api/tasks', { title, goal });
      navigate(`/tasks/${task.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create task');
    } finally {
      setLoading(false);
    }
  };

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
        <AtlasXLogo size="md" animated={false} />
        <h1 style={styles.title}>Create Research Task</h1>
      </header>

      <main style={styles.main}>
        <div className="glass-panel-elevated glass-specular" style={styles.glassPanel}>
          <div style={styles.panelHeader}>
            <h2 style={styles.panelTitle}>Task Configuration</h2>
          </div>

          {error && (
            <div style={styles.error} className="glass-panel-subtle">
              <span style={styles.errorIcon}>⚠</span>
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} style={styles.form}>
            <div style={styles.formGroup}>
              <label htmlFor="title" style={styles.label}>
                Task Title
              </label>
              <LiquidInput
                id="title"
                type="text"
                value={title}
                onChange={setTitle}
                placeholder="Enter a descriptive title"
                required
                maxLength={200}
              />
            </div>

            <div style={styles.formGroup}>
              <label htmlFor="goal" style={styles.label}>
                Research Goal
              </label>
              <LiquidInput
                id="goal"
                value={goal}
                onChange={setGoal}
                placeholder="Describe what you want to investigate"
                required
                maxLength={2000}
                rows={5}
                type="textarea"
              />
            </div>

            <div style={styles.infoBox} className="glass-panel-subtle">
              <h4 style={styles.infoTitle}>Available Tools</h4>
              <ul style={styles.infoList}>
                <li style={styles.infoItem}>CSV Statistics - Analyze CSV data patterns</li>
                <li style={styles.infoItem}>JSON Shape Inspection - Examine JSON structure</li>
                <li style={styles.infoItem}>Numeric Summary - Calculate statistical measures</li>
                <li style={styles.infoItem}>Text Statistics - Analyze text characteristics</li>
              </ul>
            </div>

            <LiquidButton type="submit" disabled={loading} loading={loading} size="lg" fullWidth>
              {loading ? 'Creating task...' : 'Create Task'}
            </LiquidButton>
          </form>
        </div>
      </main>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    minHeight: '100vh',
    width: '100%',
    minWidth: 0,
    backgroundColor: colors.background.primary,
    fontFamily: typography.fontFamily.primary,
    color: colors.text.primary,
    display: 'flex',
    flexDirection: 'column',
  },
  header: {
    padding: `${spacing[6]} ${spacing[12]}`,
    borderBottom: `1px solid ${colors.border.tertiary}`,
    display: 'flex',
    alignItems: 'center',
    gap: spacing[6],
    flexWrap: 'wrap',
  },
  backButton: {
    padding: `${spacing[3]} ${spacing[5]}`,
    fontSize: typography.fontSize.sm,
  },
  title: {
    fontSize: typography.fontSize['2xl'],
    fontWeight: typography.fontWeight.bold,
    margin: 0,
  },
  main: {
    flex: 1,
    width: '100%',
    minWidth: 0,
    padding: spacing[12],
    maxWidth: '800px',
    margin: '0 auto',
  },
  glassPanel: {
    padding: spacing[8],
    borderRadius: '1rem',
  },
  panelHeader: {
    marginBottom: spacing[8],
  },
  panelTitle: {
    fontSize: typography.fontSize.xl,
    fontWeight: typography.fontWeight.semibold,
    margin: 0,
  },
  error: {
    display: 'flex',
    alignItems: 'center',
    gap: spacing[3],
    padding: spacing[4],
    fontSize: typography.fontSize.sm,
    marginBottom: spacing[6],
  },
  errorIcon: {
    fontSize: typography.fontSize.lg,
  },
  form: {
    display: 'flex',
    flexDirection: 'column',
    gap: spacing[6],
  },
  formGroup: {
    display: 'flex',
    flexDirection: 'column',
    gap: spacing[2],
  },
  label: {
    fontSize: typography.fontSize.sm,
    fontWeight: typography.fontWeight.medium,
    color: colors.text.secondary,
  },
  infoBox: {
    padding: spacing[6],
    borderRadius: borderRadius.base,
    background: `rgba(0, 229, 255, 0.05)`,
    border: `1px solid ${colors.border.tertiary}`,
  },
  infoTitle: {
    fontSize: typography.fontSize.base,
    fontWeight: typography.fontWeight.semibold,
    margin: `0 0 ${spacing[4]} 0`,
    color: colors.accent.cyan,
  },
  infoList: {
    margin: 0,
    paddingLeft: spacing[6],
    color: colors.text.secondary,
  },
  infoItem: {
    marginBottom: spacing[2],
    fontSize: typography.fontSize.sm,
  },
};

export default CreateTask;