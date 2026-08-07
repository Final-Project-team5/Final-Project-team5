import { useEffect, useState } from 'react';
import { buildPrompt, generateDrafts } from '../api/posterApi';
import './DraftSelect.css';

/**
 * 화면 C — 이미지 초안 선택
 * /generate/drafts(mock)로 받은 시안 3장을 그리드로 보여주고, 클릭한 시안을
 * 하단에 크게 확대해서 보여준다. (docs/UIUX_스펙정리.md 4장 참고)
 *
 * 로딩 디테일(스켈레톤)/재시도 버튼은 다음 단계 고도화 스코프 — 이번엔 뼈대만 구현.
 * 선택한 시안의 image(base64)는 App 상태로 들고 있다가 다음 화면에서
 * draft_image로 재사용한다 (서버 stateless 구조).
 */
function DraftSelect({ mode, productImage, spec, onConfirm, onBack }) {
  const [drafts, setDrafts] = useState(null);
  const [selectedId, setSelectedId] = useState(null);

  useEffect(() => {
    let cancelled = false;
    generateDrafts({
      mode,
      image: productImage,
      prompt: buildPrompt(spec),
      num_images: 3,
    }).then((res) => {
      if (cancelled) return;
      setDrafts(res.drafts);
      setSelectedId(res.drafts[0]?.id ?? null);
    });
    return () => {
      cancelled = true;
    };
    // 화면 진입(마운트) 시 한 번만 초안을 요청한다 — mode/productImage/spec은
    // 화면 A에서 이미 확정되어 이 화면 안에서는 바뀌지 않는다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectedDraft = drafts?.find((d) => d.id === selectedId) || null;

  return (
    <div className="draft-select">
      <h1 className="draft-select__title">마음에 드는 시안을 골라주세요</h1>
      <p className="draft-select__description">
        가벼운 모델로 빠르게 만든 초안이에요. 하나를 고르면 다음 단계에서 고품질로 다듬어드려요.
      </p>

      {!drafts && <p className="draft-select__loading">시안을 준비하고 있어요…</p>}

      {drafts && (
        <>
          <div className="draft-select__grid">
            {drafts.map((draft, idx) => (
              <button
                key={draft.id}
                type="button"
                className={
                  'draft-select__card' + (draft.id === selectedId ? ' draft-select__card--active' : '')
                }
                onClick={() => setSelectedId(draft.id)}
              >
                <img src={draft.image} alt={`시안 ${idx + 1}`} />
                {draft.id === selectedId && <span className="draft-select__check">✓</span>}
              </button>
            ))}
          </div>

          {selectedDraft && (
            <div className="draft-select__preview">
              <img src={selectedDraft.image} alt="선택한 시안 확대 보기" />
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
          이 시안으로 다음 화면으로
        </button>
      </div>
    </div>
  );
}

export default DraftSelect;
