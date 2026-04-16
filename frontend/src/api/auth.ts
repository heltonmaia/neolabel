import { api } from './client';

export interface User {
  id: number;
  username: string;
  role: 'admin' | 'annotator' | 'reviewer';
  created_at: string;
}

export async function login(email: string, password: string) {
  const form = new URLSearchParams();
  form.append('username', email);
  form.append('password', password);
  const { data } = await api.post<{ access_token: string; token_type: string }>(
    '/auth/login',
    form,
    { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } },
  );
  return data;
}

export async function me() {
  const { data } = await api.get<User>('/auth/me');
  return data;
}
