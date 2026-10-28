/** Type definitions for ATLAS-X API responses. */

export interface User {
  id: number;
  username: string;
  created_at: string;
}

export interface AuthResponse {
  token: string;
  user: User;
}

export interface Task {
  id: number;
  user_id: number;
  title: string;
  goal: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface SystemStatus {
  status: string;
  sandbox: string;
  verifier: string;
  provenance: string;
  model: string;
}

export interface Tool {
  name: string;
  version: string;
  category: string;
  description: string;
  capability: string;
  determinism: string;
  parameters: Record<string, unknown>;
}

export interface ToolExecution {
  id: number;
  tool_name: string;
  status: 'pending' | 'running' | 'succeeded' | 'failed';
  input: Record<string, unknown>;
  result?: Record<string, unknown>;
  error?: string;
  created_at: string;
  completed_at?: string;
}

export interface ToolInputField {
  name: string;
  type: 'text' | 'number' | 'textarea' | 'select';
  label: string;
  placeholder?: string;
  required?: boolean;
  maxLength?: number;
  minLength?: number;
  min?: number;
  max?: number;
  rows?: number;
  options?: Array<{ value: string; label: string }>;
}

export interface ToolInvokeResponse {
  tool_id?: string;
  tool_version?: string;
  capability?: string;
  determinism?: string;
  user_id?: number;
  task_id?: number;
  execution_id?: number;
  result: Record<string, unknown>;
  provenance_event_id?: number;
}
