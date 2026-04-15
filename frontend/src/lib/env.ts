export const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api/v1';
// API_URL is like http://host/api/v1 — strip trailing /api/v1 for serving /files
export const FILES_BASE = API_URL.replace(/\/api\/v1\/?$/, '');
