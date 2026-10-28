/** 404 Not Found page. */

import { useNavigate } from 'react-router-dom';
import { colors, typography, spacing, borderRadius, transitions } from '../styles/designTokens';

export default function NotFound() {
  const navigate = useNavigate();

  return (
    <div style={styles.container}>
      <div style={styles.content}>
        <div style={styles.icon}>404</div>
        <h1 style={styles.title}>Page Not Found</h1>
        <p style={styles.message}>
          The page you're looking for doesn't exist or has been moved.
        </p>
        <button onClick={() => navigate('/dashboard')} style={styles.button}>
          Go to Dashboard
        </button>
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
    alignItems: 'center',
    justifyContent: 'center',
  },
  content: {
    textAlign: 'center',
    maxWidth: '500px',
  },
  icon: {
    fontSize: typography.fontSize['5xl'],
    fontWeight: typography.fontWeight.bold,
    color: colors.accent.cyan,
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
    marginBottom: spacing[8],
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
