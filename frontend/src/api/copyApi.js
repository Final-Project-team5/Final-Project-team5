/**
 * 문구 생성/규제 검증 API — mock 버전.
 * 실서버(도혁님 파트)가 준비되기 전까지 프론트 흐름 검증용으로 사용한다.
 * 요청/응답 형태는 docs/UIUX_스펙정리.md 5장(문구 모델) 기준을 따른다.
 *
 *   POST /suggest/options  { message, step, spec } → chat.jsx (화면 A)
 *   POST /generate/copy    { spec }                → CopyResult.jsx (화면 B)
 *   POST /validate/copy    { headline, sub }        → CopyResult.jsx (화면 B)
 */

const MOCK_DELAY_MS = 400;
export const TOTAL_STEPS = 5;

function delay(ms = MOCK_DELAY_MS) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// --- 업종별 2번 질문(제품/가게) 선택지 ---------------------------------
const CATEGORY_PRODUCT_OPTIONS = {
  food: ['떡볶이집', '베이커리·디저트', '카페', '도시락 전문점'],
  beauty: ['스킨케어 브랜드', '헤어살롱', '네일샵', '향수 브랜드'],
  goods: ['문구·디자인 소품', '반려동물 굿즈', '캠핑용품', '인테리어 소품'],
  default: ['우리 브랜드 제품', '오프라인 매장', '온라인 스토어', '신제품 라인업'],
};

function categoryKey(message = '') {
  if (message.includes('푸드')) return 'food';
  if (message.includes('뷰티')) return 'beauty';
  if (message.includes('굿즈')) return 'goods';
  return 'default';
}

const TONE_OPTIONS = ['따뜻하고 아늑한', '깔끔하고 모던한', '화려하고 트렌디한', '자연스럽고 담백한'];
const HIGHLIGHT_OPTIONS = ['신선한 재료', '합리적인 가격', '특별한 이벤트', '브랜드 스토리'];
const EXTRA_OPTIONS = ['특별히 없어요', '이벤트를 강조해주세요', '가격을 강조해주세요', '심플하게 만들어주세요'];

/** 첫 질문(1단계, 업종)은 고정 선택지라 API 호출 없이 프론트에서 바로 사용한다. */
export const INITIAL_QUESTION = {
  step: 1,
  total_steps: TOTAL_STEPS,
  question: '어떤 업종이신가요?',
  options: ['푸드', '뷰티', '굿즈'],
  multiSelect: false,
  freeform: false,
};

function buildQuestion(step, spec) {
  switch (step) {
    case 2:
      return {
        question: '어떤 제품/가게인가요?',
        options: CATEGORY_PRODUCT_OPTIONS[categoryKey(spec.category)],
        multiSelect: false,
        freeform: false,
      };
    case 3:
      return {
        question: '원하시는 포스터 느낌은 어떤가요?',
        options: TONE_OPTIONS,
        multiSelect: false,
        freeform: false,
      };
    case 4:
      return {
        question: '강조하고 싶은 점은 무엇인가요? (복수 선택 가능)',
        options: HIGHLIGHT_OPTIONS,
        multiSelect: true,
        freeform: false,
      };
    case 5:
      return {
        question: '추가로 요청하실 사항이 있나요?',
        options: EXTRA_OPTIONS,
        multiSelect: false,
        freeform: true,
      };
    default:
      return { question: '', options: [], multiSelect: false, freeform: false };
  }
}

function buildConfirmMessage(step, spec) {
  switch (step) {
    case 1:
      return `${spec.category} 업종이시군요!`;
    case 2:
      return `${spec.product}, 멋지네요!`;
    case 3:
      return '좋은 느낌이에요!';
    case 4:
      return '강조 포인트 확인했어요!';
    case 5:
      return '모든 답변을 확인했어요. 문구를 만들어볼게요!';
    default:
      return '';
  }
}

/**
 * POST /suggest/options 목 함수.
 * message: 사용자가 고른 선택지 텍스트 또는 기타 직접입력 값
 * step: 직전 응답의 next_step 값 (첫 요청은 생략 → 1로 처리)
 * spec: 누적 상태
 */
export async function suggestOptions({ message, step = 1, spec = {} } = {}) {
  await delay();

  const nextSpec = { ...spec };
  switch (step) {
    case 1:
      nextSpec.category = message;
      break;
    case 2:
      nextSpec.product = message;
      break;
    case 3:
      nextSpec.tone = message;
      break;
    case 4:
      nextSpec.highlights = message;
      break;
    case 5:
      nextSpec.extra = message;
      break;
    default:
      break;
  }

  if (step >= TOTAL_STEPS) {
    return {
      step,
      next_step: null,
      total_steps: TOTAL_STEPS,
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
  const { question, options, multiSelect, freeform } = buildQuestion(nextStep, nextSpec);

  return {
    step,
    next_step: nextStep,
    total_steps: TOTAL_STEPS,
    question,
    options,
    multiSelect,
    freeform,
    spec: nextSpec,
    confirm_message: buildConfirmMessage(step, nextSpec),
    done: false,
  };
}

// --- 규제 검사 (데모용 간이 룰) -----------------------------------------
const BLOCK_PATTERNS = [/치료/, /완치/, /부작용\s*없/, /질병\s*예방/];
const WARN_PATTERNS = [/1위/, /최고\s*(?!의\s*재료)/, /100\s*%\s*(효과|만족)/, /무조건/];

function scanText(text = '') {
  if (BLOCK_PATTERNS.some((re) => re.test(text))) return 'block';
  if (WARN_PATTERNS.some((re) => re.test(text))) return 'warn';
  return 'pass';
}

function noteForStatus(status) {
  if (status === 'block') return '질병 치료·예방 효과를 암시하는 표현은 관련 법령상 사용할 수 없어요.';
  if (status === 'warn') return '객관적 근거 없는 최상급·단정 표현은 주의가 필요해요.';
  return null;
}

function truncate(text = '', max) {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function buildCopy(spec) {
  const product = spec.product || '우리 브랜드';
  const firstHighlight = (spec.highlights || '특별한 매력').split(',')[0].trim();
  const tone = spec.tone || '자연스러운';

  return {
    headline: truncate(`${product}, ${firstHighlight}`, 20),
    sub: truncate(`${tone} 느낌으로 ${firstHighlight}을 담았어요`, 30),
  };
}

function buildSafeCopy(spec) {
  const product = spec.product || '우리 브랜드';
  return {
    headline: truncate(`${product}만의 특별함`, 20),
    sub: truncate('지금 만나보세요', 30),
  };
}

/** POST /generate/copy 목 함수. 5단계 완료 후 자동으로 이어서 호출한다. */
export async function generateCopy(spec = {}) {
  await delay(600);

  const combinedInput = [spec.product, spec.tone, spec.highlights, spec.extra].filter(Boolean).join(' ');
  const status = scanText(combinedInput);
  const { headline, sub } = buildCopy(spec);

  if (status === 'pass') {
    return { headline, sub, status, note: null, alternative: null };
  }

  return {
    headline,
    sub,
    status,
    note: noteForStatus(status),
    alternative: buildSafeCopy(spec),
  };
}

/** POST /validate/copy 목 함수. 사용자가 문구를 직접 수정했을 때 재검증한다. */
export async function validateCopy({ headline = '', sub = '' } = {}) {
  await delay(300);
  const status = scanText(`${headline} ${sub}`);
  return { status, note: noteForStatus(status) };
}
