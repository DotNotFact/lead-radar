import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Бэкенд (src/webapp) слушает MINIAPP_PORT из .env, по умолчанию 8765 - см. .env.example
    // в корне проекта. При dev-разработке фронтенда отдельно от бэкенда прокси избавляет от
    // CORS-настройки на стороне FastAPI.
    proxy: {
      '/api': 'http://127.0.0.1:8765',
    },
  },
})
