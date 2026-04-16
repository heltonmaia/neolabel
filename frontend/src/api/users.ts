import { api } from './client';
import type { User } from './auth';

export async function listUsers() {
  const { data } = await api.get<User[]>('/users');
  return data;
}
