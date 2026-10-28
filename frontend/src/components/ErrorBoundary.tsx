/** Error boundary to catch component crashes. */

import React, { Component, ErrorInfo, ReactNode } from 'react';
import { colors, typography, spacing, borderRadius, transitions } from '../styles/designTokens';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Error caught by boundary:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={styles.container}>
          <div style={styles.content}>
            <div style={styles.icon}>⚠</div>
            <h1 style={styles.title}>Something went wrong</h1>
            <p style={styles.message}>
              An unexpected error occurred. Please refresh the page or try again.
            </p>
            {this.state.error && (
              <details style={styles.details}>
                <summary style={styles.summary}>Error details</summary>
                <pre style={styles.error}>{this.state.error.toString()}</pre>
              </details>
            )}
            <button
              onClick={() => window.location.reload()}
              style={styles.button}
            >
              Refresh Page
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    minHeight: '100vh',
    backgroundColor: colors.background.primary,
    fontFamily: typography.fontFamily.primary,
    color: colors.text.primary,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  content: {
    textAlign: 'center',
    maxWidth: '600px',
    padding: spacing[8],
  },
  icon: {
    fontSize: typography.fontSize['5xl'],
    marginBottom: spacing[6],
  },
  title: {
    fontSize: typography.fontSize['2xl'],
    fontWeight: typography.fontWeight.bold,
    marginBottom: spacing[4],
    marginTop: 0,
  },
  message: {
    fontSize: typography.fontSize.base,
    color: colors.text.secondary,
    marginBottom: spacing[6],
  },
  details: {
    marginBottom: spacing[8],
    textAlign: 'left',
  },
  summary: {
    cursor: 'pointer',
    color: colors.accent.cyan,
    marginBottom: spacing[4],
  },
  error: {
    backgroundColor: colors.background.tertiary,
    padding: spacing[4],
    borderRadius: borderRadius.base,
    fontSize: typography.fontSize.sm,
    color: colors.text.tertiary,
    overflow: 'auto',
  },
  button: {
    padding: `${spacing[4]} ${spacing[8]}`,
    borderRadius: borderRadius.base,
    border: `1px solid ${colors.accent.cyan}`,
    background: 'transparent',
    color: colors.accent.cyan,
    cursor: 'pointer',
    fontSize: typography.fontSize.base,
    fontWeight: typography.fontWeight.medium,
    transition: `all ${transitions.base}`,
  },
};
