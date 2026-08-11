import Mascot from '../components/Mascot';
import TickerPreview from '../components/TickerPreview';
import './Home.css';

/**
 * 화면 -1 — 홈
 * (docs/UIUX_스펙정리.md 4장 참고)
 *
 * 마스코트는 예시 카드를 "방금 그린" 것처럼 카드 왼쪽 가장자리에 걸치듯
 * 배치한다 — 실제 화면 흐름과 무관한 장식이라 스크린리더에는 노출하지 않는다.
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

      <div className="home__scene">
        <div className="home__mascot-wrap">
          <Mascot expression="idle" size={168} className="home__mascot" />
          <span className="home__sparkle home__sparkle--a" aria-hidden="true">✦</span>
          <span className="home__sparkle home__sparkle--b" aria-hidden="true">✦</span>
          <span className="home__sparkle home__sparkle--c" aria-hidden="true">✦</span>
        </div>
        <TickerPreview />
      </div>
    </div>
  );
}

export default Home;
