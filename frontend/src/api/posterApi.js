/**
 * 포스터 이미지 생성 API.
 * (docs/UIUX_스펙정리.md 5장 "포스터 모델" 참고, 8/10 용도→비율 매핑 반영)
 *
 *   POST /generate/drafts  { mode, image?, prompt, ratio, backgroundType?, num_images } → DraftSelect.jsx (화면 C, 로딩 A)
 *   POST /generate/refine  { draft_image, original_image, background, prompt, text } → PosterEditor.jsx (화면 D, 로딩 B)
 *
 * copyApi.js와 동일한 패턴: 아래는 크게 두 갈래로 나뉜다(컴포넌트는 둘 중 뭐가
 * 쓰이는지 몰라도 됨).
 *   - mockGenerateDrafts()/mockGenerateRefine() : 실서버 없이 프론트 흐름만
 *     검증하던 기존 mock (그대로 보존)
 *   - realGenerateDrafts()/realGenerateRefine() : 실제 백엔드(poster_model,
 *     기본 http://localhost:8000) 호출 어댑터. 요청/응답 필드는
 *     poster_model/api.py + poster_model/docs/api.md를 직접 읽고 맞췄다.
 * 맨 아래 generateDrafts/generateRefine이 실제 진입점이며,
 * VITE_USE_REAL_POSTER_API=true일 때만 real 쪽을, 아니면 mock 쪽을 그대로 쓴다.
 *
 * ⚠ 지우님 서버 접근 주소가 아직 확정 전이라 real 경로는 코드 준비 + 로컬
 * 스모크 테스트까지만 하고, 실제 엔드투엔드 테스트는 나중에 진행한다.
 *
 * mock 실패 시뮬레이션(?mockFail=drafts,refine / ?mockFailRate=0.3)은 mockUtils.js
 * 참고 — 개발/테스트 중 재시도 버튼 동작을 확인할 때 쓴다(mock 모드 전용).
 */

import { MockApiError, maybeFail } from './mockUtils';

const MOCK_DELAY_MS = 900;
const SEEDS = [12345, 67890, 24680];

// --- 실제 서버 연동 스위치 -----------------------------------------------
// VITE_USE_REAL_POSTER_API=true면 아래 realXxx()가, 아니면 기존 mockXxx()가 쓰인다.
// (.env / .env.local에서 설정. 기본값은 false — 실제 서버 주소가 아직 확정 전.)
const USE_REAL_API = import.meta.env.VITE_USE_REAL_POSTER_API === 'true';
const REAL_API_BASE = import.meta.env.VITE_POSTER_API_BASE || 'http://localhost:8000';

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

/**
 * 챗봇 spec(화면 A)에서 포스터용 "배경 설명" 프롬프트를 만든다. 화면 C/D가 공유.
 *
 * 강조점 필드명이 mock/real에서 다르다 — mock copyApi.js(suggestOptions)는
 * spec.highlights(콤마로 합친 문자열)를 쓰고, 실제 백엔드(chatbot.py)는
 * spec.keywords(배열)를 내려준다. 여기서 둘 다 흡수해서 항상 문자열로 맞춘다
 * (실제 백엔드 필드명은 keywords가 우선 — 8/13 확인된 불일치 수정).
 *
 * spec.request(6단계 "추가 요청" 자유입력)도 이어붙인다 — 이전에는 buildPrompt()가
 * 아예 참조하지 않아서 6단계에 뭘 입력해도 포스터 prompt에 반영되지 않았다
 * (8/13 확인된 누락, 이번에 추가).
 */
export function buildPrompt(spec = {}) {
  const highlights = Array.isArray(spec.keywords)
    ? spec.keywords.join(', ')
    : spec.keywords || spec.highlights;
  return (
    [spec.tone, spec.product, highlights, spec.request].filter(Boolean).join(', ') || '포스터 배경'
  );
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
// echo해야 동일 배경이 재현된다(서버 무상태). type은 'gradient'(flat) 또는 'ai'.
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
export async function mockGenerateDrafts({
  mode = 'text2img',
  image = null,
  prompt = '',
  ratio = '1:1',
  backgroundType = 'ai',
  num_images = 3,
} = {}) {
  await delay();
  maybeFail('drafts');

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
export async function mockGenerateRefine({
  draft_image,
  original_image,
  background,
  prompt = '',
  text = {},
} = {}) {
  await delay(1100);
  maybeFail('refine');

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

// ============================================================================
// --- 실제 백엔드(poster_model, 기본 http://localhost:8000) 연동 --------------
// mock과 정확히 같은 요청/응답 형태로 컴포넌트(DraftSelect.jsx, PosterEditor.jsx)에
// 맞춰주는 어댑터 계층. 컴포넌트는 이 파일 안쪽이 mock인지 real인지 몰라도 된다.
// 필드는 poster_model/api.py(DraftRequest/RefineRequest/DraftItem 등)와
// poster_model/docs/api.md를 직접 읽고 맞췄다.
// ============================================================================

/**
 * 실제 서버 에러(네트워크 실패/4xx/5xx)를 사용자 친화적 메시지로 감싼다.
 * copyApi.js의 RealApiError와 동일한 패턴 — MockApiError를 상속해서
 * mockUtils.js의 toFriendlyMessage()가 그대로 인식한다(instanceof 체크 통과).
 */
class RealApiError extends MockApiError {
  constructor(key, customMessage) {
    super(key); // key(drafts|refine)에 대응하는 기본 친화 메시지를 우선 세팅
    this.name = 'RealApiError';
    if (customMessage) {
      this.message = customMessage;
      this.friendlyMessage = customMessage;
    }
  }
}

/** 실제 서버로 POST 요청을 보내고 실패를 RealApiError로 통일해서 던진다. */
async function postJSON(path, body, key) {
  let response;
  try {
    response = await fetch(`${REAL_API_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch {
    // fetch 자체가 실패 — 서버가 꺼져있거나 네트워크 문제
    throw new RealApiError(key, '서버에 연결할 수 없어요. 잠시 후 다시 시도해주세요.');
  }

  if (!response.ok) {
    // 원인은 콘솔에만 남기고, 화면에는 항상 사용자 친화적 메시지만 노출한다.
    // poster_model은 400 detail로 문자열뿐 아니라 구조화된 객체
    // ({error, message, ...})도 내려주므로 그대로 로그만 남긴다.
    let detail = '';
    try {
      detail = (await response.json())?.detail;
    } catch {
      // 응답이 JSON이 아닐 수도 있음 — 무시
    }
    console.error(`[posterApi] ${path} 실패 (${response.status})`, detail);
    throw new RealApiError(key);
  }

  return response.json();
}

/**
 * POST /generate/drafts 실제 호출.
 * 프론트 필드명 → 서버 필드명 매핑:
 *   ratio(문자열)          → aspect_ratio
 *   backgroundType('ai'|'flat') → background_mode('ai'|'gradient')
 *     ('flat'을 'gradient'로 매핑 — mock의 mockBackground()가 flat일 때
 *      type:'gradient'로 흉내내던 것과 동일한 선택. bg_colors를 생략하면
 *      서버가 category 기본 팔레트를 쓴다.)
 * image는 data: prefix가 있어도 서버가 알아서 떼어내므로 그대로 보낸다.
 *
 * 응답 DraftItem({id, image, seed, background})은 mock의 drafts[] 항목과
 * 필드명이 완전히 같아 별도 매핑 없이 그대로 반환한다.
 *
 * ⚠ 알려진 제약(UI는 아직 이 조합을 막지 않음, 실서버 연동 시 주의):
 *   - background_mode가 'gradient'/'solid'면 서버가 image를 요구한다.
 *     "사진 없이 진행"(mode=text2img) + 3:4(상세페이지, flat 강제)를 같이
 *     고르면 400이 난다 — poster_model/docs/api.md 참고.
 *   - AI 배경(background_mode='ai')은 1:1/3:1만 지원, 3:4는 400.
 *     DraftSelect.jsx가 3:4일 때 backgroundType을 'flat'으로 강제하므로
 *     현재 UI 흐름에서는 이 조합 자체가 발생하지 않는다.
 */
async function realGenerateDrafts({
  mode = 'text2img',
  image = null,
  prompt = '',
  ratio = '1:1',
  backgroundType = 'ai',
  num_images = 3,
} = {}) {
  const body = {
    mode,
    image: image || undefined,
    prompt: prompt || undefined,
    num_images,
    background_mode: backgroundType === 'flat' ? 'gradient' : 'ai',
    aspect_ratio: ratio,
  };
  const res = await postJSON('/generate/drafts', body, 'drafts');
  return { drafts: res.drafts || [], meta: res.meta };
}

/**
 * POST /generate/refine 실제 호출.
 * draft_image/original_image/background/prompt/text 모두 mock 호출부
 * (PosterEditor.jsx)가 넘기는 그대로 서버 필드명과 일치한다 — 별도 매핑 불필요:
 *   - background: realGenerateDrafts()가 돌려준 DraftItem.background를 그대로
 *     echo하면 이미 {mode, colors, direction} 형태라 서버 BackgroundSpec과 맞는다.
 *   - text: {headline, sub, x, y, headline_size, sub_size, style, font_id, align}
 *     전부 서버 TextSpec 필드와 이름이 같다.
 *   - aspect_ratio는 보내지 않는다 — 서버가 draft_image 크기에서 항상 추론하므로
 *     생략해도 기존 동작과 동일하다(poster_model/docs/api.md 참고).
 *
 * 응답 { image, meta }도 mock과 최상위 필드명이 완전히 같다.
 */
async function realGenerateRefine({
  draft_image,
  original_image,
  background,
  prompt = '',
  text = {},
} = {}) {
  const body = {
    draft_image,
    original_image: original_image || undefined,
    background: background || undefined,
    prompt: prompt || undefined,
    text,
  };
  const res = await postJSON('/generate/refine', body, 'refine');
  return { image: res.image, meta: res.meta };
}

// --- 컴포넌트가 실제로 import하는 진입점 -----------------------------------
// DraftSelect.jsx/PosterEditor.jsx는 이 두 함수만 알면 되고, mock/real 분기는
// VITE_USE_REAL_POSTER_API 값에 따라 여기서만 결정된다.

/** POST /generate/drafts — VITE_USE_REAL_POSTER_API=true면 실제 서버, 아니면 mock. */
export async function generateDrafts(args) {
  return USE_REAL_API ? realGenerateDrafts(args) : mockGenerateDrafts(args);
}

/** POST /generate/refine — VITE_USE_REAL_POSTER_API=true면 실제 서버, 아니면 mock. */
export async function generateRefine(args) {
  return USE_REAL_API ? realGenerateRefine(args) : mockGenerateRefine(args);
}
