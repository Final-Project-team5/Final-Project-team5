/**
 * mock API 공용 유틸 — 실패 시뮬레이션 + 사용자 친화적 에러 메시지.
 * (docs/UIUX_스펙정리.md 6장 "이미지 생성 실패/타임아웃 → 재시도 버튼,
 *  사용자 친화적 문구" 대응. 실서버 연동 시 이 파일은 그대로 두고,
 *  각 mock 함수 안의 maybeFail() 호출만 지우면 된다.)
 *
 * --- 실패를 인위적으로 재현하는 방법 (개발/테스트 전용, URL 쿼리 파라미터) ---
 *
 *   ?mockFail=drafts,refine
 *     지정한 엔드포인트가 "딱 한 번"만 실패하고, 같은 요청을 재시도하면 성공한다.
 *     재시도 버튼이 실제로 다시 요청을 보내고 정상적으로 복구되는지 확인할 때 쓴다.
 *
 *   ?mockFailRate=0.3
 *     모든 mock 호출이 매번 30% 확률로 실패한다. 에러 UI를 반복적으로 띄워보고
 *     싶을 때 쓴다 (0~1 사이 값).
 *
 * 엔드포인트 키:
 *   options        → POST /suggest/options (화면 A, product 느낌/강조점/추가요청)
 *   vision         → POST /vision/product  (화면 A, product 사진 인식)
 *   productConfirm → POST /vision/product/confirm (Vision 맞아요/수정할게요 확정)
 *   background     → POST /vision/background (선택 배경 참고 이미지 분석)
 *   copy           → POST /generate/copy   (화면 A→B 전환)
 *   validate       → POST /validate/copy   (화면 B)
 *   drafts         → POST /generate/drafts (화면 C, 로딩 A)
 *   refine         → POST /generate/refine (화면 D, 로딩 B)
 *
 * 예: http://localhost:5173/?mockFail=drafts  (초안 생성이 한 번 실패하는 것을 재현)
 */

const FRIENDLY_MESSAGES = {
  options: '다음 질문을 불러오는 중 문제가 생겼어요. 다시 시도해주세요.',
  vision: '사진을 분석하는 중 문제가 생겼어요. 다시 시도해주세요.',
  productConfirm: '제품명을 확정하는 중 문제가 생겼어요. 다시 시도해주세요.',
  background: '배경 참고 이미지를 분석하는 중 문제가 생겼어요.',
  copy: '문구를 만드는 중 문제가 생겼어요. 다시 시도해주세요.',
  validate: '문구를 확인하는 중 문제가 생겼어요. 다시 시도해주세요.',
  drafts: '시안 이미지를 만드는 중 문제가 생겼어요. 다시 시도해주세요.',
  refine: '이미지를 고품질로 다듬는 중 문제가 생겼어요. 다시 시도해주세요.',
};
const DEFAULT_MESSAGE = '요청을 처리하는 중 문제가 생겼어요. 다시 시도해주세요.';

/**
 * mock 함수가 던지는 에러. 실제 서버 에러(네트워크 오류, 5xx 등)를 흉내내되,
 * 화면에는 항상 사용자 친화적 메시지만 노출한다 — 원인(네트워크/서버 등)은
 * 구분해서 보여주지 않는다 (8/11 스펙 3장 요구사항).
 */
export class MockApiError extends Error {
  constructor(key) {
    super(FRIENDLY_MESSAGES[key] || DEFAULT_MESSAGE);
    this.name = 'MockApiError';
    this.key = key;
    this.friendlyMessage = this.message;
  }
}

/**
 * 어떤 에러든(mock이든 실제 fetch 실패든) 사용자에게 보여줄 친절한 문구로 바꾼다.
 * 실서버 연동 후에도 catch(err) => toFriendlyMessage(err, 'drafts') 형태로 그대로 쓸 수 있다.
 */
export function toFriendlyMessage(error, key) {
  if (error instanceof MockApiError) return error.friendlyMessage;
  return FRIENDLY_MESSAGES[key] || DEFAULT_MESSAGE;
}

function parseListParam(name) {
  const raw = new URLSearchParams(window.location.search).get(name);
  return raw
    ? raw
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
    : [];
}

function parseRateParam(name) {
  const raw = parseFloat(new URLSearchParams(window.location.search).get(name));
  return Number.isFinite(raw) ? Math.min(1, Math.max(0, raw)) : 0;
}

// 한 번 실패하면 목록에서 지운다 — 그래야 "재시도하면 성공"하는 시나리오를
// 재현할 수 있다(같은 파라미터로 새로고침하면 다시 한 번 실패를 볼 수 있음).
const failOnceKeys = new Set(parseListParam('mockFail'));
const failRate = parseRateParam('mockFailRate');

// React StrictMode(개발 모드)는 useEffect를 마운트마다 두 번 실행한다 — 예를 들어
// 화면 C(DraftSelect)의 초안 요청 effect가 즉시 cleanup→재실행되면서 같은 API를
// 아주 짧은 간격으로 두 번 호출한다. 그 중 첫 번째 호출 결과는 컴포넌트가
// cancelled 플래그로 버리는데, 만약 그 버려지는 호출이 실패를 "소모"해버리면
// 실제로 화면에 반영되는 두 번째 호출은 항상 성공해버려서 에러 UI를 영영 볼 수
// 없다. 그래서 짧은 유예 시간(DEDUPE_MS) 안에 같은 key로 들어오는 모든 호출은
// 전부 실패시키고, 그 유예 시간이 지난 뒤에야 실제로 소모(consume)한다 — 사람이나
// 테스트 스크립트가 누르는 "다시 시도" 클릭은 항상 이 유예 시간보다 한참 뒤에
// 일어나므로 정상적으로 성공한다.
const DEDUPE_MS = 250;
const pendingConsume = new Map();

/**
 * 로딩 A/B(LoadingChecklist) 전용 — 실제 응답이 최소 표시 시간보다 빨리 와도
 * 체크리스트 3단계가 순서대로 다 보일 시간을 확보할 때까지 화면 전환을 미룬다.
 * 응답이 최소 시간보다 늦게 오면 원래대로 응답을 그대로 기다린다(단축 없음).
 * 성공/실패 어느 쪽이든 똑같이 최소 시간을 채운 뒤에야 결과가 반영되므로,
 * 체크리스트가 반짝 떴다가 바로 에러로 바뀌는 것도 함께 막아준다.
 */
export function withMinDuration(promise, ms) {
  const settled = promise.then(
    (value) => ({ ok: true, value }),
    (error) => ({ ok: false, error }),
  );
  const wait = new Promise((resolve) => setTimeout(resolve, ms));
  return Promise.all([settled, wait]).then(([result]) => {
    if (result.ok) return result.value;
    throw result.error;
  });
}

/** mock 함수 안에서 응답을 만들기 전에 호출 — 실패 조건에 해당하면 던진다. */
export function maybeFail(key) {
  if (failOnceKeys.has(key)) {
    if (!pendingConsume.has(key)) {
      const timer = setTimeout(() => {
        failOnceKeys.delete(key);
        pendingConsume.delete(key);
      }, DEDUPE_MS);
      pendingConsume.set(key, timer);
    }
    throw new MockApiError(key);
  }
  if (failRate > 0 && Math.random() < failRate) {
    throw new MockApiError(key);
  }
}
