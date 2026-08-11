/**
 * 문구 생성/규제 검증 API — mock 버전.
 * 실서버(도혁님 파트)가 준비되기 전까지 프론트 흐름 검증용으로 사용한다.
 * 요청/응답 형태는 docs/UIUX_스펙정리.md 5장(문구 모델) 기준을 따른다.
 *
 *   POST /suggest/options  { message, step, spec } → ChatFlow.jsx (화면 A)
 *   POST /generate/copy    { spec }                → { copies: [...] }(3개) → CopyResult.jsx (화면 B)
 *   POST /validate/copy    { headline, sub }        → CopyResult.jsx (화면 B, 선택한 문구 재검증)
 *
 * 실패 시뮬레이션(?mockFail=options,copy,validate / ?mockFailRate=0.3)은
 * mockUtils.js 참고 — 개발/테스트 중 재시도 버튼 동작을 확인할 때 쓴다.
 */

import { maybeFail } from './mockUtils';

const MOCK_DELAY_MS = 400;
export const TOTAL_STEPS = 6;

function delay(ms = MOCK_DELAY_MS) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// --- 용도 질문 (8/11 확정: 비율 매핑은 프론트가 아니라 서버가 결정) --------
// 프론트는 이 선택지로 질문만 보여주고, 매핑 결과(purpose/aspect_ratio)는
// 서버가 /suggest/options 응답 spec에 채워서 내려준다. 프론트는 그 값을
// 그대로 받아 쓸 뿐 계산하지 않는다 — 아래 PURPOSE_BY_USAGE는 mock이 "서버라면
// 이렇게 채워줬을 값"을 흉내내기 위한 내부 구현일 뿐, 프론트 쪽 매핑 로직이 아니다.
export const USAGE_OPTIONS = ['SNS 카드뉴스', '배너', '상세페이지'];
const PURPOSE_BY_USAGE = {
  'SNS 카드뉴스': { purpose: 'sns', aspect_ratio: '1:1' },
  배너: { purpose: 'banner', aspect_ratio: '3:1' },
  상세페이지: { purpose: 'detail', aspect_ratio: '3:4' },
};
function resolvePurpose(usage) {
  return PURPOSE_BY_USAGE[usage] || { purpose: 'sns', aspect_ratio: '1:1' };
}

// --- 업종별 3번 질문(제품/가게) 선택지 ---------------------------------
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
        question: '이 포스터는 어디에 사용하실 예정인가요?',
        options: USAGE_OPTIONS,
        multiSelect: false,
        freeform: false,
      };
    case 3:
      return {
        question: '어떤 제품/가게인가요?',
        options: CATEGORY_PRODUCT_OPTIONS[categoryKey(spec.category)],
        multiSelect: false,
        freeform: false,
      };
    case 4:
      return {
        question: '원하시는 포스터 느낌은 어떤가요?',
        options: TONE_OPTIONS,
        multiSelect: false,
        freeform: false,
      };
    case 5:
      return {
        question: '강조하고 싶은 점은 무엇인가요? (복수 선택 가능)',
        options: HIGHLIGHT_OPTIONS,
        multiSelect: true,
        freeform: false,
      };
    case 6:
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
      return `${spec.usage}에 맞는 비율로 준비할게요!`;
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
 * POST /suggest/options 목 함수.
 * message: 사용자가 고른 선택지 텍스트 또는 기타 직접입력 값
 * step: 직전 응답의 next_step 값 (첫 요청은 생략 → 1로 처리)
 * spec: 누적 상태
 */
export async function suggestOptions({ message, step = 1, spec = {} } = {}) {
  await delay();
  maybeFail('options');

  const nextSpec = { ...spec };
  switch (step) {
    case 1:
      nextSpec.category = message;
      break;
    case 2: {
      nextSpec.usage = message;
      // 서버 응답 흉내: spec에 purpose/aspect_ratio를 이미 채운 상태로 내려준다.
      const { purpose, aspect_ratio } = resolvePurpose(message);
      nextSpec.purpose = purpose;
      nextSpec.aspect_ratio = aspect_ratio;
      break;
    }
    case 3:
      nextSpec.product = message;
      break;
    case 4:
      nextSpec.tone = message;
      break;
    case 5:
      nextSpec.highlights = message;
      break;
    case 6:
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

function splitHighlights(spec) {
  return (spec.highlights || '특별한 매력')
    .split(',')
    .map((h) => h.trim())
    .filter(Boolean);
}

/**
 * 문구 3개(시안) 후보를 만든다 (8/8 진우님 리뷰 반영 — /generate/copy는 headline/sub
 * 조합을 3개 반환하는 구조). 서로 다른 템플릿을 써서 강조점 조합이 갈리게 해두면,
 * 문구마다 규제 검증 결과가 달라지는 상황(일부만 block/warn)도 자연스럽게 재현된다.
 */
function buildCopyCandidates(spec) {
  const product = spec.product || '우리 브랜드';
  const tone = spec.tone || '자연스러운';
  const highlights = splitHighlights(spec);
  const first = highlights[0] || '특별한 매력';
  const second = highlights[1] || first;

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
 * POST /generate/copy 목 함수. 6단계 완료 후 자동으로 이어서 호출한다.
 * 응답은 `copies` 배열(3개) — 각 항목이 headline/sub와 함께 자기 자신의
 * regulation_flags/safe/status를 따로 갖는다(문구마다 규제 상태가 다를 수 있음).
 */
export async function generateCopy(spec = {}) {
  await delay(600);
  maybeFail('copy');

  const candidates = buildCopyCandidates(spec);
  // 실제 화면에 노출/수정되는 headline+sub만 검사한다 — 그래야 화면 B에서
  // "이 표현으로 바꿀게요"를 눌렀을 때 flag.pattern이 입력창 안에서 실제로 매칭된다.
  // (Q3 "제품/가게"나 Q5 "강조점"을 기타로 직접 입력하면 headline에 그대로 반영되어
  // block/warn 데모를 재현할 수 있다 — 예: 제품에 "아토피 치료 크림" 입력)
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
export async function validateCopy({ headline = '', sub = '' } = {}, spec = {}) {
  await delay(300);
  maybeFail('validate');
  const { status, flags, safe } = scanRegulation(`${headline} ${sub}`, spec);
  return { status, flags, safe };
}
