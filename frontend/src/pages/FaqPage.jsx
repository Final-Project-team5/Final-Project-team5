import { useState } from 'react';
import { FAQ_ITEMS } from '../constants/faqItems';
import './FaqPage.css';

/**
 * /faq — 자주 묻는 질문 전체 목록.
 * 사이드바는 그대로 유지되고 메인 영역만 이 화면으로 바뀐다(App.jsx 참고).
 * 사이드바 미리보기(faqItems.js의 앞 FAQ_PREVIEW_COUNT개)와 같은 데이터를 쓴다.
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
              {isOpen && <p className="faq-page__answer">{item.a}</p>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default FaqPage;
