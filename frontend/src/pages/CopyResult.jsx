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

/**
 * 화면 B — 문구 생성 결과 화면
 * /generate/copy(mock) 결과를 보여주고, 사용자가 직접 수정하면
 * /validate/copy(mock)로 재검증한다. (docs/UIUX_스펙정리.md 4장·5장 참고)
 *
 * block/warn 항목은 regulation_flags 배열로 각각 표시하고, 대체 표현을
 * 클릭하면 수정 입력창에 바로 반영된다.
 * 다음 화면(시안 선택)은 화면 C로 연결됨.
 */
function CopyResult({ result, spec, onConfirm, onRestart }) {
  const [current, setCurrent] = useState(() => ({
    headline: result.headline,
    sub: result.sub,
    status: result.status,
    flags: result.regulation_flags || [],
  }));
  const [draftHeadline, setDraftHeadline] = useState(result.headline);
  const [draftSub, setDraftSub] = useState(result.sub);
  const [validating, setValidating] = useState(false);

  const isPass = current.status === 'pass';
  const badge = BADGE_INFO[current.status] || BADGE_INFO.pass;

  const applySuggestion = (flag) => {
    const re = new RegExp(escapeRegExp(flag.pattern), 'g');
    setDraftHeadline((prev) => prev.replace(re, flag.suggestion));
    setDraftSub((prev) => prev.replace(re, flag.suggestion));
  };

  const handleRevalidate = async () => {
    setValidating(true);
    const res = await validateCopy({ headline: draftHeadline, sub: draftSub }, spec);
    setValidating(false);
    setCurrent({ headline: draftHeadline, sub: draftSub, status: res.status, flags: res.flags || [] });
  };

  return (
    <div className="copy-result">
      <h1 className="copy-result__title">문구가 준비됐어요</h1>
      <p className="copy-result__description">규제 검증까지 마친 문구예요. 마음에 들지 않으면 직접 수정할 수 있어요.</p>

      <div className="copy-result__card">
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
                  대체 표현 적용: <strong>{flag.suggestion}</strong>
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
