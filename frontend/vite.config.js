import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // PosterEditor.css의 @font-face가 poster_model/assets/fonts를 참조한다.
    // dev 서버는 기본적으로 프로젝트 루트(frontend/) 밖의 파일을 서빙하지 않아
    // 폰트 5종이 전부 차단되고 폴백 서체로 그려진다. build는 이 제한을 받지 않는다.
    fs: { allow: ['..'] },
  },
})
