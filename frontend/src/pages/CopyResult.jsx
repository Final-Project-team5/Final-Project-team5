import { useState } from 'react';
import { validateCopy } from '../api/copyApi';
import './CopyResult.css';

const BADGE_INFO = {
  pass: { label: '규제 검증 통과', className: 'copy-result__badge--pass' },
  warn: { label: '주의 필요', className: 'copy-result__badge--warn' },
  block: { label: '규제 위반', className: 'copy-result__badge--block' },
};

/**
 * 화면 B — 문구 생성 결과 화면
 * /generate/copy(mock) 결과를 보여주고, 사용자가 직접 수정하면
 * /validate/copy(mock)로 재검증한다. (docs/UIUX_스펙정리.md 4장 참고)
 *
 * 다음 화면(시안 선택)은 미구현 — [이 문구로 시안 선택하러 가기] 버튼만 배치.
 */
function CopyResult({ result, onConfirm, onRestart }) {
  const [current, setCurrent] = useState(result);
  const [draftHeadline, setDraftHeadline] = useState(result.headline);
  const [draftSub, setDraftSub] = useState(result.sub);
  const [validating, setValidating] = useState(false);

  const isPass = current.status === 'pass';
  const badge = BADGE_INFO[current.status] || BADGE_INFO.pass;

  const applyAlternative = () => {
    if (!current.alternative) return;
    const next = {
      headline: current.alternative.headline,
      sub: current.alternative.sub,
      status: 'pass',
      note: null,
      alternative: null,
    };
    setCurrent(next);
    setDraftHeadline(next.headline);
    setDraftSub(next.sub);
  };

  const handleRevalidate = async () => {
    setValidating(true);
    const res = await validateCopy({ headline: draftHeadline, sub: draftSub });
    setValidating(false);
    setCurrent({
      headline: draftHeadline,
      sub: draftSub,
      status: res.status,
      note: res.note,
      alternative: current.alternative,
    });
  };

  return (
    <div className="copy-result">
      <h1 className="copy-result__title">문구가 준비됐어요</h1>
      <p className="copy-result__description">규제 검증까지 마친 문구예요. 마음에 들지 않으면 직접 수정할 수 있어요.</p>

      <div className="copy-result__card">
        <span className={`copy-result__badge ${badge.className}`}>{badge.label}</span>
        <div className="copy-result__headline">{current.headline}</div>
        <div className="copy-result__sub">{current.sub}</div>

        {!isPass && (
          <div className="copy-result__notice">
            <div className="copy-result__notice-reason">{current.note}</div>

            {current.alternative && (
              <div className="copy-result__alternative">
                <div className="copy-result__alternative-label">대체 문구 제안</div>
                <div className="copy-result__alternative-headline">{current.alternative.headline}</div>
                <div className="copy-result__alternative-sub">{current.alternative.sub}</div>
                <button type="button" className="copy-result__alt-btn" onClick={applyAlternative}>
                  이 문구로 계속하기
                </button>
              </div>
            )}
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
          {validating ? '검증 중…' : '수정한 문구 재검증하기'}
        </button>
      </div>

      <div className="copy-result__actions">
        <button type="button" className="copy-result__secondary" onClick={onRestart}>
          처음부터 다시 만들기
        </button>
        <button
          type="button"
          className="copy-result__primary"
          disabled={!isPass}
          onClick={() => onConfirm({ headline: current.headline, sub: current.sub })}
        >
          이 문구로 시안 선택하러 가기
        </button>
      </div>
    </div>
  );
}

export default CopyResult;
