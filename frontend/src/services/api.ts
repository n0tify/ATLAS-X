/** API service for communicating with FastAPI backend. */

const API_BASE_URL = '';  // Use Vite proxy

// Simple in-memory cache for GET requests with 5 second TTL
const cache = new Map<string, { data: unknown; timestamp: number }>();
const CACHE_TTL = 5000; // 5 seconds

function getCached<T>(endpoint: string): T | null {
  const cached = cache.get(endpoint);
  if (cached && Date.now() - cached.timestamp < CACHE_TTL) {
    return cached.data as T;
  }
  return null;
}

function setCache(endpoint: string, data: unknown) {
  cache.set(endpoint, { data, timestamp: Date.now() });
}

function clearCache(endpoint?: string) {
  if (endpoint) {
    cache.delete(endpoint);
  } else {
    cache.clear();
  }
}

const getAuthHeaders = () => {
  const token = localStorage.getItem('auth_token');
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
};

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = 'Request failed';
    try {
      const error = await response.json();
      detail = error.detail || detail;
    } catch {
      // If JSON parsing fails, use status text
      detail = response.statusText || detail;
    }
    throw new Error(detail);
  }
  return response.json();
}

export const api = {
  /** Base URL for API requests */
  baseURL: API_BASE_URL,

  /** Generic GET request with caching */
  async get<T>(endpoint: string): Promise<T> {
    const cached = getCached<T>(endpoint);
    if (cached) return cached;

    const response = await fetch(`${this.baseURL}${endpoint}`, {
      method: 'GET',
      headers: getAuthHeaders(),
    });
    const data = await handleResponse<T>(response);
    setCache(endpoint, data);
    return data;
  },

  /** Generic POST request */
  async post<T>(endpoint: string, data: unknown): Promise<T> {
    const response = await fetch(`${this.baseURL}${endpoint}`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify(data),
    });
    const result = await handleResponse<T>(response);
    clearCache(); // Clear cache on mutations
    return result;
  },

  /** Generic DELETE request */
  async delete<T>(endpoint: string): Promise<T> {
    const response = await fetch(`${this.baseURL}${endpoint}`, {
      method: 'DELETE',
      headers: getAuthHeaders(),
    });
    const result = await handleResponse<T>(response);
    clearCache(); // Clear cache on mutations
    return result;
  },

  /** Set auth token */
  setToken(token: string) {
    localStorage.setItem('auth_token', token);
    clearCache();
  },

  /** Clear auth token */
  clearToken() {
    localStorage.removeItem('auth_token');
    clearCache();
  },

  /** Get auth token */
  getToken(): string | null {
    return localStorage.getItem('auth_token');
  },
};
