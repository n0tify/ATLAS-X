/** Authentication service for ATLAS-X. */

import { api } from './api';
import type { AuthResponse, User } from '../types';

export const authService = {
  /** Register a new user */
  async register(username: string, password: string): Promise<AuthResponse> {
    await api.post<User>('/api/auth/register', { username, password });
    // After registration, log in to get the token
    return this.login(username, password);
  },

  /** Sign in with username and password */
  async login(username: string, password: string): Promise<AuthResponse> {
    const result = await api.post<AuthResponse>('/api/auth/login', { username, password });
    api.setToken(result.token);
    return result;
  },

  /** Sign out */
  async logout(): Promise<{ message: string }> {
    try {
      return await api.post<{ message: string }>('/api/auth/logout', {});
    } finally {
      api.clearToken();
    }
  },

  /** Get current authenticated user */
  async getCurrentUser(): Promise<User> {
    return api.get<User>('/api/auth/me');
  },
};
