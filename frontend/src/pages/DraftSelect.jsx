import { useEffect, useState } from 'react';
import { buildPrompt, generateDrafts, toImageSrc } from '../api/posterApi';
import './DraftSelect.css';

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
 * 로딩 디테일(스켈레톤)/재시도 버튼은 다음 단계 고도화 스코프 — 이번엔 뼈대만 구현.
 *
 * ⚠ draft.image는 prefix 없는 순수 base64(8/8 리뷰 반영) — 화면에 <img src>로 보여줄
 * 때는 toImageSrc()로 감싸고, 선택한 시안을 다음 화면(refine 호출)에 넘길 땐 원본
 * base64를 그대로 App 상태로 들고 있다가 draft_image/background로 재사용한다
 * (서버 stateless 구조).
 */
function DraftSelect({ mode, productImage, spec, onConfirm, onBack }) {
  const ratio = spec?.aspect_ratio || '1:1';
  const aiDisabled = ratio === '3:4';
  const [backgroundType, setBackgroundType] = useState(aiDisabled ? 'flat' : 'ai');
  const [drafts, setDrafts] = useState(null);
  const [selectedId, setSelectedId] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setDrafts(null);
    generateDrafts({
      mode,
      image: productImage,
      prompt: buildPrompt(spec),
      ratio,
      backgroundType,
      num_images: 3,
    }).then((res) => {
      if (cancelled) return;
      setDrafts(res.drafts);
      setSelectedId(res.drafts[0]?.id ?? null);
    });
    return () => {
      cancelled = true;
    };
    // mode/productImage/spec은 화면 A에서 이미 확정되어 이 화면 안에서는 바뀌지
    // 않는다 — backgroundType이 바뀔 때만 다시 요청하면 된다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backgroundType]);

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
          {BACKGROUND_TYPE_OPTIONS.map((opt) => {
            const disabled = opt.id === 'ai' && aiDisabled;
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
                onClick={() => setBackgroundType(opt.id)}
              >
                {opt.label}
                {disabled && <span className="draft-select__bg-type-soon">준비 중</span>}
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

      {!drafts && <p className="draft-select__loading">시안을 준비하고 있어요…</p>}

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
