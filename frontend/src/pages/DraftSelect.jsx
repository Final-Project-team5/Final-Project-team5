import { useEffect, useState } from 'react';
import { generateDrafts, planDesignPrompt, toImageSrc } from '../api/posterApi';
import { toFriendlyMessage, withMinDuration } from '../api/mockUtils';
import ErrorNotice from '../components/ErrorNotice';
import LoadingChecklist from '../components/LoadingChecklist';
import './DraftSelect.css';

// 로딩 A — 화면 C 진입 시 /generate/drafts 호출 중 보여주는 체크리스트
// (docs/UIUX_스펙정리.md 3장). 실제 서버 진행률이 아니라 체감 대기시간을
// 줄이기 위한 연출용 순서다.
const DRAFT_LOADING_STEPS = ['키워드 분석 중', '배경 시안 그리는 중', '시안 3장 정리하는 중'];
// mock 응답이 이보다 빨리 와도 체크리스트 3단계가 순서대로 다 보일 때까지는
// 화면을 넘기지 않는다. 항목별로 균등하게 배분(3초 ÷ 3단계 = 1초씩).
const DRAFT_LOADING_MIN_MS = 3000;

// 배경 종류 선택지 — AI 배경(diffusion 모델)과 flat 배경(단색/그라데이션).
// 3:4(상세페이지)는 투명 제품 continuation 문제로 AI 배경이 아직 production
// 차단 상태라 '준비 중'으로 비활성화하고 flat만 고를 수 있게 한다. (8/10 확정)
const BACKGROUND_TYPE_OPTIONS = [
  { id: 'ai', label: 'AI 배경' },
  { id: 'flat', label: '단색·그라데이션 배경' },
];

/**
 * 화면 C — 이미지 초안 선택
 * /generate/drafts(mock)로 받은 시안 3장을 그리드로 보여주고, 클릭한 시안을
 * 하단에 크게 확대해서 보여준다. (docs/UIUX_스펙정리.md 4장 참고)
 *
 * 로딩 A(초안 생성 중)는 LoadingChecklist + 스켈레톤 카드로 보여주고, 실패하면
 * ErrorNotice로 친절한 메시지와 "다시 시도" 버튼을 노출한다(같은 요청 재전송).
 *
 * ⚠ draft.image는 prefix 없는 순수 base64(8/8 리뷰 반영) — 화면에 <img src>로 보여줄
 * 때는 toImageSrc()로 감싸고, 선택한 시안을 다음 화면(refine 호출)에 넘길 땐 원본
 * base64를 그대로 App 상태로 들고 있다가 draft_image/background로 재사용한다
 * (서버 stateless 구조).
 */
function DraftSelect({ mode, productImage, spec, onConfirm, onBack }) {
  const ratio = spec?.aspect_ratio || '1:1';
  const aiDisabled = ratio === '3:4';
  // service는 사진이 없어 flat(단색·그라데이션) 배경을 만들 제품 마스크 자체가
  // 없다 — AI 배경만 제공한다(docs/UIUX_스펙정리.md 5장 business_type×비율×배경
  // 표, 8/14 갱신). product는 기존대로 flat/AI 둘 다 노출.
  const isService = spec?.business_type === 'service';
  const backgroundTypeOptions = isService
    ? BACKGROUND_TYPE_OPTIONS.filter((opt) => opt.id === 'ai')
    : BACKGROUND_TYPE_OPTIONS;
  const [backgroundType, setBackgroundType] = useState(aiDisabled ? 'flat' : 'ai');
  const [drafts, setDrafts] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [loadError, setLoadError] = useState(null);
  // backgroundType이 바뀌지 않아도 "다시 시도"를 누르면 같은 요청을 다시 보내야
  // 하므로, 재시도 전용 카운터를 따로 둬서 effect를 다시 트리거한다.
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    // StrictMode(개발 모드)는 이 effect를 마운트마다 두 번(마운트→cleanup→재마운트)
    // 실행한다. cancelled 플래그는 "먼저 나간 요청의 결과를 화면에 반영하지 않는
    // 것"만 보장할 뿐 실제 fetch 자체는 막지 못해서, real API에서는 매번 진짜 서버
    // 요청이 2번 나가는 문제가 있었다(8/13 확인). AbortController로 cleanup 시점에
    // 실제 요청을 취소해서 진짜로 1번만 나가게 한다 — mock 쪽은 fetch를 안 쓰므로
    // signal을 받아도 조용히 무시한다(동작 영향 없음).
    const controller = new AbortController();
    setDrafts(null);
    setLoadError(null);
    withMinDuration(
      generateDrafts({
        mode,
        image: productImage,
        prompt: planDesignPrompt(spec),
        ratio,
        backgroundType,
        num_images: 3,
        signal: controller.signal,
      }),
      DRAFT_LOADING_MIN_MS,
    )
      .then((res) => {
        if (cancelled) return;
        setDrafts(res.drafts);
        setSelectedId(res.drafts[0]?.id ?? null);
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(toFriendlyMessage(err, 'drafts'));
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
    // mode/productImage/spec은 화면 A에서 이미 확정되어 이 화면 안에서는 바뀌지
    // 않는다 — backgroundType이 바뀌거나 재시도 버튼을 누를 때만 다시 요청한다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backgroundType, retryToken]);

  const handleRetryDrafts = () => setRetryToken((t) => t + 1);

  // /generate/drafts 응답을 기다리는 중인지 — LoadingChecklist를 보여주는 조건과 동일.
  // 로딩 중에 배경 스타일 칩을 다시 누르면(특히 real API에서는 진짜 GPU 요청이라
  // 비용이 든다) 중복 요청이 나갈 수 있어 그동안 칩을 비활성화해 막는다.
  const isLoadingDrafts = !drafts && !loadError;

  const selectedDraft = drafts?.find((d) => d.id === selectedId) || null;
  const aspectRatio = ratio.replace(':', ' / ');

  return (
    <div className="draft-select">
      <h1 className="draft-select__title">마음에 드는 시안을 골라주세요</h1>
      <p className="draft-select__description">
        가벼운 모델로 빠르게 만든 초안이에요. 하나를 고르면 다음 단계에서 고품질로 다듬어드려요.
      </p>

      <div className="draft-select__bg-type">
        <div className="draft-select__bg-type-label">배경 스타일</div>
        <div className="draft-select__bg-type-options">
          {backgroundTypeOptions.map((opt) => {
            const permanentlyDisabled = opt.id === 'ai' && aiDisabled;
            const disabled = permanentlyDisabled || isLoadingDrafts;
            return (
              <button
                key={opt.id}
                type="button"
                disabled={disabled}
                className={
                  'draft-select__bg-type-chip' +
                  (backgroundType === opt.id ? ' draft-select__bg-type-chip--active' : '') +
                  (disabled ? ' draft-select__bg-type-chip--disabled' : '')
                }
                onClick={() => {
                  // disabled 버튼은 브라우저가 클릭 자체를 무시하지만, 방어적으로 한 번 더 막는다.
                  if (isLoadingDrafts) return;
                  setBackgroundType(opt.id);
                }}
              >
                {opt.label}
                {permanentlyDisabled && <span className="draft-select__bg-type-soon">준비 중</span>}
              </button>
            );
          })}
        </div>
        {aiDisabled && (
          <p className="draft-select__bg-type-note">
            상세페이지(3:4) 비율은 AI 배경이 아직 준비 중이라, 단색·그라데이션 배경으로 만들어드려요.
          </p>
        )}
      </div>

      {!drafts && !loadError && (
        <LoadingChecklist
          variant="draft"
          title="배경 시안을 만들고 있어요"
          caption="가벼운 모델로 3장을 빠르게 그려드릴게요"
          steps={DRAFT_LOADING_STEPS}
          stepDurationMs={DRAFT_LOADING_MIN_MS / DRAFT_LOADING_STEPS.length}
        />
      )}

      {loadError && (
        <ErrorNotice message={loadError} onRetry={handleRetryDrafts} />
      )}

      {drafts && (
        <>
          <div className="draft-select__grid" style={{ '--draft-ratio': aspectRatio }}>
            {drafts.map((draft, idx) => (
              <button
                key={draft.id}
                type="button"
                className={
                  'draft-select__card' + (draft.id === selectedId ? ' draft-select__card--active' : '')
                }
                onClick={() => setSelectedId(draft.id)}
              >
                <img src={toImageSrc(draft.image)} alt={`시안 ${idx + 1}`} />
                {draft.id === selectedId && <span className="draft-select__check">✓</span>}
              </button>
            ))}
          </div>

          {selectedDraft && (
            <div className="draft-select__preview" style={{ '--draft-ratio': aspectRatio }}>
              <img src={toImageSrc(selectedDraft.image)} alt="선택한 시안 확대 보기" />
            </div>
          )}
        </>
      )}

      <div className="draft-select__actions">
        <button type="button" className="draft-select__secondary" onClick={onBack}>
          이전으로
        </button>
        <button
          type="button"
          className="draft-select__primary"
          disabled={!selectedDraft}
          onClick={() => onConfirm(selectedDraft)}
        >
          이 배경으로 꾸미러 가기
        </button>
      </div>
    </div>
  );
}

export default DraftSelect;
