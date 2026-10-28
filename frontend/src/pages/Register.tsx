/** Premium register page for ATLAS-X research platform. */

import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { AtlasXLogo } from '../components/LiquidGlassToggle';
import { LiquidButton, LiquidInput } from '../components/LiquidGlass';
import { colors, typography, spacing, borderRadius, transitions } from '../styles/designTokens';

export function Register() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { register } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (password !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }

    setLoading(true);

    try {
      await register(username, password);
      navigate('/dashboard');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed');
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
      {/* Left Panel - Branding */}
      <div style={styles.leftPanel}>
        <div style={styles.brandContent}>
          <AtlasXLogo size="xl" animated={true} />
          <h1 style={styles.title}>Join the Research Platform</h1>
          <p style={styles.subtitle}>
            Create your account to investigate how authorization, sandboxing,
            independent verification, provenance integrity, and bounded recovery
            affect multi-step agent reliability and security.
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

      {/* Right Panel - Registration Form */}
      <div style={styles.rightPanel}>
        <div className="glass-panel-elevated glass-specular" style={styles.formContainer}>
          <div style={styles.formHeader}>
            <h2 style={styles.formTitle}>Create Account</h2>
            <p style={styles.formSubtitle}>Join the ATLAS-X research community</p>
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
                placeholder="Choose a username"
                required
                minLength={5}
                maxLength={32}
                autoComplete="username"
              />
              <small style={styles.hint}>5-32 characters</small>
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
                  placeholder="Create a password"
                  required
                  minLength={5}
                  autoComplete="new-password"
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
              <small style={styles.hint}>Minimum 5 characters</small>
            </div>

            <div style={styles.formGroup}>
              <label htmlFor="confirmPassword" style={styles.label}>
                Confirm Password
              </label>
              <LiquidInput
                id="confirmPassword"
                type={showPassword ? 'text' : 'password'}
                value={confirmPassword}
                onChange={setConfirmPassword}
                placeholder="Confirm your password"
                required
                minLength={5}
                autoComplete="new-password"
              />
            </div>

            <LiquidButton type="submit" disabled={loading} loading={loading} size="lg" fullWidth>
              {loading ? 'Creating account...' : 'Create Account'}
            </LiquidButton>
          </form>

          <div style={styles.footer}>
            <span style={styles.footerText}>Already have an account?</span>
            <Link to="/login" style={styles.link}>
              Sign in
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
  hint: {
    color: colors.text.muted,
    fontSize: typography.fontSize.xs,
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

export default Register;