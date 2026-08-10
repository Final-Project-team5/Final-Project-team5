/**
 * 포스터 이미지 생성 API — mock 버전.
 * 실서버(지우님 파트)가 준비되기 전까지 프론트 흐름 검증용으로 사용한다.
 * (docs/UIUX_스펙정리.md 5장 "포스터 모델" 참고, 8/10 용도→비율 매핑 반영)
 *
 *   POST /generate/drafts  { mode, image?, prompt, ratio, backgroundType?, num_images } → DraftSelect.jsx (화면 C)
 *   POST /generate/refine  { draft_image, original_image, background, prompt, text } → PosterEditor.jsx (화면 D)
 */

const MOCK_DELAY_MS = 900;
const SEEDS = [12345, 67890, 24680];

// 챗봇 용도 질문(화면 A)에서 넘어온 비율 문자열 → 실제 캔버스 픽셀 크기.
// AI 배경(diffusion) 쪽은 아직 비정사각 production 미지원이라 실제로는 3:1/3:4가
// flat 배경에서만 쓰이지만, mock 캔버스 자체는 비율만 맞춰 그려둔다.
const RATIO_DIMENSIONS = {
  '1:1': { w: 512, h: 512 },
  '3:1': { w: 768, h: 256 },
  '3:4': { w: 384, h: 512 },
};

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
// backgroundType이 'flat'이면 점선 테두리(= "AI가 그렸다"는 표시) 없이 단순 배경만 그려서
// 화면 C/E에서 AI 배경과 flat 배경을 시각적으로 구분할 수 있게 한다.
function placeholderImage(seed, label, ratio, backgroundType) {
  const { w, h } = RATIO_DIMENSIONS[ratio] || RATIO_DIMENSIONS['1:1'];
  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  const hue = (seed * 47) % 360;

  ctx.fillStyle = `hsl(${hue} 20% 90%)`;
  ctx.fillRect(0, 0, w, h);

  if (backgroundType !== 'flat') {
    ctx.strokeStyle = `hsl(${hue} 20% 78%)`;
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 8]);
    ctx.strokeRect(16, 16, w - 32, h - 32);
  }

  ctx.fillStyle = `hsl(${hue} 20% 45%)`;
  ctx.font = '600 26px sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(label, w / 2, h / 2);

  return canvas.toDataURL('image/png'); // data:image/png;base64,...
}

/** data URI에서 순수 base64만 뽑아낸다 (이미 prefix가 없으면 그대로 반환). */
function stripDataUriPrefix(value = '') {
  const commaIdx = value.indexOf(',');
  return value.startsWith('data:') && commaIdx >= 0 ? value.slice(commaIdx + 1) : value;
}

// background 값 mock — 실제로는 draft 응답에 실려 오고, refine 요청 때 그대로
// echo해야 동일 배경이 재현된다(서버 무상태). type이 'gradient'(flat)인지 'ai'인지로
// 화면 E의 "같은 배경으로 다른 이미지 생성하기" 버튼 노출 여부를 가른다.
function mockBackground(seed, backgroundType) {
  if (backgroundType === 'flat') {
    const hue = (seed * 47) % 360;
    return { type: 'gradient', colors: [`hsl(${hue} 30% 92%)`, `hsl(${hue} 30% 78%)`] };
  }
  return { type: 'ai' };
}

/**
 * POST /generate/drafts 목 함수. 화면 A에서 저장한 mode/image/ratio를 그대로 넘겨받는다.
 * backgroundType: 'ai' | 'flat' — 화면 C에서 고른 배경 종류(3:4에서는 항상 'flat'로 강제됨).
 */
export async function generateDrafts({
  mode = 'text2img',
  image = null,
  prompt = '',
  ratio = '1:1',
  backgroundType = 'ai',
  num_images = 3,
} = {}) {
  await delay();

  // 실제 /generate/drafts 응답의 image도 prefix 없는 순수 base64라 mock도 캔버스
  // data URI에서 prefix를 떼어 맞춰준다 — 화면 쪽(화면 C)에서 표시할 땐 toImageSrc()로
  // 다시 감싸야 하고, refine에 넘길 땐 이 순수 base64를 그대로 재전송하면 된다.
  const drafts = SEEDS.slice(0, num_images).map((seed, idx) => ({
    id: `d${idx + 1}`,
    image: stripDataUriPrefix(placeholderImage(seed, `시안 ${idx + 1}`, ratio, backgroundType)),
    seed,
    background: mockBackground(seed, backgroundType),
  }));

  return {
    drafts,
    meta: {
      elapsed: 9.8,
      model: mode === 'inpaint' ? 'sd15-inpaint' : 'sd15',
      mode,
      prompt,
      ratio,
      backgroundType,
      usedProductImage: Boolean(image),
    },
  };
}

/**
 * 실제 /generate/drafts, /generate/refine 응답의 image는 모두 순수 base64
 * (data: prefix 없음)로 내려온다. 화면에서 <img src>로 바로 쓰려면 이 어댑터로
 * 감싸야 한다 — 실서버 연동 시에도 이 함수 하나만 그대로 붙이면 됨
 * (docs/UIUX_스펙정리.md 5장 참고). draft_image로 refine에 재전송할 땐 이 변환
 * 이전의 순수 base64를 그대로 써야 한다(변환은 표시용일 뿐).
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
 *
 * text는 그대로 받아 meta.layout.text로 echo한다 — text.font_id(화면 D 서체
 * 드롭다운 선택값)도 별도 처리 없이 그 안에 실려 함께 내려간다.
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
