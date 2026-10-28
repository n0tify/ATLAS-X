/** Premium login page for ATLAS-X research platform. */

import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { AtlasXLogo } from '../components/LiquidGlassToggle';
import { LiquidButton, LiquidInput } from '../components/LiquidGlass';
import { colors, typography, spacing, borderRadius, transitions } from '../styles/designTokens';

export function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      await login(username, password);
      navigate('/dashboard');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login" style={styles.container}>
      <div className="ambient-bg">
        <div className="ambient-grid"></div>
        <div className="ambient-orbs">
          <div className="ambient-orb ambient-orb-1"></div>
          <div className="ambient-orb ambient-orb-2"></div>
          <div className="ambient-orb ambient-orb-3"></div>
          <div className="ambient-orb ambient-orb-4"></div>
        </div>
      </div>
      {/* Left Panel - Branding */}
      <div className="leftPanel" style={styles.leftPanel}>
        <div className="brandContent" style={styles.brandContent}>
          <AtlasXLogo size="xl" animated={true} />
          <h1 style={styles.title}>Research Platform for Reliable AI Agents</h1>
          <p style={styles.subtitle}>
            Investigating how authorization, sandboxing, independent verification,
            provenance integrity, and bounded recovery affect multi-step agent reliability
            and security.
          </p>
          <div style={styles.features}>
            <div style={styles.feature} className="glass-panel-subtle">
              <div style={styles.featureIcon}>✓</div>
              <div style={styles.featureText}>Deterministic Verification</div>
            </div>
            <div style={styles.feature} className="glass-panel-subtle">
              <div style={styles.featureIcon}>✓</div>
              <div style={styles.featureText}>Tamper-Evident Provenance</div>
            </div>
            <div style={styles.feature} className="glass-panel-subtle">
              <div style={styles.featureIcon}>✓</div>
              <div style={styles.featureText}>Bounded Sandbox Execution</div>
            </div>
            <div style={styles.feature} className="glass-panel-subtle">
              <div style={styles.featureIcon}>✓</div>
              <div style={styles.featureText}>Reproducible Experiments</div>
            </div>
          </div>
        </div>
      </div>

      {/* Right Panel - Sign In Form */}
      <div className="rightPanel" style={styles.rightPanel}>
        <div className="glass-panel-elevated glass-specular" style={styles.formContainer}>
          <div style={styles.formHeader}>
            <h2 style={styles.formTitle}>Sign In</h2>
            <p style={styles.formSubtitle}>Access your research workspace</p>
          </div>

          {error && (
            <div style={styles.error} className="glass-panel-subtle">
              <span style={styles.errorIcon}>⚠</span>
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} style={styles.form}>
            <div style={styles.formGroup}>
              <label htmlFor="username" style={styles.label}>
                Username
              </label>
              <LiquidInput
                id="username"
                type="text"
                value={username}
                onChange={setUsername}
                placeholder="Enter your username"
                required
                minLength={5}
                maxLength={32}
                autoComplete="username"
              />
            </div>

            <div style={styles.formGroup}>
              <label htmlFor="password" style={styles.label}>
                Password
              </label>
              <div style={styles.passwordWrapper}>
                <LiquidInput
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={setPassword}
                  placeholder="Enter your password"
                  required
                  minLength={5}
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  style={styles.passwordToggle}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? '👁' : '👁‍🗨'}
                </button>
              </div>
            </div>

            <LiquidButton type="submit" disabled={loading} loading={loading} size="lg" fullWidth>
              {loading ? 'Signing in...' : 'Sign In'}
            </LiquidButton>
          </form>

          <div style={styles.footer}>
            <span style={styles.footerText}>Don't have an account?</span>
            <Link to="/register" style={styles.link}>
              Create an account
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    minHeight: '100vh',
    fontFamily: typography.fontFamily.primary,
    backgroundColor: colors.background.primary,
  },
  leftPanel: {
    flex: '1',
    position: 'relative',
    background: `linear-gradient(135deg, ${colors.background.secondary} 0%, ${colors.background.primary} 100%)`,
    display: 'flex',
    flexDirection: 'column',
    justifyContent: 'center',
    padding: spacing[16],
    overflow: 'hidden',
    minWidth: 0,
  },
  brandContent: {
    position: 'relative',
    zIndex: 1,
    maxWidth: '600px',
  },
  title: {
    fontSize: typography.fontSize['5xl'],
    fontWeight: typography.fontWeight.bold,
    color: colors.text.primary,
    marginBottom: spacing[6],
    marginTop: 0,
    lineHeight: typography.lineHeight.tight,
  },
  subtitle: {
    fontSize: typography.fontSize.lg,
    color: colors.text.secondary,
    lineHeight: typography.lineHeight.relaxed,
    marginBottom: spacing[12],
  },
  features: {
    display: 'grid',
    gridTemplateColumns: 'repeat(2, 1fr)',
    gap: spacing[6],
  },
  feature: {
    display: 'flex',
    alignItems: 'center',
    gap: spacing[3],
    padding: spacing[4],
  },
  featureIcon: {
    fontSize: typography.fontSize.xl,
    color: colors.accent.cyan,
  },
  featureText: {
    fontSize: typography.fontSize.base,
    color: colors.text.secondary,
    fontWeight: typography.fontWeight.medium,
  },
  rightPanel: {
    width: '500px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.background.secondary,
    padding: spacing[8],
  },
  formContainer: {
    width: '100%',
    maxWidth: '400px',
  },
  formHeader: {
    marginBottom: spacing[8],
  },
  formTitle: {
    fontSize: typography.fontSize['3xl'],
    fontWeight: typography.fontWeight.bold,
    color: colors.text.primary,
    marginBottom: spacing[2],
    marginTop: 0,
  },
  formSubtitle: {
    fontSize: typography.fontSize.base,
    color: colors.text.tertiary,
    marginBottom: 0,
  },
  error: {
    display: 'flex',
    alignItems: 'center',
    gap: spacing[3],
    padding: spacing[4],
    backgroundColor: 'rgba(239, 68, 68, 0.1)',
    border: `1px solid ${colors.accent.error}`,
    borderRadius: borderRadius.base,
    color: colors.accent.error,
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
  passwordWrapper: {
    position: 'relative',
  },
  passwordToggle: {
    position: 'absolute',
    right: spacing[4],
    top: '50%',
    transform: 'translateY(-50%)',
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    fontSize: typography.fontSize.lg,
    padding: 0,
    color: colors.text.tertiary,
  },
  footer: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing[2],
    marginTop: spacing[8],
    color: colors.text.tertiary,
    fontSize: typography.fontSize.sm,
  },
  footerText: {
    color: colors.text.tertiary,
  },
  link: {
    color: colors.accent.cyan,
    textDecoration: 'none',
    fontWeight: typography.fontWeight.medium,
    transition: `color ${transitions.fast}`,
  },
};

export default Login;