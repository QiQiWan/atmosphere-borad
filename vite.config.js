import { defineConfig, loadEnv } from 'vite';
import vue from '@vitejs/plugin-vue';
import { resolve } from 'node:path';

export default ({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const port = Number(env.VITE_PORT || 5173);
  const proxyTarget = env.VITE_BACKEND_PROXY || 'http://127.0.0.1:52000';

  return defineConfig({
    base: env.VITE_BASE_URL || '/',
    plugins: [vue()],
    resolve: {
      alias: {
        '@': resolve(__dirname, 'src'),
      },
    },
    server: {
      host: '0.0.0.0',
      port,
      open: env.VITE_OPEN_BROWSER === 'false' ? false : `http://localhost:${port}/`,
      cors: true,
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
          secure: false,
        },
      },
    },
    preview: {
      host: '0.0.0.0',
      port: Number(env.VITE_PREVIEW_PORT || 4173),
    },
    build: {
      target: 'es2018',
      sourcemap: false,
      chunkSizeWarningLimit: 2000,
      rollupOptions: {
        output: {
          entryFileNames: 'static/js/[name]-[hash].js',
          chunkFileNames: 'static/js/[name]-[hash].js',
          assetFileNames: 'static/[ext]/[name]-[hash].[ext]',
          manualChunks: {
            vue: ['vue', 'vue-router'],
            charts: ['echarts'],
            element: ['element-plus'],
          },
        },
      },
    },
  });
};
