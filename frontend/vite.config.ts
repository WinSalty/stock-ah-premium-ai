import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

declare const process: {
  env: {
    FRONTEND_PORT?: string;
    BACKEND_PORT?: string;
  };
};

const frontendPort = Number(process.env.FRONTEND_PORT || 5173);
const backendPort = process.env.BACKEND_PORT || '8000';

export default defineConfig({
  plugins: [react()],
  build: {
    chunkSizeWarningLimit: 1100,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) {
            return undefined;
          }
          if (id.includes('/react/') || id.includes('/react-dom/')) {
            return 'react';
          }
          if (id.includes('/antd/') || id.includes('/@ant-design/')) {
            return 'antd';
          }
          if (id.includes('/echarts/') || id.includes('/echarts-for-react/')) {
            return 'charts';
          }
          return undefined;
        }
      }
    }
  },
  server: {
    port: frontendPort,
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${backendPort}`,
        changeOrigin: true
      }
    }
  }
});
