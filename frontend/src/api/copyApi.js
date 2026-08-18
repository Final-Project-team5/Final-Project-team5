/**
 * 문구 생성/규제 검증 API + 제품 Vision 인식 API.
 * 요청/응답 형태는 docs/UIUX_스펙정리.md 5장(문구 모델) 기준을 따른다.
 *
 *   POST /suggest/options  { message, step, spec } → ChatFlow.jsx (화면 A, product 느낌/강조점/추가요청)
 *   POST /vision/product   { image_data_url, spec } → ChatFlow.jsx (화면 A, product 사진 단계 — PR #70, 리뷰 중)
 *   POST /generate/copy    { spec }                → { copies: [...] }(3개) → CopyResult.jsx (화면 B)
 *   POST /validate/copy    { headline, sub }        → CopyResult.jsx (화면 B, 선택한 문구 재검증)
 *
 * 이 파일 아래쪽은 크게 두 갈래로 나뉜다 (컴포넌트는 둘 중 뭐가 쓰이는지 몰라도 됨):
 *   - mockXxx()  : 실서버 없이 프론트 흐름만 검증하던 기존 mock (그대로 보존)
 *   - realXxx()  : 실제 백엔드(copy_model, 기본 http://localhost:8001) 호출 어댑터
 * 맨 아래 suggestOptions/visionProduct/generateCopy/validateCopy가 실제 진입점이며,
 * VITE_USE_REAL_COPY_API=true일 때만 real 쪽을, 아니면 mock 쪽을 그대로 쓴다.
 *
 * mock 실패 시뮬레이션(?mockFail=options,copy,validate,vision / ?mockFailRate=0.3)은
 * mockUtils.js 참고 — 개발/테스트 중 재시도 버튼 동작을 확인할 때 쓴다(mock 모드 전용).
 * Vision mock 결과를 강제로 바꾸고 싶으면 ?mockVision=auto_fill|confirm|reupload
 * 쿼리 파라미터를 쓴다(기본은 auto_fill) — 맞아요/수정할게요/재업로드 세 분기를
 * 실제 사진 없이도 재현해볼 수 있다.
 *
 * --- 8/14 챗봇 분기 개편 핵심 요약 (docs/UIUX_스펙정리.md 3-3·3-4장) ---
 * 0단계(business_type)·업종·용도는 이제 전부 프론트 하드코딩이라 서버 호출이
 * 없다. product는 업종/용도 확정 후 곧바로 사진 업로드 → Vision 인식으로
 * 넘어가며(제품명 직접 입력 질문 없음), Vision이 spec.product를 확정지어야만
 * 느낌(tone)부터 실제 /suggest/options 호출이 시작된다(백엔드 FLOW_STEPS
 * 기준 3=product/4=tone/5=keywords/6=request — 프론트는 4번부터 호출).
 *
 * service는 학원(academy)/체육관·도장(sports) 2업종만 지원하고 사진/제품명
 * 단계가 아예 없다. 문제는 PR #70 기준 서버 FLOW_STEPS에는 여전히 3번
 * "product" 슬롯이 남아있어(서비스형 오버라이드 질문 "어떤 서비스나 가게를
 * 홍보하시나요?"), 그 답을 하지 않고는 서버가 4번(tone) 질문을 내려줄 방법이
 * 없다는 점이다. 프론트에서 그 슬롯에 임의 값을 채워 우회하지 말라는 지시에
 * 따라, service의 느낌/강조점/추가요청은 서버 호출 없이 프론트 고정 선택지로
 * 진행한다(serviceAdvance) — mock/real 토글과 무관하게 항상 이 경로를 탄다.
 *
 * ⚠ Vision "맞아요/수정할게요" 확정 방식은 아직 공식 계약이 없다 — /suggest/options의
 * 3번(product) 슬롯을 프론트가 임의로 "확정 API"처럼 재사용하지 않기로 했다
 * (8/14 팀 합의). auto_fill은 /vision/product 응답에 이미 실려오는 suggestion을
 * 그대로 쓰지만(이건 PR #70이 실제로 구현한 동작), confirm/수정 경로는
 * confirmProductLocally()에 TODO 경계로 분리해뒀다 — real 모드에서는 아직
 * 아무 것도 호출하지 않고 "준비 중" 에러로 명확히 실패시킨다(mock 모드는 로컬
 * 데이터로만 진행 — 실제 서버에는 어떤 요청도 보내지 않는다). PR #70 리뷰
 * 답변으로 공식 계약이 정해지면 그 함수 안쪽만 실제 API 호출로 교체하면 된다.
 * 이 부분과 /generate/copy의 academy/sports 지원 여부는 모두 백엔드 리뷰
 * 답변 대기 상태다(하단 각주 참고).
 */

import { MockApiError, maybeFail } from './mockUtils';

const MOCK_DELAY_MS = 400;

// --- 실제 서버 연동 스위치 -----------------------------------------------
// VITE_USE_REAL_COPY_API=true면 아래 realXxx()가, 아니면 기존 mockXxx()가 쓰인다.
// (.env / .env.local에서 설정 — README나 .env.example 참고)
const USE_REAL_API = import.meta.env.VITE_USE_REAL_COPY_API === 'true';
const REAL_API_BASE = import.meta.env.VITE_COPY_API_BASE || 'http://localhost:8001';

function delay(ms = MOCK_DELAY_MS) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// UI 진행률(n/총단계) — business_type별 표시 분모를 프론트가 직접 관리한다.
// PR #70 서버 total_steps는 product/service 모두 6을 내려주지만(FLOW_STEPS
// 길이가 같음), 최신 UI 기준 표시 분모는 product 7 / service 6로 다르다
// (docs/UIUX_스펙정리.md 3-4장 — 답변 대기, 서버값을 그대로 쓰지 않는다).
export const TOTAL_STEPS_BY_TYPE = { product: 7, service: 6 };

// --- 0단계 — business_type (프론트 하드코딩, 8/14 확정) --------------------
// 서버는 이 시점에 business_type을 아직 몰라 내려줄 선택지 자체가 없다
// (docs/UIUX_스펙정리.md 3-3장) — 프론트가 고정 질문/선택지를 들고 있는다.
export const BUSINESS_TYPE_QUESTION_TEXT = '제품이 있으신가요, 서비스 위주이신가요?';
export const BUSINESS_TYPE_OPTIONS = [
  { value: 'product', label: '제품이 있어요 (사진 촬영 가능)' },
  { value: 'service', label: '서비스 위주예요 (사진 없이 진행)' },
];

// --- 1단계 — 업종 (프론트 하드코딩) -----------------------------------
// product/service 모두 지원 업종이 고정된 소수 집합이라(Vision·CopyRequest가
// 요구하는 enum과 정확히 일치해야 함) LLM 자유 매핑 없이 프론트가 값을 직접 emit한다.
export const CATEGORY_QUESTION_TEXT_BY_TYPE = {
  product: '어떤 업종이신가요?',
  service: '어떤 서비스 업종이신가요?',
};
// 업종 화면 안내 문구 (8/14 신규) — 서비스형 업종이 2개뿐이라 실망하지 않도록.
export const CATEGORY_HINT_TEXT = '업종은 계속 추가될 예정이에요.';
export const CATEGORY_OPTIONS_BY_TYPE = {
  product: [
    { value: 'food', label: '푸드' },
    { value: 'beauty', label: '뷰티' },
    { value: 'goods', label: '굿즈' },
  ],
  service: [
    { value: 'academy', label: '학원' },
    { value: 'sports', label: '체육관·도장' },
  ],
};

// --- 2단계 — 용도 (프론트 하드코딩, 8/14 확정) ------------------------
// 비율 매핑도 프론트가 직접 들고 있는다(서버 매핑 응답을 기다리지 않음).
export const USAGE_QUESTION_TEXT = '이 포스터는 어디에 사용하실 예정인가요?';
export const USAGE_OPTIONS_BY_TYPE = {
  product: [
    { value: 'sns', label: 'SNS', aspect_ratio: '1:1' },
    { value: 'banner', label: '배너', aspect_ratio: '3:1' },
    { value: 'detail', label: '상세페이지', aspect_ratio: '3:4' },
  ],
  // service는 SNS 1:1 고정 — 배너/상세는 선택지 자체를 노출하지 않는다.
  service: [{ value: 'sns', label: 'SNS', aspect_ratio: '1:1' }],
};

// --- 3단계(product 전용) — 사진 업로드 + Vision 인식 ------------------
export const PHOTO_GUIDE_TEXT = '최대한 깨끗한 배경(단색)에 제품이 1개만 나오도록 찍어주세요.';
export const ALLOWED_IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp'];
export const MAX_IMAGE_BYTES = 8 * 1024 * 1024; // 8 MiB — 프론트에서도 선제 차단

// 배경 참고 이미지(선택, 8/18 신규) — 제품 사진과 같은 질문 화면 안에서 받되
// 역할을 프론트가 처음부터 분리해서 관리한다(LLM이 이미지 역할을 자동 판별하지
// 않음). Vision 제품 인식 대상이 아니며, 확정된 poster API 계약이 아직 없어
// ChatFlow.jsx가 state로만 들고 있고 어떤 API에도 실제 전송하지 않는다
// (docs/UIUX_스펙정리.md — 배경 레퍼런스 계약 확정 전까지 mock/interface로 격리).
export const BACKGROUND_REFERENCE_LABEL = '배경 참고 이미지 업로드';
export const BACKGROUND_REFERENCE_GUIDE_TEXT =
  '선택 사항이에요. 원하는 배경 분위기가 있다면 참고 이미지를 함께 올려주세요. (제품 인식에는 사용되지 않아요)';

const TONE_OPTIONS = ['따뜻하고 아늑한', '깔끔하고 모던한', '화려하고 트렌디한', '자연스럽고 담백한'];
const HIGHLIGHT_OPTIONS = ['신선한 재료', '합리적인 가격', '특별한 이벤트', '브랜드 스토리'];
const EXTRA_OPTIONS = ['특별히 없어요', '이벤트를 강조해주세요', '가격을 강조해주세요', '심플하게 만들어주세요'];

// service 강조점 세트는 제품형과 결이 달라야 한다(docs 3-3장: 전문성·경력 /
// 후기·평판 / 접근성 / 상담·가격 안내). service는 서버 호출이 아예 없어
// (아래 serviceAdvance 참고) 느낌/강조점/추가요청 선택지를 여기서 고정해둔다.
const SERVICE_TONE_OPTIONS = ['신뢰감 있는 전문가 느낌', '활기찬 분위기', '차분하고 깔끔한 느낌', '따뜻하고 친근한 느낌'];
const SERVICE_HIGHLIGHT_OPTIONS = ['전문성·경력', '후기·평판', '접근성(위치·시간)', '상담·가격 안내'];
const SERVICE_REQUEST_OPTIONS = ['신규 개강', '무료 상담 이벤트', '수강료 할인', '특별히 없어요'];

/** 문구 3개(시안) 생성 전, /generate/copy 바디의 category enum과 정합되는지 확인하는 헬퍼. */
function categoryKey(category = '') {
  return ['food', 'beauty', 'goods'].includes(category) ? category : 'default';
}

// ============================================================================
// --- mock: /suggest/options (product 전용, 백엔드 FLOW_STEPS 3~6번 흉내) ---
// step 3(product)은 Vision 확정/보정 브리지가 호출하고, 4(tone)/5(keywords)/
// 6(request)는 ChatFlow가 순서대로 호출한다. 1(category)/2(purpose)는 이제
// 프론트 하드코딩이라 이 함수에 도달하지 않는다.
// ============================================================================

function buildQuestion(step) {
  switch (step) {
    case 4:
      return { question: '원하시는 포스터 느낌은 어떤가요?', options: TONE_OPTIONS, multiSelect: false, freeform: false };
    case 5:
      return {
        question: '강조하고 싶은 점은 무엇인가요? (복수 선택 가능)',
        options: HIGHLIGHT_OPTIONS,
        multiSelect: true,
        freeform: false,
      };
    case 6:
      return { question: '추가로 요청하실 사항이 있나요?', options: EXTRA_OPTIONS, multiSelect: false, freeform: true };
    default:
      return { question: '', options: [], multiSelect: false, freeform: false };
  }
}

function buildConfirmMessage(step, spec) {
  switch (step) {
    case 3:
      return `${spec.product}, 멋지네요!`;
    case 4:
      return '좋은 느낌이에요!';
    case 5:
      return '강조 포인트 확인했어요!';
    case 6:
      return '모든 답변을 확인했어요. 문구를 만들어볼게요!';
    default:
      return '';
  }
}

/**
 * POST /suggest/options 목 함수 (product step 3~6 전용, 백엔드 번호 그대로 사용).
 * message: 사용자가 고른 선택지 텍스트 / Vision 확정·보정 제품명
 * step: 직전 응답의 next_step 값(3부터 시작 — Vision 브리지가 최초 호출)
 * spec: 누적 상태
 */
export async function mockSuggestOptions({ message, step = 3, spec = {} } = {}) {
  await delay();
  maybeFail('options');

  const nextSpec = { ...spec };
  switch (step) {
    case 3:
      nextSpec.product = message;
      break;
    case 4:
      nextSpec.tone = message;
      break;
    case 5:
      nextSpec.keywords = message.split(',').map((s) => s.trim()).filter(Boolean);
      break;
    case 6:
      nextSpec.request = message;
      break;
    default:
      break;
  }

  if (step >= 6) {
    return {
      step,
      next_step: null,
      total_steps: 6,
      question: null,
      options: [],
      multiSelect: false,
      freeform: false,
      spec: nextSpec,
      confirm_message: buildConfirmMessage(step, nextSpec),
      done: true,
    };
  }

  const nextStep = step + 1;
  const { question, options, multiSelect, freeform } = buildQuestion(nextStep);

  return {
    step,
    next_step: nextStep,
    total_steps: 6,
    question,
    options,
    multiSelect,
    freeform,
    spec: nextSpec,
    confirm_message: buildConfirmMessage(step, nextSpec),
    done: false,
  };
}

/**
 * Vision "맞아요"(confirm 분기, auto_fill의 캐시된 suggestion이 없는 경우)와
 * "수정할게요"(사용자가 이름을 직접 고친 경우) 전용 — 확정/보정한 이름을
 * spec.product에 반영하고 다음(느낌) 질문을 만든다.
 *
 * ⚠ TODO(PR #70 리뷰 답변 대기): 이 확정을 서버에 공식적으로 알리는 계약이
 * 아직 없다. 예전에는 여기서 `/suggest/options`의 3번(product) 슬롯을
 * 재사용해 서버를 호출했으나, 백엔드와 합의되지 않은 임의 계약이라 제거했다.
 * 지금은:
 *   - real 모드: 아무 것도 호출하지 않고 "아직 준비되지 않았다"는 에러를
 *     명시적으로 던진다 — 조용히 잘못된 값을 만들어내지 않기 위함.
 *   - mock 모드: 테스트/데모용으로 로컬 mock 데이터만으로 느낌 질문까지
 *     진행한다(실제 서버에는 어떤 요청도 보내지 않는다).
 * 공식 계약이 정해지면 real 분기 안쪽만 실제 API 호출로 채우면 된다.
 */
export async function confirmProductLocally({ name, spec = {} } = {}) {
  if (USE_REAL_API) {
    throw new MockApiError('productConfirm');
  }

  await delay(150);
  const nextSpec = { ...spec, product: name };
  const { question, options, multiSelect, freeform } = buildQuestion(4);
  return {
    step: 3,
    next_step: 4,
    total_steps: 6,
    question,
    options,
    multiSelect,
    freeform,
    spec: nextSpec,
    confirm_message: buildConfirmMessage(3, nextSpec),
    done: false,
  };
}

// ============================================================================
// --- mock: /vision/product (product 3단계 — 제품 사진 인식) ----------------
// PR #70의 vision.py `_mock_context`/`_finalize_context`와 같은 판정 정책을
// 흉내낸다: clear+category 일치 → auto_fill / ambiguous·mismatch → confirm /
// invalid → reupload. ?mockVision=auto_fill|confirm|reupload로 강제 가능.
// ============================================================================

const MOCK_VISION_SAMPLES = {
  food: { product: '쿠키 세트', detected_category: 'food', visible_features: ['박스 포장', '개별 쿠키가 보임'] },
  beauty: { product: '립 틴트', detected_category: 'beauty', visible_features: ['원통형 패키지', '핑크 계열'] },
  goods: { product: '다이어리', detected_category: 'goods', visible_features: ['책 형태', '하드 커버'] },
};

// confirm(category mismatch) mock 전용 — requested_category와 다른 카테고리의
// 샘플을 "detected"로 골라서 실제 판정 로직(vision.py `_finalize_context`의
// category_match = detected == requested_category)과 같은 방식으로 계산해도
// 항상 false가 나오게 한다(진짜 불일치를 재현).
const MISMATCH_CATEGORY_BY_CATEGORY = { food: 'beauty', beauty: 'goods', goods: 'food' };

function mockVisionOverride() {
  const raw = new URLSearchParams(window.location.search).get('mockVision');
  return ['auto_fill', 'confirm', 'reupload'].includes(raw) ? raw : null;
}

function buildMockVisionContext(category, forced) {
  const sample = MOCK_VISION_SAMPLES[category] || MOCK_VISION_SAMPLES.goods;
  const base = {
    requested_category: category,
    visible_text: [],
    candidates: [],
  };

  if (forced === 'reupload') {
    return {
      ...base,
      product: null,
      detected_category: 'unknown',
      category_match: false,
      visible_features: [],
      recognition_status: 'invalid',
      next_action: 'reupload',
    };
  }
  if (forced === 'confirm') {
    // 이전엔 requested_category와 같은 카테고리의 샘플을 쓰면서 category_match만
    // false로 하드코딩해 requested===detected인데 mismatch라는 모순 데이터였다.
    // 실제로 다른 카테고리의 샘플을 "인식 결과"로 써서 category_match를
    // 계산값(detected === requested)으로 채운다 — 결과는 항상 false지만,
    // 데이터 자체가 자기모순 없는 진짜 mismatch를 재현한다.
    const detectedCategory = MISMATCH_CATEGORY_BY_CATEGORY[category] || 'goods';
    const detectedSample = MOCK_VISION_SAMPLES[detectedCategory];
    return {
      ...base,
      product: detectedSample.product,
      detected_category: detectedSample.detected_category,
      category_match: detectedSample.detected_category === category,
      visible_features: detectedSample.visible_features,
      recognition_status: 'clear',
      next_action: 'confirm',
    };
  }
  return {
    ...base,
    product: sample.product,
    detected_category: sample.detected_category,
    category_match: true,
    visible_features: sample.visible_features,
    recognition_status: 'clear',
    next_action: 'auto_fill',
  };
}

/**
 * POST /vision/product 목 함수. 실제 이미지 인식은 하지 않고(비용 0), 사진 대신
 * category와 ?mockVision 쿼리로 결과를 결정한다 — UI 흐름(맞아요/수정할게요/
 * 재업로드) 검증용. auto_fill이면 PR #70과 동일하게 내부적으로 step 3을 한 번
 * 더 태워 tone 질문(suggestion)까지 함께 반환한다.
 */
export async function mockVisionProduct({ spec = {} } = {}) {
  await delay(700);
  maybeFail('vision');

  const category = spec.category || 'goods';
  const context = buildMockVisionContext(category, mockVisionOverride());

  const productContext = {
    product: context.product,
    detected_category: context.detected_category,
    category_match: context.category_match,
    visible_features: context.visible_features,
    visible_text: context.visible_text,
    recognition_status: context.recognition_status,
    next_action: context.next_action,
  };
  const baseSpec = { ...spec, product_context: productContext };

  if (context.next_action !== 'auto_fill') {
    delete baseSpec.product;
    return { context, spec: baseSpec, suggestion: null, meta: { model: 'mock', mock: true, advanced: false } };
  }

  baseSpec.product = context.product;
  const suggestion = await mockSuggestOptions({ message: context.product, step: 3, spec: baseSpec });
  return {
    context,
    spec: suggestion.spec,
    suggestion,
    meta: { model: 'mock', mock: true, advanced: true },
  };
}

// --- service 전용 — 서버 호출 없는 고정 진행(tone/keywords/request) --------
// 이유: 백엔드 FLOW_STEPS 3번(product) 슬롯이 service에도 남아있어(질문:
// "어떤 서비스나 가게를 홍보하시나요?"), 그 답 없이는 서버가 4번(tone) 질문을
// 내려줄 방법이 없다. 그 슬롯에 임의 값을 채워 우회하지 않기로 했으므로
// (docs/UIUX_스펙정리.md 3-4장 리뷰 답변 대기), service는 mock/real 여부와
// 관계없이 항상 이 고정 진행을 탄다. 응답 모양은 suggestOptions와 동일하게
// 맞춰서 ChatFlow가 business_type에 상관없이 같은 렌더링 경로를 쓸 수 있게 한다.
export const SERVICE_FLOW = [
  { slot: 'tone', question: '원하시는 포스터 느낌은 어떤가요?', options: SERVICE_TONE_OPTIONS, multiSelect: false, freeform: false },
  {
    slot: 'keywords',
    question: '강조하고 싶은 점은 무엇인가요? (복수 선택 가능)',
    options: SERVICE_HIGHLIGHT_OPTIONS,
    multiSelect: true,
    freeform: false,
  },
  { slot: 'request', question: '추가로 요청하실 사항이 있나요?', options: SERVICE_REQUEST_OPTIONS, multiSelect: false, freeform: true },
];

function serviceConfirmMessage(slot) {
  switch (slot) {
    case 'tone':
      return '좋은 느낌이에요!';
    case 'keywords':
      return '강조 포인트 확인했어요!';
    case 'request':
      return '모든 답변을 확인했어요. 문구를 만들어볼게요!';
    default:
      return '';
  }
}

/**
 * service 전용 진행 함수. step 1=tone 답변, 2=keywords 답변, 3=request 답변
 * (SERVICE_FLOW 내부 인덱스 — 백엔드 FLOW_STEPS 번호와는 무관). 실제 네트워크
 * 호출은 없지만 suggestOptions와 동일한 응답 모양을 반환해 ChatFlow가 그대로
 * pushQuestion에 사용할 수 있게 한다.
 */
export async function serviceAdvance({ message, step = 1, spec = {} } = {}) {
  await delay(150);
  const cfg = SERVICE_FLOW[step - 1];
  const nextSpec = { ...spec };
  if (cfg.slot === 'keywords') {
    nextSpec.keywords = message.split(',').map((s) => s.trim()).filter(Boolean);
  } else {
    nextSpec[cfg.slot] = message;
  }

  const done = step >= SERVICE_FLOW.length;
  if (done) {
    return {
      step,
      next_step: null,
      total_steps: SERVICE_FLOW.length,
      question: null,
      options: [],
      multiSelect: false,
      freeform: false,
      spec: nextSpec,
      confirm_message: serviceConfirmMessage(cfg.slot),
      done: true,
    };
  }

  const next = SERVICE_FLOW[step];
  return {
    step,
    next_step: step + 1,
    total_steps: SERVICE_FLOW.length,
    question: next.question,
    options: next.options,
    multiSelect: next.multiSelect,
    freeform: next.freeform,
    spec: nextSpec,
    confirm_message: serviceConfirmMessage(cfg.slot),
    done: false,
  };
}

// --- 규제 룰 사전 (데모용 간이 버전, copy_model/regulation.py 구조 참고) ---
// severity: "block"(사용 불가 수준) / "warn"(맥락 확인 필요)
// suggestion: 걸린 표현을 대신할 수 있는 대체 표현 (8/6 스펙 추가분)
const COMMON_RULES = [
  {
    pattern: /최고|최상|제일|넘버\s*원|1\s*위/,
    severity: 'warn',
    note: '표시광고법: 객관적 근거 없는 최상급 표현은 부당광고 소지가 있어요.',
    suggestion: '많은 분들이 찾는',
  },
  {
    pattern: /100\s*%|백\s*퍼센트|완벽|완전\s*무결/,
    severity: 'warn',
    note: '표시광고법: 검증이 불가능한 확정적 표현이에요.',
    suggestion: '정성껏 준비한',
  },
  {
    pattern: /유일|국내\s*유일|세계\s*유일/,
    severity: 'warn',
    note: '표시광고법: 배타성을 주장하려면 입증 자료가 필요해요.',
    suggestion: '특별하게 준비한',
  },
  {
    pattern: /보장|장담/,
    severity: 'warn',
    note: '표시광고법: 효과·결과를 보장하는 표현은 주의가 필요해요.',
    suggestion: '기대하셔도 좋은',
  },
];

const FOOD_RULES = [
  {
    pattern: /치료|치유|낫는다|완치/,
    severity: 'block',
    note: '식품표시광고법 §8: 질병 치료 효능을 표방하는 표현은 금지돼요.',
    suggestion: '맛있게 즐기는',
  },
  {
    pattern: /예방|항암|항염|항균|살균/,
    severity: 'block',
    note: '식품표시광고법 §8: 질병 예방·의약품으로 오인될 수 있는 표현이에요.',
    suggestion: '건강한 하루를 위한',
  },
  {
    pattern: /다이어트\s*(효과|보장)|살\s*빠지는|지방\s*분해/,
    severity: 'block',
    note: '식품표시광고법: 체중 감량 효능 표방은 건강기능식품 인증이 필요해요.',
    suggestion: '가볍게 즐기는',
  },
  {
    pattern: /면역력\s*(강화|증진)|디톡스|해독/,
    severity: 'warn',
    note: '식품표시광고법: 신체 기능 개선 표방은 기능성 인정이 필요해요.',
    suggestion: '든든하게 채우는',
  },
  {
    pattern: /숙취\s*해소/,
    severity: 'warn',
    note: '식약처 고시: 숙취해소 표현은 인체적용시험 근거가 필요해요.',
    suggestion: '든든한 하루를 여는',
  },
];

const BEAUTY_RULES = [
  {
    pattern: /치료|치유|의학적|병원\s*급/,
    severity: 'block',
    note: '화장품법 §13: 의약품으로 오인될 수 있는 표현은 금지돼요.',
    suggestion: '편안하게 가꾸는',
  },
  {
    pattern: /(아토피|여드름|습진|건선)\s*(치료|개선)/,
    severity: 'block',
    note: '화장품법: 질환명과 함께 쓰인 개선 표현은 의약품 오인 광고예요.',
    suggestion: '산뜻하게 가꾸는',
  },
  {
    pattern: /(아토피|여드름|습진|건선)(?!\s*(치료|개선))/,
    severity: 'warn',
    note: '화장품법: 특정 질환을 직접 언급하면 의약품으로 오인될 수 있어요.',
    suggestion: '트러블 케어',
  },
  {
    pattern: /재생|세포\s*(재생|활성)|콜라겐\s*생성/,
    severity: 'warn',
    note: '화장품법: 신체 개선 효능을 단정하는 표현은 주의가 필요해요.',
    suggestion: '탄력을 더하는',
  },
  {
    pattern: /주름\s*(제거|박멸)|미백\s*보장/,
    severity: 'block',
    note: '화장품법: 기능성 인증 범위를 넘어서는 표현이에요.',
    suggestion: '결을 가꾸는',
  },
  {
    pattern: /부작용\s*(전혀|절대)\s*없/,
    severity: 'block',
    note: '화장품법: 부작용이 전혀 없다는 단정 표현은 금지돼요.',
    suggestion: '순하게 사용할 수 있는',
  },
];

const GOODS_RULES = [
  {
    pattern: /정품\s*보다|명품\s*급|짝퉁/,
    severity: 'warn',
    note: '상표법/표시광고법: 타 브랜드를 연상시키는 비교 표현은 주의가 필요해요.',
    suggestion: '고급스러운',
  },
  {
    pattern: /친환경|에코/,
    severity: 'warn',
    note: '환경성 표시광고 고시: 인증 없는 친환경 주장은 그린워싱 소지가 있어요.',
    suggestion: '자연스러운',
  },
];

const CATEGORY_RULES = {
  food: [...COMMON_RULES, ...FOOD_RULES],
  beauty: [...COMMON_RULES, ...BEAUTY_RULES],
  goods: [...COMMON_RULES, ...GOODS_RULES],
  // academy/sports 전용 룰은 아직 없음 — 도혁님 쪽 업종 확장(8/13 확정) 후 추가 예정.
  // 그 전까지는 공통 룰만 적용한다.
  default: COMMON_RULES,
};

/** 텍스트를 스캔해 규제 위반/주의 표현을 찾는다 (mock 버전 룰 매칭). */
function scanRegulation(text, spec = {}) {
  const rules = CATEGORY_RULES[categoryKey(spec.category)] || COMMON_RULES;
  const flags = [];
  for (const rule of rules) {
    const match = rule.pattern.exec(text);
    if (match) {
      flags.push({
        pattern: match[0],
        severity: rule.severity,
        note: rule.note,
        suggestion: rule.suggestion,
      });
    }
  }
  const hasBlock = flags.some((f) => f.severity === 'block');
  const status = hasBlock ? 'block' : flags.some((f) => f.severity === 'warn') ? 'warn' : 'pass';
  // safe: block 위반이 없으면 true (copy_model/regulation.py의 ValidateResponse.safe와 동일 규칙).
  // 실제 API가 이 필드를 내려주면 화면 쪽 로직은 그대로 갈아끼울 수 있도록,
  // 여기서 미리 계산해서 응답에 실어 보낸다.
  const safe = !hasBlock;
  return { status, flags, safe };
}

function truncate(text = '', max) {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/** spec.keywords(배열, 실제 계약 기준) — 과거 mock이 쓰던 spec.highlights(문자열)는 더 이상 만들지 않는다. */
function splitKeywords(spec) {
  if (Array.isArray(spec.keywords) && spec.keywords.length) return spec.keywords;
  if (typeof spec.keywords === 'string' && spec.keywords.trim()) {
    return spec.keywords.split(',').map((k) => k.trim()).filter(Boolean);
  }
  return ['특별한 매력'];
}

/**
 * 문구 3개(시안) 후보를 만든다 (8/8 진우님 리뷰 반영 — /generate/copy는 headline/sub
 * 조합을 3개 반환하는 구조). 서로 다른 템플릿을 써서 강조점 조합이 갈리게 해두면,
 * 문구마다 규제 검증 결과가 달라지는 상황(일부만 block/warn)도 자연스럽게 재현된다.
 */
function buildCopyCandidates(spec) {
  const product = spec.product || '우리 브랜드';
  const tone = spec.tone || '자연스러운';
  const keywords = splitKeywords(spec);
  const first = keywords[0] || '특별한 매력';
  const second = keywords[1] || first;

  return [
    {
      headline: truncate(`${product}, ${first}`, 20),
      sub: truncate(`${tone} 느낌으로 ${first}을 담았어요`, 30),
    },
    {
      headline: truncate(`${first}, ${product}에서 만나보세요`, 20),
      sub: truncate(`${tone} 스타일로 준비했어요`, 30),
    },
    {
      headline: truncate(`${product} 추천, ${second}`, 20),
      sub: truncate(`${second}로 특별한 하루를 만들어보세요`, 30),
    },
  ];
}

/**
 * POST /generate/copy 목 함수. 챗봇 마지막 단계(추가요청) 완료 후 자동으로 이어서 호출한다.
 * 응답은 `copies` 배열(3개) — 각 항목이 headline/sub와 함께 자기 자신의
 * regulation_flags/safe/status를 따로 갖는다(문구마다 규제 상태가 다를 수 있음).
 *
 * ⚠ service(academy/sports)는 실제 /generate/copy가 category enum(food/beauty/goods)
 * 만 허용해 real 모드에서는 422가 날 수 있다(백엔드 지원 대기, docs 3-4장) — mock은
 * category 제약이 없어 데모용으로는 그대로 동작한다.
 */
export async function mockGenerateCopy(spec = {}) {
  await delay(600);
  maybeFail('copy');

  const candidates = buildCopyCandidates(spec);
  // 실제 화면에 노출/수정되는 headline+sub만 검사한다 — 그래야 화면 B에서
  // "이 표현으로 바꿀게요"를 눌렀을 때 flag.pattern이 입력창 안에서 실제로 매칭된다.
  const copies = candidates.map((candidate, idx) => {
    const { status, flags, safe } = scanRegulation(`${candidate.headline} ${candidate.sub}`, spec);
    return {
      id: `c${idx + 1}`,
      headline: candidate.headline,
      sub: candidate.sub,
      status,
      regulation_flags: flags,
      safe,
    };
  });

  return { copies };
}

/** POST /validate/copy 목 함수. 사용자가 문구를 직접 수정했을 때 재검증한다. */
export async function mockValidateCopy({ headline = '', sub = '' } = {}, spec = {}) {
  await delay(300);
  maybeFail('validate');
  const { status, flags, safe } = scanRegulation(`${headline} ${sub}`, spec);
  return { status, flags, safe };
}

// ============================================================================
// --- 실제 백엔드(copy_model, 기본 http://localhost:8001) 연동 -----------------
// mock과 정확히 같은 요청/응답 형태로 컴포넌트(ChatFlow.jsx, CopyResult.jsx)에
// 맞춰주는 어댑터 계층. 컴포넌트는 이 파일 안쪽이 mock인지 real인지 몰라도 된다.
// ============================================================================

/**
 * 실제 서버 에러(네트워크 실패/4xx/5xx)를 사용자 친화적 메시지로 감싼다.
 * MockApiError를 상속해서 mockUtils.js의 toFriendlyMessage()가 그대로 인식한다
 * (instanceof MockApiError 체크를 그대로 통과) — 별도 처리 분기를 컴포넌트 쪽에
 * 추가할 필요가 없다.
 */
class RealApiError extends MockApiError {
  constructor(key, customMessage) {
    super(key); // key에 대응하는 기본 친화 메시지를 우선 세팅
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
    // 원인은 콘솔에만 남기고, 화면에는 항상 사용자 친화적 메시지만 노출한다
    // (mockUtils.js MockApiError와 동일한 정책 — 8/11 스펙 3장).
    let detail = '';
    try {
      detail = (await response.json())?.detail || '';
    } catch {
      // 응답이 JSON이 아닐 수도 있음 — 무시
    }
    console.error(`[copyApi] ${path} 실패 (${response.status})`, detail);
    throw new RealApiError(key);
  }

  return response.json();
}

/** 규제 flag severity로 status(pass/warn/block)를 판정한다 — mock scanRegulation과 동일 규칙. */
function deriveStatus(flags) {
  if (flags.some((f) => f.severity === 'block')) return 'block';
  if (flags.some((f) => f.severity === 'warn')) return 'warn';
  return 'pass';
}

/**
 * 서버 RegulationFlag({matched, severity, reason, suggestion}) →
 * mock 형태({pattern, severity, note, suggestion})로 필드명을 맞춘다.
 * CopyResult.jsx가 flag.pattern/flag.note를 그대로 참조하므로 이 매핑이 꼭 필요하다.
 */
function mapRegulationFlags(flags = []) {
  return flags.map((f) => ({
    pattern: f.matched,
    severity: f.severity,
    note: f.reason,
    suggestion: f.suggestion || '',
  }));
}

/** 서버 SuggestResponse(raw) → 컴포넌트가 쓰는 공통 모양으로 매핑. suggestOptions/vision 양쪽에서 공유. */
function mapSuggestRaw(res) {
  const done = Boolean(res.done);
  return {
    step: res.step,
    next_step: res.next_step ?? null,
    total_steps: res.total_steps,
    question: res.question,
    options: res.options || [],
    multiSelect: Boolean(res.allow_multiple),
    freeform: !done && res.next_step === res.total_steps,
    spec: res.spec || {},
    confirm_message: res.confirm_message || '',
    done,
  };
}

/**
 * POST /suggest/options 실제 호출 (product step 3~6 전용 — 3은 Vision 브리지가,
 * 4~6은 ChatFlow가 호출한다. 1/2는 프론트 하드코딩이라 호출하지 않는다).
 * { message, step, spec, mode: "fixed" } 전송 → SuggestResponse를 mock과
 * 동일한 형태로 매핑한다.
 */
async function realSuggestOptions({ message, step = 3, spec = {} } = {}) {
  const res = await postJSON('/suggest/options', { message, step, spec, mode: 'fixed' }, 'options');
  return mapSuggestRaw(res);
}

/**
 * POST /vision/product 실제 호출 (PR #70, 리뷰 중 — 현재 연결된 서버에 아직
 * 배포되지 않았다면 404/RealApiError로 실패한다). 요청 바디는
 * { image_data_url, spec }이며 spec.category가 food/beauty/goods 중 하나여야
 * 서버 유효성 검사를 통과한다.
 */
async function realVisionProduct({ imageDataUrl, spec = {} } = {}) {
  const res = await postJSON('/vision/product', { image_data_url: imageDataUrl, spec }, 'vision');
  return {
    context: res.context,
    spec: res.spec || {},
    suggestion: res.suggestion ? mapSuggestRaw(res.suggestion) : null,
    meta: res.meta || {},
  };
}

/**
 * POST /generate/copy 실제 호출.
 * spec 전체(+ num_candidates: 3)를 그대로 보낸다 — aspect_ratio/purpose 등
 * CopyRequest가 모르는 필드는 서버가 무시한다. 응답 candidates[]를 mock의
 * copies[]와 같은 형태({id, headline, sub, status, regulation_flags, safe})로 맞춘다.
 */
async function realGenerateCopy(spec = {}) {
  const res = await postJSON('/generate/copy', { ...spec, num_candidates: 3 }, 'copy');
  const copies = (res.candidates || []).map((c) => {
    const flags = mapRegulationFlags(c.regulation_flags);
    return {
      id: c.id,
      headline: c.headline,
      sub: c.sub,
      status: deriveStatus(flags),
      regulation_flags: flags,
      safe: c.safe,
    };
  });
  return { copies };
}

/**
 * POST /validate/copy 실제 호출.
 * { category, headline, sub, use_llm: false } 전송(룰 기반 검증만 — 비용 없음).
 * 응답 { safe, flags }를 mock validateCopy와 동일한 { status, flags, safe }로 맞춘다.
 */
async function realValidateCopy({ headline = '', sub = '' } = {}, spec = {}) {
  const res = await postJSON(
    '/validate/copy',
    { category: spec.category, headline, sub, use_llm: false },
    'validate',
  );
  const flags = mapRegulationFlags(res.flags);
  return { status: deriveStatus(flags), flags, safe: res.safe };
}

// --- 컴포넌트가 실제로 import하는 진입점 -----------------------------------
// ChatFlow.jsx/CopyResult.jsx는 아래 함수들만 알면 되고, mock/real 분기는
// VITE_USE_REAL_COPY_API 값에 따라 여기서만 결정된다. business_type=service는
// suggestOptions/visionProduct 대상이 아니다(위 SERVICE_FLOW 각주 참고) — 항상
// serviceAdvance를 직접 호출한다.

/** POST /suggest/options — product 전용. VITE_USE_REAL_COPY_API=true면 실제 서버, 아니면 mock. */
export async function suggestOptions(args) {
  return USE_REAL_API ? realSuggestOptions(args) : mockSuggestOptions(args);
}

/** POST /vision/product — product 전용. VITE_USE_REAL_COPY_API=true면 실제 서버, 아니면 mock. */
export async function visionProduct(args) {
  return USE_REAL_API ? realVisionProduct(args) : mockVisionProduct(args);
}

/** POST /generate/copy — VITE_USE_REAL_COPY_API=true면 실제 서버, 아니면 mock. */
export async function generateCopy(spec) {
  return USE_REAL_API ? realGenerateCopy(spec) : mockGenerateCopy(spec);
}

/** POST /validate/copy — VITE_USE_REAL_COPY_API=true면 실제 서버, 아니면 mock. */
export async function validateCopy(payload, spec) {
  return USE_REAL_API ? realValidateCopy(payload, spec) : mockValidateCopy(payload, spec);
}
