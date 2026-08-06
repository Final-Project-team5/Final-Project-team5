/**
 * 포스터 이미지 생성 API — mock 버전.
 * 실서버(지우님 파트)가 준비되기 전까지 프론트 흐름 검증용으로 사용한다.
 * (docs/UIUX_스펙정리.md 5장 "포스터 모델" 참고)
 *
 *   POST /generate/drafts  { mode, image?, prompt, num_images } → DraftSelect.jsx (화면 C)
 */

const MOCK_DELAY_MS = 900;
const SEEDS = [12345, 67890, 24680];

function delay(ms = MOCK_DELAY_MS) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// 실제 이미지 모델이 아직 없어 회색 placeholder 이미지를 SVG data URI로 대신 만든다.
function placeholderImage(seed, label) {
  const hue = (seed * 47) % 360;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512">
    <rect width="512" height="512" fill="hsl(${hue} 20% 90%)" />
    <rect x="16" y="16" width="480" height="480" rx="18" fill="none" stroke="hsl(${hue} 20% 78%)" stroke-width="2" stroke-dasharray="6 8" />
    <text x="50%" y="50%" font-family="sans-serif" font-size="26" fill="hsl(${hue} 20% 45%)" text-anchor="middle" dominant-baseline="middle">${label}</text>
  </svg>`;
  return `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(svg)))}`;
}

/** POST /generate/drafts 목 함수. 화면 A에서 저장한 mode/image를 그대로 넘겨받는다. */
export async function generateDrafts({ mode = 'text2img', image = null, prompt = '', num_images = 3 } = {}) {
  await delay();

  const drafts = SEEDS.slice(0, num_images).map((seed, idx) => ({
    id: `d${idx + 1}`,
    image: placeholderImage(seed, `시안 ${idx + 1}`),
    seed,
  }));

  return {
    drafts,
    meta: {
      elapsed: 9.8,
      model: mode === 'inpaint' ? 'sd15-inpaint' : 'sd15',
      mode,
      prompt,
      usedProductImage: Boolean(image),
    },
  };
}
