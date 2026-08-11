import './Sidebar.css';

/**
 * 좌측 고정 사이드바 — 로고, 새로 만들기 버튼, "오늘의 상식" 순환 팁,
 * AI 생성물 사전 고지 문구.
 * (docs/UIUX_스펙정리.md 4장 "화면 -1 — 홈" 참고)
 */
function Sidebar({ regTip, regTipVisible, onGoHome, onNewFlow }) {
  return (
    <aside className="sidebar">
      <button type="button" className="sidebar__logo" onClick={onGoHome}>
        <img src="/favicon.svg" alt="" className="sidebar__logo-icon" width="24" height="24" />
        <span>애드지니</span>
      </button>

      <button type="button" className="sidebar__new-btn" onClick={onNewFlow}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M12 5v14M5 12h14" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" />
        </svg>
        새로 만들기
      </button>

      <div className="sidebar__tip-card">
        <div className="sidebar__tip-header">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
              d="M12 2a7 7 0 00-4 12.7V17a1 1 0 001 1h6a1 1 0 001-1v-2.3A7 7 0 0012 2z"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinejoin="round"
            />
            <path d="M10 21h4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
          <span>오늘의 상식</span>
        </div>
        <div className="sidebar__tip-text" style={{ opacity: regTipVisible ? 1 : 0 }}>
          {regTip}
        </div>
      </div>

      <div className="sidebar__spacer" />

      <div className="sidebar__notice">
        이 서비스는 생성형 AI로 문구와 이미지를 자동 생성합니다.
      </div>
    </aside>
  );
}

export default Sidebar;
