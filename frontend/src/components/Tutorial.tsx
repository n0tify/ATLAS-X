/** Tutorial overlay component - 5-step Quick Tour. */

import React from 'react';
import { useTutorial } from '../hooks/useTutorial';
import { colors, typography, spacing, borderRadius, shadows, transitions } from '../styles/designTokens';

export function Tutorial() {
  const { showTutorial, step, nextStep, prevStep, skipTutorial } = useTutorial();

  if (!showTutorial) return null;

  const steps = [
    {
      title: 'Explore the Dashboard',
      description: 'This is your AI research laboratory. The Living System Map shows the agent lifecycle from Task through Provenance. Each stage reflects real persisted state.',
      icon: '⬡',
    },
    {
      title: 'Create a Research Task',
      description: 'Define your research goal with clear objectives, constraints, and validation criteria. Tasks are persisted with full provenance tracking from creation through verification.',
      icon: '📝',
    },
    {
      title: 'Plan and Execute',
      description: 'Each task generates a verified plan. Authorize supported tools, execute bounded operations in the sandbox, and track real progress with deterministic verification.',
      icon: '⚡',
    },
    {
      title: 'Verify and Inspect',
      description: 'Independent verification confirms results. Inspect artifacts, provenance chains with cryptographic integrity checks, and export reproducible reports for your research.',
      icon: '✓',
    },
    {
      title: 'Research and Evaluate',
      description: 'Use the Research Playground, Security Center, and benchmarks to conduct systematic agent reliability experiments and contribute to the ATLAS-BENCH dataset.',
      icon: '🔬',
    },
  ];

  const currentStep = steps[step];

  return (
    <div style={styles.overlay}>
      <div style={styles.modal}>
        <div style={styles.iconContainer}>
          <span style={styles.icon}>{currentStep.icon}</span>
        </div>

        <div style={styles.content}>
          <h2 style={styles.title}>{currentStep.title}</h2>
          <p style={styles.description}>{currentStep.description}</p>

          <div style={styles.progress}>
            {steps.map((_, index) => (
              <div
                key={index}
                style={{
                  ...styles.progressDot,
                  backgroundColor: index === step ? colors.accent.cyan : colors.border.primary,
                }}
              />
            ))}
          </div>
        </div>

        <div style={styles.actions}>
          {step > 0 && (
            <button onClick={prevStep} style={styles.secondaryButton}>
              Back
            </button>
          )}
          <button onClick={nextStep} style={styles.primaryButton}>
            {step === steps.length - 1 ? 'Finish and Explore' : 'Next'}
          </button>
          <button onClick={skipTutorial} style={styles.skipButton}>
            Skip Tour
          </button>
        </div>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  overlay: {
    position: 'fixed',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0, 0, 0, 0.8)',
    backdropFilter: 'blur(10px)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 9999,
    pointerEvents: 'auto',
  },
  modal: {
    background: `rgba(17, 24, 39, 0.95)`,
    backdropFilter: 'blur(20px)',
    border: `1px solid ${colors.border.primary}`,
    borderRadius: borderRadius.xl,
    padding: spacing[12],
    maxWidth: '600px',
    width: '90%',
    boxShadow: shadows.lg,
    pointerEvents: 'auto',
  },
  iconContainer: {
    width: '80px',
    height: '80px',
    borderRadius: '50%',
    background: `linear-gradient(135deg, ${colors.accent.cyan} 0%, ${colors.accent.violet} 100%)`,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: spacing[8],
    margin: '0 auto ' + spacing[8] + ' auto',
  },
  icon: {
    fontSize: typography.fontSize['4xl'],
  },
  content: {
    textAlign: 'center',
    marginBottom: spacing[8],
  },
  title: {
    fontSize: typography.fontSize['2xl'],
    fontWeight: typography.fontWeight.bold,
    marginBottom: spacing[4],
    marginTop: 0,
    color: colors.text.primary,
  },
  description: {
    fontSize: typography.fontSize.base,
    lineHeight: typography.lineHeight.relaxed,
    color: colors.text.secondary,
    marginBottom: spacing[8],
  },
  progress: {
    display: 'flex',
    justifyContent: 'center',
    gap: spacing[3],
    marginBottom: spacing[8],
  },
  progressDot: {
    width: '8px',
    height: '8px',
    borderRadius: '50%',
    transition: `background-color ${transitions.base}`,
  },
  actions: {
    display: 'flex',
    justifyContent: 'center',
    gap: spacing[4],
    flexWrap: 'wrap',
  },
  primaryButton: {
    padding: `${spacing[4]} ${spacing[8]}`,
    borderRadius: borderRadius.base,
    border: 'none',
    background: `linear-gradient(135deg, ${colors.accent.cyan} 0%, ${colors.accent.blue} 100%)`,
    color: colors.text.primary,
    fontSize: typography.fontSize.base,
    fontWeight: typography.fontWeight.semibold,
    cursor: 'pointer',
    boxShadow: shadows.glow,
    transition: `all ${transitions.base}`,
  },
  secondaryButton: {
    padding: `${spacing[4]} ${spacing[8]}`,
    borderRadius: borderRadius.base,
    border: `1px solid ${colors.border.primary}`,
    background: 'transparent',
    color: colors.text.secondary,
    fontSize: typography.fontSize.base,
    fontWeight: typography.fontWeight.medium,
    cursor: 'pointer',
    transition: `all ${transitions.base}`,
  },
  skipButton: {
    padding: `${spacing[4]} ${spacing[8]}`,
    borderRadius: borderRadius.base,
    border: 'none',
    background: 'transparent',
    color: colors.text.tertiary,
    fontSize: typography.fontSize.sm,
    cursor: 'pointer',
    transition: `all ${transitions.base}`,
  },
};
