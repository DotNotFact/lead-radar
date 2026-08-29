import { SourcesPage } from './pages/SourcesPage'

// Единственный экран первой итерации (docs/miniapp-brief.md) - переключатель источников.
// Остальные экраны (Telegram-чаты, скоринг, настройки, статистика) добавляются сюда по
// одному, каждый со своими тестами, а не все разом.
export function App() {
  return <SourcesPage />
}
