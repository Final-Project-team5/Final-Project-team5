/**
 * 포스터 이미지 생성 API — mock 버전.
 * 실서버(지우님 파트)가 준비되기 전까지 프론트 흐름 검증용으로 사용한다.
 * (docs/UIUX_스펙정리.md 5장 "포스터 모델" 참고, 8/7 실서버 필드 정합 반영)
 *
 *   POST /generate/drafts  { mode, image?, prompt, num_images } → DraftSelect.jsx (화면 C)
 *   POST /generate/refine  { draft_image, original_image, background, prompt, text } → PosterEditor.jsx (화면 D)
 */

const MOCK_DELAY_MS = 900;
const SEEDS = [12345, 67890, 24680];

function delay(ms = MOCK_DELAY_MS) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** 챗봇 spec(화면 A)에서 포스터용 "배경 설명" 프롬프트를 만든다. 화면 C/D가 공유. */
export function buildPrompt(spec = {}) {
  return [spec.tone, spec.product, spec.highlights].filter(Boolean).join(', ') || '포스터 배경';
}

// 실제 이미지 모델이 아직 없어 캔버스로 그린 placeholder를 PNG data URI로 대신 만든다.
// (화면 D에서 base64 strip → 재조합 왕복을 거치는데, 실제로 다시 렌더되는 이미지여야
//  어댑터 동작을 눈으로 확인할 수 있어서 SVG 대신 PNG로 그린다)
function placeholderImage(seed, label) {
  const size = 512;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  const hue = (seed * 47) % 360;

  ctx.fillStyle = `hsl(${hue} 20% 90%)`;
  ctx.fillRect(0, 0, size, size);
  ctx.strokeStyle = `hsl(${hue} 20% 78%)`;
  ctx.lineWidth = 2;
  ctx.setLineDash([6, 8]);
  ctx.strokeRect(16, 16, size - 32, size - 32);
  ctx.fillStyle = `hsl(${hue} 20% 45%)`;
  ctx.font = '600 26px sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(label, size / 2, size / 2);

  return canvas.toDataURL('image/png'); // data:image/png;base64,...
}

// solid/gradient 배경 모드의 mock 값 — 실제로는 draft 응답에 실려 오고,
// refine 요청 때 그대로 echo해야 동일 배경이 재현된다 (서버 무상태).
function mockBackground(seed) {
  const hue = (seed * 47) % 360;
  return { type: 'gradient', colors: [`hsl(${hue} 30% 92%)`, `hsl(${hue} 30% 78%)`] };
}

/** POST /generate/drafts 목 함수. 화면 A에서 저장한 mode/image를 그대로 넘겨받는다. */
export async function generateDrafts({ mode = 'text2img', image = null, prompt = '', num_images = 3 } = {}) {
  await delay();

  const drafts = SEEDS.slice(0, num_images).map((seed, idx) => ({
    id: `d${idx + 1}`,
    image: placeholderImage(seed, `시안 ${idx + 1}`),
    seed,
    background: mockBackground(seed),
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

/** data URI에서 순수 base64만 뽑아낸다 (이미 prefix가 없으면 그대로 반환). */
function stripDataUriPrefix(value = '') {
  const commaIdx = value.indexOf(',');
  return value.startsWith('data:') && commaIdx >= 0 ? value.slice(commaIdx + 1) : value;
}

/**
 * 실제 /generate/refine 응답의 image는 순수 base64(data: prefix 없음)로 내려온다.
 * 화면에서 <img src>로 바로 쓰려면 이 어댑터로 감싸야 한다 — 실서버 연동 시에도
 * 이 함수 하나만 그대로 붙이면 됨 (docs/UIUX_스펙정리.md 5장 참고).
 */
export function toImageSrc(base64) {
  if (!base64) return '';
  return base64.startsWith('data:') ? base64 : `data:image/png;base64,${base64}`;
}

/**
 * POST /generate/refine 목 함수. 화면 D에서 [완성하기] 클릭 시 딱 한 번 호출한다.
 * 실제 이미지 합성 모델이 없어 mock에서는 선택한 시안(draft_image)을 그대로
 * "완성 이미지"로 되돌려준다. 응답의 image는 실제 API와 동일하게 순수 base64로
 * 내려보내므로 호출부에서 반드시 toImageSrc()로 감싸서 써야 한다.
 */
export async function generateRefine({
  draft_image,
  original_image,
  background,
  prompt = '',
  text = {},
} = {}) {
  await delay(1100);

  return {
    image: stripDataUriPrefix(draft_image),
    meta: {
      elapsed: 12.3,
      model: 'sdxl',
      seed: Math.floor(Math.random() * 100000),
      layout: { text },
      usedOriginalImage: Boolean(original_image),
      background,
      prompt,
    },
  };
}
