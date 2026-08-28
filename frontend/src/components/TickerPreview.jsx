import { useEffect, useState } from 'react';
import { TICKER_ITEMS } from '../constants/tickerItems';
import './TickerPreview.css';

const CARD_COUNT = TICKER_ITEMS.length;
const ROTATE_INTERVAL_MS = 3200;
const CARD_OFFSET_PX = 350;

/**
 * 홈 화면 우측의 예시 결과 카드 — 세로 방향으로 자동 스크롤(티커)되며
 * 카테고리(푸드/뷰티/학원)별 실제 예시 이미지가 순환 노출된다.
 * 이미지 자체에 헤드라인/서브 문구가 이미 포함돼 있어(완성 포스터 예시),
 * 카드에서 텍스트를 다시 그리지 않고 규제 통과/caption 배지만 그 위에 얹는다.
 */
function TickerPreview() {
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setActiveIndex((prev) => (prev + 1) % CARD_COUNT);
    }, ROTATE_INTERVAL_MS);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="ticker-preview">
      <div className="ticker-preview__stage">
        {TICKER_ITEMS.map((item, idx) => {
          // idx 기준 activeIndex와의 상대 위치를 -1(위로 퇴장) / 0(활성) / 1(대기)로 계산
          const rel0 = ((idx - activeIndex) % CARD_COUNT + CARD_COUNT) % CARD_COUNT;
          const rel = rel0 === CARD_COUNT - 1 ? -1 : rel0;
          const isActive = rel === 0;

          return (
            <div
              key={item.caption}
              className="ticker-preview__card"
              style={{
                transform: `translate(-50%, -50%) translateY(${rel * CARD_OFFSET_PX}px) scale(${isActive ? 1 : 0.82})`,
                opacity: isActive ? 1 : 0.4,
                zIndex: isActive ? 2 : 1,
              }}
            >
              <img className="ticker-preview__image" src={item.image} alt={item.text} />
              <div className="ticker-preview__badge-pass">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path
                    d="M5 13l4 4L19 7"
                    stroke="currentColor"
                    strokeWidth="3.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                규제 통과
              </div>
              <div className="ticker-preview__badge-caption">{item.caption}</div>
            </div>
          );
        })}
      </div>
      <div className="ticker-preview__fade" />
    </div>
  );
}

export default TickerPreview;
