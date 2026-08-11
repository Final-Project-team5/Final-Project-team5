import { useState } from 'react';
import { validateCopy } from '../api/copyApi';
import './CopyResult.css';

const BADGE_INFO = {
  pass: { label: '규제 검증 통과', className: 'copy-result__badge--pass' },
  warn: { label: '주의 필요', className: 'copy-result__badge--warn' },
  block: { label: '규제 위반', className: 'copy-result__badge--block' },
};

const SEVERITY_LABEL = { block: '규제 위반', warn: '주의' };

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function toCurrent(copy) {
  return {
    headline: copy.headline,
    sub: copy.sub,
    status: copy.status,
    flags: copy.regulation_flags || [],
    safe: copy.safe,
  };
}

/**
 * 화면 B — 문구 생성 결과 화면
 * /generate/copy(mock)가 반환한 문구 3개(copies) 중 하나를 사용자가 고르고,
 * 고른 문구를 직접 수정하면 /validate/copy(mock)로 재검증한다.
 * (docs/UIUX_스펙정리.md 4장·5장 참고, 8/8 리뷰 반영 — 문구 3개 선택 구조)
 *
 * block(safe: false)인 카드는 선택할 수 없고, warn·통과 카드만 고를 수 있다.
 * 아래 "선택한 문구" 영역은 그렇게 고른 카드에 대해서만 동작한다.
 */
function CopyResult({ result, spec, onConfirm, onRestart }) {
  const copies = result.copies || [];
  const initialCopy = copies.find((c) => c.safe) || copies[0] || null;

  const [selectedId, setSelectedId] = useState(initialCopy?.id ?? null);
  const [current, setCurrent] = useState(() => (initialCopy ? toCurrent(initialCopy) : null));
  const [draftHeadline, setDraftHeadline] = useState(initialCopy?.headline ?? '');
  const [draftSub, setDraftSub] = useState(initialCopy?.sub ?? '');
  const [validating, setValidating] = useState(false);

  // block 여부는 status를 다시 훑지 않고 safe 필드로 바로 판단한다 — 실제 API가
  // safe를 내려주면(copy_model/regulation.py ValidateResponse.safe와 동일 규칙)
  // 이 부분은 손댈 필요 없이 그대로 붙는다.
  const canProceed = Boolean(current?.safe);
  const badge = current ? BADGE_INFO[current.status] || BADGE_INFO.pass : null;

  const selectCopy = (copy) => {
    if (!copy.safe) return; // block인 문구는 선택 불가
    setSelectedId(copy.id);
    setCurrent(toCurrent(copy));
    setDraftHeadline(copy.headline);
    setDraftSub(copy.sub);
  };

  const applySuggestion = (flag) => {
    const re = new RegExp(escapeRegExp(flag.pattern), 'g');
    setDraftHeadline((prev) => prev.replace(re, flag.suggestion));
    setDraftSub((prev) => prev.replace(re, flag.suggestion));
  };

  const handleRevalidate = async () => {
    setValidating(true);
    const res = await validateCopy({ headline: draftHeadline, sub: draftSub }, spec);
    setValidating(false);
    setCurrent({
      headline: draftHeadline,
      sub: draftSub,
      status: res.status,
      flags: res.flags || [],
      safe: res.safe,
    });
  };

  return (
    <div className="copy-result">
      <h1 className="copy-result__title">마음에 드는 문구를 골라주세요</h1>
      <p className="copy-result__description">
        3가지 문구를 준비했어요. 규제 검증까지 마쳤고, 고른 문구는 직접 수정할 수도 있어요.
      </p>

      <div className="copy-result__candidates">
        {copies.map((copy) => {
          const copyBadge = BADGE_INFO[copy.status] || BADGE_INFO.pass;
          const disabled = !copy.safe;
          const active = copy.id === selectedId;
          return (
            <button
              key={copy.id}
              type="button"
              disabled={disabled}
              className={
                'copy-result__candidate' +
                (active ? ' copy-result__candidate--active' : '') +
                (disabled ? ' copy-result__candidate--disabled' : '')
              }
              onClick={() => selectCopy(copy)}
            >
              <span className={`copy-result__badge ${copyBadge.className}`}>{copyBadge.label}</span>
              <div className="copy-result__candidate-headline">{copy.headline}</div>
              <div className="copy-result__candidate-sub">{copy.sub}</div>
              {disabled && (
                <p className="copy-result__candidate-blocked-note">규제 위반이라 이 문구는 고를 수 없어요.</p>
              )}
            </button>
          );
        })}
      </div>

      {current && (
        <>
          <div className="copy-result__card">
            <div className="copy-result__card-label">선택한 문구</div>
            <span className={`copy-result__badge ${badge.className}`}>{badge.label}</span>
            <div className="copy-result__headline">{current.headline}</div>
            <div className="copy-result__sub">{current.sub}</div>

            {current.flags.length > 0 && (
              <div className="copy-result__flags">
                {current.flags.map((flag, idx) => (
                  <div
                    key={`${flag.pattern}-${idx}`}
                    className={`copy-result__flag copy-result__flag--${flag.severity}`}
                  >
                    <div className="copy-result__flag-head">
                      <span className="copy-result__flag-severity">{SEVERITY_LABEL[flag.severity]}</span>
                      <span className="copy-result__flag-pattern">“{flag.pattern}”</span>
                    </div>
                    <p className="copy-result__flag-note">{flag.note}</p>
                    <button type="button" className="copy-result__flag-suggestion" onClick={() => applySuggestion(flag)}>
                      이 표현으로 바꿀게요: <strong>{flag.suggestion}</strong>
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="copy-result__edit">
            <div className="copy-result__edit-title">문구 직접 수정하기</div>
            <label className="copy-result__field">
              <span>헤드라인</span>
              <input value={draftHeadline} onChange={(e) => setDraftHeadline(e.target.value)} maxLength={40} />
            </label>
            <label className="copy-result__field">
              <span>서브 카피</span>
              <input value={draftSub} onChange={(e) => setDraftSub(e.target.value)} maxLength={60} />
            </label>
            <button type="button" className="copy-result__validate-btn" disabled={validating} onClick={handleRevalidate}>
              {validating ? '확인하는 중…' : '수정한 문구 다시 확인하기'}
            </button>
          </div>
        </>
      )}

      <div className="copy-result__actions">
        <button type="button" className="copy-result__secondary" onClick={onRestart}>
          처음부터 다시 만들기
        </button>
        <button
          type="button"
          className="copy-result__primary"
          disabled={!canProceed}
          onClick={() => onConfirm({ headline: current.headline, sub: current.sub, status: current.status })}
        >
          이 문구로 포스터 만들기
        </button>
      </div>
    </div>
  );
}

export default CopyResult;
