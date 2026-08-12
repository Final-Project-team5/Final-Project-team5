import { FAQ_ITEMS, FAQ_PREVIEW_COUNT } from '../constants/faqItems';
import faceIcon from '../assets/mascot/face.png';
import './Sidebar.css';

// 사이드바 미니 진행 표시가 따라가는 전체 흐름 순서. App.jsx의 view 값과 key로 매칭한다.
// (/faq는 흐름 밖의 화면이라 이 목록에 없다 — App이 currentView로 직전 흐름 단계를
// 그대로 넘겨주므로 FAQ를 보는 중에도 진행 표시는 그대로 유지된다.)
// label은 dot 아래엔 안 쓰고(폭이 좁아서) 위젯 하단 "N. ○○" 한 줄 표시에만 쓴다.
const FLOW_STEPS = [
  { key: 'chat', label: '챗봇', current: '챗봇 답변 중' },
  { key: 'result', label: '문구', current: '문구 확인 중' },
  { key: 'drafts', label: '시안', current: '시안 선택 중' },
  { key: 'poster', label: '위치조정', current: '문구 위치 조정 중' },
  { key: 'final', label: '최종결과', current: '최종 결과 확인 중' },
];

/**
 * 좌측 고정 사이드바 — 로고, 새로 만들기 버튼, 진행 상황 미니 스텝(가로 dot),
 * FAQ 미리보기, "오늘의 상식" 순환 팁(AI 고지 문구 바로 위), AI 생성물 사전 고지 문구.
 * (docs/UIUX_스펙정리.md 4장 "화면 -1 — 홈" 참고)
 */
function Sidebar({ regTip, regTipVisible, currentView, onGoHome, onNewFlow, onGoFaq }) {
  const currentStepIndex = FLOW_STEPS.findIndex((step) => step.key === currentView);

  return (
    <aside className="sidebar">
      <button type="button" className="sidebar__logo" onClick={onGoHome}>
        <img src={faceIcon} alt="" className="sidebar__logo-icon" width="54" height="54" />
        <span>애드지니</span>
      </button>

      <button type="button" className="sidebar__new-btn" onClick={onNewFlow}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M12 5v14M5 12h14" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" />
        </svg>
        새로 만들기
      </button>

      <div className="sidebar__steps">
        <div className="sidebar__steps-label">진행 상황</div>
        <div className="sidebar__steps-track">
          {FLOW_STEPS.map((step, idx) => {
            const state =
              currentStepIndex < 0
                ? 'pending'
                : idx < currentStepIndex
                  ? 'done'
                  : idx === currentStepIndex
                    ? 'current'
                    : 'pending';
            return (
              <div className="sidebar__step-node" key={step.key}>
                {idx > 0 && (
                  <span
                    className={
                      'sidebar__step-connector' + (idx <= currentStepIndex ? ' sidebar__step-connector--done' : '')
                    }
                  />
                )}
                <span className={`sidebar__step-dot sidebar__step-dot--${state}`}>
                  {state === 'done' ? '✓' : null}
                </span>
              </div>
            );
          })}
        </div>
        <div className="sidebar__steps-current">
          {currentStepIndex >= 0 ? `${currentStepIndex + 1}. ${FLOW_STEPS[currentStepIndex].current}` : '아직 시작 전이에요'}
        </div>
      </div>

      <div className="sidebar__faq">
        <div className="sidebar__faq-label">자주 묻는 질문</div>
        <ul className="sidebar__faq-list">
          {FAQ_ITEMS.slice(0, FAQ_PREVIEW_COUNT).map((item) => (
            <li key={item.q} className="sidebar__faq-item">
              {item.q}
            </li>
          ))}
        </ul>
        <button type="button" className="sidebar__faq-more" onClick={onGoFaq}>
          자세히 보러가기 <span aria-hidden="true">›</span>
        </button>
      </div>

      <div className="sidebar__spacer" />

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

      <div className="sidebar__notice">
        이 서비스는 생성형 AI로 문구와 이미지를 자동 생성합니다.
      </div>
    </aside>
  );
}

export default Sidebar;
