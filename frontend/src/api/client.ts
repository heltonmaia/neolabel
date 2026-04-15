import axios from 'axios';
import { API_URL } from '@/lib/env';
import { useAuth } from '@/stores/auth';

export const api = axios.create({ baseURL: API_URL });

api.interceptors.request.use((config) => {
  const token = useAuth.getState().token;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401) useAuth.getState().logout();
    return Promise.reject(error);
  },
);
