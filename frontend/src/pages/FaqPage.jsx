import { useState } from 'react';
import { FAQ_ITEMS } from '../constants/faqItems';
import regulationBadgeImg from '../assets/faq/regulation-badge.png';
import draftGridImg from '../assets/faq/draft-grid.png';
import positionDragImg from '../assets/faq/position-drag.png';
import sizeOptionsImg from '../assets/faq/size-options.png';
import './FaqPage.css';

// faqItems.js의 image 키 → 실제 이미지 모듈. Vite가 번들에 포함할 수 있도록
// import는 정적으로 미리 해두고, 문자열 키로만 골라 쓴다.
const FAQ_IMAGES = {
  'regulation-badge': regulationBadgeImg,
  'draft-grid': draftGridImg,
  'position-drag': positionDragImg,
  'size-options': sizeOptionsImg,
};

/**
 * /faq — 자주 묻는 질문 전체 목록.
 * 사이드바는 그대로 유지되고 메인 영역만 이 화면으로 바뀐다(App.jsx 참고).
 * 사이드바 미리보기(faqItems.js의 앞 FAQ_PREVIEW_COUNT개)와 같은 데이터를 쓴다.
 *
 * 일부 답변은 관련 화면을 실제로 캡처해 크롭한 스크린샷을 함께 보여준다
 * (frontend/src/assets/faq/ — 해당 UI 요소만 나오게 잘라둔 이미지, 전체 화면 아님).
 */
function FaqPage() {
  const [openIndex, setOpenIndex] = useState(0);

  const toggle = (idx) => {
    setOpenIndex((prev) => (prev === idx ? -1 : idx));
  };

  return (
    <div className="faq-page">
      <h1 className="faq-page__title">자주 묻는 질문</h1>
      <p className="faq-page__description">궁금한 점을 눌러서 확인해보세요.</p>

      <ul className="faq-page__list">
        {FAQ_ITEMS.map((item, idx) => {
          const isOpen = openIndex === idx;
          const image = item.image ? FAQ_IMAGES[item.image] : null;
          return (
            <li key={item.q} className="faq-page__item">
              <button
                type="button"
                className="faq-page__question"
                aria-expanded={isOpen}
                onClick={() => toggle(idx)}
              >
                <span>{item.q}</span>
                <svg
                  className={`faq-page__chevron${isOpen ? ' faq-page__chevron--open' : ''}`}
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  aria-hidden="true"
                >
                  <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
              {isOpen && (
                <div className="faq-page__answer-wrap">
                  <p className="faq-page__answer">{item.a}</p>
                  {image && (
                    <img className="faq-page__answer-image" src={image} alt={item.imageAlt || ''} />
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default FaqPage;
