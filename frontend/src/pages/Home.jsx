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
          애드지니에게 말해보세요.
          <br />
          문구와 이미지가 마법처럼 완성돼요.
        </p>
        <button type="button" className="home__cta" onClick={onNewFlow}>
          <svg width="19.2" height="19.2" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M12 5v14M5 12h14" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" />
          </svg>
          새로 만들기
        </button>
      </div>

      <div className="home__ticker">
        <TickerPreview />
      </div>
    </div>
  );
}

export default Home;
