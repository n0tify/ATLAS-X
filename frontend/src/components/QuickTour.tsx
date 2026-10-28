/** Five-step Quick Tour component. */

import { useState, useCallback } from 'react';
import { colors, typography, spacing, borderRadius, shadows, transitions } from '../styles/designTokens';

interface TourStep {
  title: string;
  content: string;
  target: string;
}

const tourSteps: TourStep[] = [
  {
    title: 'Explore the Dashboard',
    content: 'This is your AI research laboratory. The Living System Map shows the agent lifecycle. Real system status appears here.',
    target: '#dashboard-overview',
  },
  {
    title: 'Create a Research Task',
    content: 'Define your research goal here. Specify the objective, constraints, and expected validation criteria.',
    target: '#create-task',
  },
  {
    title: 'Plan and Execute',
    content: 'Each task generates a verified plan. Authorize tools, execute bounded operations, and track real progress.',
    target: '#task-workspace',
  },
  {
    title: 'Verify and Inspect',
    content: 'Independent verification confirms results. Inspect artifacts, provenance events, and integrity evidence.',
    target: '#verification',
  },
  {
    title: 'Research and Evaluate',
    content: 'Use the Research Playground, Security Center, and benchmarks to conduct systematic agent reliability experiments.',
    target: '#research-tools',
  },
];

interface QuickTourProps {
  onClose: () => void;
}

export function QuickTour({ onClose }: QuickTourProps) {
  const [currentStep, setCurrentStep] = useState(0);
  const [isVisible, setIsVisible] = useState(true);

  const handleFinish = useCallback(() => {
    setIsVisible(false);
    setTimeout(onClose, 300);
  }, [onClose]);

  const handleNext = useCallback(() => {
    if (currentStep < tourSteps.length - 1) {
      setCurrentStep(currentStep + 1);
    } else {
      handleFinish();
    }
  }, [currentStep, handleFinish]);

  const handleBack = useCallback(() => {
    if (currentStep > 0) {
      setCurrentStep(currentStep - 1);
    }
  }, [currentStep]);

  const handleSkip = useCallback(() => {
    setIsVisible(false);
    setTimeout(onClose, 300);
  }, [onClose]);

  const step = tourSteps[currentStep];

  if (!isVisible) return null;

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        pointerEvents: 'none',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      {/* Backdrop */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: 'rgba(0, 0, 0, 0.7)',
          pointerEvents: 'auto',
        }}
        onClick={handleSkip}
      />

      {/* Tour Card */}
      <div
        style={{
          position: 'relative',
          maxWidth: '480px',
          width: '90%',
          background: 'rgba(20, 27, 44, 0.95)',
          backdropFilter: 'blur(20px)',
          WebkitBackdropFilter: 'blur(20px)',
          border: `1px solid ${colors.accent.violet}`,
          borderRadius: borderRadius.xl,
          boxShadow: shadows.glow,
          padding: spacing[6],
          pointerEvents: 'auto',
          animation: 'fadeIn 0.3s ease-out',
        }}
      >
        {/* Progress Indicator */}
        <div
          style={{
            display: 'flex',
            gap: spacing[2],
            marginBottom: spacing[4],
          }}
        >
          {tourSteps.map((_, index) => (
            <div
              key={index}
              style={{
                flex: 1,
                height: '2px',
                background:
                  index <= currentStep ? colors.accent.violet : colors.border.tertiary,
                transition: transitions.base,
              }}
            />
          ))}
        </div>

        {/* Step Number */}
        <div
          style={{
            fontSize: typography.fontSize.xs,
            fontWeight: typography.fontWeight.medium,
            color: colors.accent.cyan,
            marginBottom: spacing[2],
            letterSpacing: typography.letterSpacing.wide,
            textTransform: 'uppercase',
          }}
        >
          Step {currentStep + 1} of {tourSteps.length}
        </div>

        {/* Title */}
        <h2
          style={{
            fontSize: typography.fontSize.xl,
            fontWeight: typography.fontWeight.bold,
            color: colors.text.primary,
            marginBottom: spacing[3],
            fontFamily: typography.fontFamily.primary,
          }}
        >
          {step.title}
        </h2>

        {/* Content */}
        <p
          style={{
            fontSize: typography.fontSize.base,
            lineHeight: typography.lineHeight.relaxed,
            color: colors.text.secondary,
            marginBottom: spacing[6],
            fontFamily: typography.fontFamily.primary,
          }}
        >
          {step.content}
        </p>

        {/* Actions */}
        <div
          style={{
            display: 'flex',
            gap: spacing[3],
            justifyContent: 'flex-end',
          }}
        >
          {currentStep > 0 && (
            <button
              onClick={handleBack}
              style={{
                fontFamily: typography.fontFamily.primary,
                fontSize: typography.fontSize.base,
                fontWeight: typography.fontWeight.medium,
                color: colors.text.secondary,
                background: 'transparent',
                border: 'none',
                padding: `${spacing[2]} ${spacing[4]}`,
                cursor: 'pointer',
                transition: transitions.base,
              }}
            >
              Back
            </button>
          )}

          <button
            onClick={handleSkip}
            style={{
              fontFamily: typography.fontFamily.primary,
              fontSize: typography.fontSize.base,
              fontWeight: typography.fontWeight.medium,
              color: colors.text.secondary,
              background: 'transparent',
              border: 'none',
              padding: `${spacing[2]} ${spacing[4]}`,
              cursor: 'pointer',
              transition: transitions.base,
            }}
          >
            Skip
          </button>

          <button
            onClick={handleNext}
            style={{
              fontFamily: typography.fontFamily.primary,
              fontSize: typography.fontSize.base,
              fontWeight: typography.fontWeight.semibold,
              color: colors.text.primary,
              background: `linear-gradient(135deg, ${colors.accent.violet} 0%, ${colors.accent.indigo} 100%)`,
              border: 'none',
              borderRadius: borderRadius.md,
              padding: `${spacing[2]} ${spacing[5]}`,
              cursor: 'pointer',
              transition: transitions.base,
              boxShadow: shadows.glow,
            }}
          >
            {currentStep === tourSteps.length - 1 ? 'Finish' : 'Next'}
          </button>
        </div>
      </div>
    </div>
  );
}
