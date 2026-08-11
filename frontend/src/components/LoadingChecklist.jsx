import { useEffect, useState } from 'react';
import Mascot from './Mascot';
import './LoadingChecklist.css';

/**
 * 로딩 A(초안 생성 중)/로딩 B(고품질화 중) 공용 체크리스트 로딩 UI.
 * (docs/UIUX_스펙정리.md 3장 "중요 — 로딩이 총 2번 발생, 두 단계를 명확히
 * 구분해서 보여줘야 함" 대응)
 *
 * variant로 로딩 A/B를 시각적으로 구분한다(강조색이 달라짐). steps는 실제
 * 서버 진행률이 아니라 "지루하지 않게" 하기 위한 연출로, 일정 간격마다
 * 다음 항목으로 순서대로 넘어간다(마지막 항목에서 멈춰 대기).
 */
function LoadingChecklist({ title, caption, steps, stepDurationMs = 1300, variant = 'draft' }) {
  const [activeIndex, setActiveIndex] = useState(0);

  useEffect(() => {
    setActiveIndex(0);
    if (steps.length <= 1) return undefined;
    const timer = setInterval(() => {
      setActiveIndex((prev) => (prev + 1 < steps.length ? prev + 1 : prev));
    }, stepDurationMs);
    return () => clearInterval(timer);
    // steps 배열은 매 렌더 새 배열일 수 있어 length만 의존값으로 삼는다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [steps.length, stepDurationMs]);

  return (
    <div className={`loading-checklist loading-checklist--${variant}`} role="status" aria-live="polite">
      <div className="loading-checklist__spinner" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
      <h2 className="loading-checklist__title">{title}</h2>
      {caption && <p className="loading-checklist__caption">{caption}</p>}
      <div className="loading-checklist__body">
        <Mascot expression="working" size={84} className="loading-checklist__mascot" />
        <ul className="loading-checklist__steps">
          {steps.map((step, idx) => {
            const state = idx < activeIndex ? 'done' : idx === activeIndex ? 'active' : 'pending';
            return (
              <li key={step} className={`loading-checklist__step loading-checklist__step--${state}`}>
                <span className="loading-checklist__step-icon">{state === 'done' ? '✓' : idx + 1}</span>
                <span>{step}</span>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}

export default LoadingChecklist;
