/** Authentication context for managing user state. */

import { useState, useEffect, type ReactNode } from 'react';
import type { User } from '../types';
import { AuthContext } from './AuthContextInstance';
import { authService } from '../services/auth';
import { api } from '../services/api';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Check if user is already authenticated on mount
    const token = api.getToken();
    if (token) {
      refreshUser().catch(() => {
        setUser(null);
        setLoading(false);
      });
    } else {
      setLoading(false);
    }
  }, []);

  const refreshUser = async () => {
    try {
      const currentUser = await authService.getCurrentUser();
      setUser(currentUser);
    } catch (error) {
      setUser(null);
      api.clearToken();
      throw error;
    } finally {
      setLoading(false);
    }
  };

  const login = async (username: string, password: string) => {
    await authService.login(username, password);
    await refreshUser();
  };

  const register = async (username: string, password: string) => {
    await authService.register(username, password);
    // Token is already set by authService.register -> login
    await refreshUser();
  };

  const logout = async () => {
    await authService.logout();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}
