import './ErrorNotice.css';

/**
 * API 실패 시 노출하는 공용 에러 UI — 항상 사용자 친화적 메시지 + "다시 시도" 버튼.
 * (docs/UIUX_스펙정리.md 6장 "이미지 생성 실패/타임아웃 → 재시도 버튼, 에러 원인은
 * 사용자 친화적 문구로" 대응) 네트워크 문제든 서버 문제든 원인을 구분해서 보여주지
 * 않고 항상 같은 톤의 메시지로 통일한다 — message는 호출부에서
 * toFriendlyMessage()로 이미 가공된 문구를 넘겨받는다.
 *
 * compact: true면 챗봇 말풍선처럼 좁은 영역에 들어가는 축약형으로 표시한다.
 */
function ErrorNotice({ message, onRetry, retrying = false, compact = false }) {
  return (
    <div className={`error-notice${compact ? ' error-notice--compact' : ''}`} role="alert">
      <span className="error-notice__icon" aria-hidden="true">
        ⚠️
      </span>
      <p className="error-notice__message">{message}</p>
      <button type="button" className="error-notice__retry" onClick={onRetry} disabled={retrying}>
        {retrying ? '다시 시도하는 중…' : '다시 시도'}
      </button>
    </div>
  );
}

export default ErrorNotice;
