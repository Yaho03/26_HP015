import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // 개발 서버(:5173)에서 상대 경로(/api, /ws, /health)로 호출해도 백엔드(:8000)로
    // 프록시되도록 함 — 배포 환경의 nginx 프록시(frontend/nginx.conf)와 동일한 역할
    // (이슈 #105, 프론트엔드가 :8000을 직접 호출하지 않게 하기 위함).
    proxy: {
      '/api': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
})
