import TickerPreview from '../components/TickerPreview';
import './Home.css';

/**
 * 화면 -1 — 홈
 * (docs/UIUX_스펙정리.md 4장 참고)
 */
function Home({ onNewFlow }) {
  return (
    <div className="home">
      <div className="home__intro">
        <h1 className="home__headline">
          오늘은 어떤
          <br />
          광고를 만들어볼까요?
        </h1>
        <p className="home__description">
          챗봇과 대화하듯 답하면 문구와 이미지를 자동으로 만들어드려요.
        </p>
        <button type="button" className="home__cta" onClick={onNewFlow}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M12 5v14M5 12h14" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" />
          </svg>
          새로 만들기
        </button>
      </div>

      <TickerPreview />
    </div>
  );
}

export default Home;
