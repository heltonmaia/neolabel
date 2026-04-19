import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    // Docker bind-mount inotify events are unreliable on Linux, so
    // fall back to polling for HMR inside the container.
    watch: { usePolling: true, interval: 300 },
  },
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
});
