import { api } from './client';

export interface User {
  id: number;
  username: string;
  email?: string | null;
  role: 'admin' | 'annotator' | 'reviewer';
  created_at: string;
}

export async function requestEmergencyCode(email: string) {
  const { data } = await api.post<{ detail: string }>('/auth/emergency/request', { email });
  return data;
}

export async function verifyEmergencyCode(email: string, code: string) {
  const { data } = await api.post<{ access_token: string; token_type: string }>(
    '/auth/emergency/verify',
    { email, code },
  );
  return data;
}

export async function loginWithGoogle(credential: string) {
  const { data } = await api.post<{ access_token: string; token_type: string }>(
    '/auth/google',
    { credential },
  );
  return data;
}

export async function me() {
  const { data } = await api.get<User>('/auth/me');
  return data;
}
