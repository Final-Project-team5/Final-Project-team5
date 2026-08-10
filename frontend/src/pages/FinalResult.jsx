import { useState } from 'react';
import './FinalResult.css';

// 용도별 사이즈 토글 — 지우님 파이프라인에 비율별 크롭이 아직 없어(현재 1024×1024
// 정사각형만 생성) square만 available:true. 나중에 백엔드가 준비되면 이 배열의
// available만 true로 바꾸면 바로 열리는 구조로 잡아둠.
const SIZE_OPTIONS = [
  { id: 'square', label: '정사각형 1024×1024', available: true },
  { id: 'sns', label: 'SNS 카드뉴스', available: false },
  { id: 'banner', label: '배너', available: false },
  { id: 'detail', label: '상세페이지', available: false },
];

const BADGE_INFO = {
  pass: { label: '규제 검증 통과', className: 'final-result__badge--pass' },
  warn: { label: '주의 필요', className: 'final-result__badge--warn' },
};

function dataUriToBlob(dataUri) {
  const [header, base64 = ''] = dataUri.split(',');
  const mimeMatch = header.match(/data:(.*);base64/);
  const mime = mimeMatch ? mimeMatch[1] : 'image/png';
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}

function downloadDataUri(dataUri, filename) {
  const blob = dataUriToBlob(dataUri);
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/**
 * 화면 E — 최종 결과
 * 화면 D(/generate/refine mock)의 결과 이미지와 확정 문구를 보여주고 다운로드까지
 * 제공한다. (docs/UIUX_스펙정리.md 4장, docs/AI_생성물_고지_표준안.md 참고)
 *
 * 로딩 디테일/재시도/에러 UI는 다음 단계 고도화 스코프 — 이번엔 뼈대만 구현.
 */
function FinalResult({ image, headline, sub, status, onRestart }) {
  const [sizeId, setSizeId] = useState('square');
  const badge = BADGE_INFO[status] || BADGE_INFO.pass;

  const handleDownload = () => {
    downloadDataUri(image, `ad-poster-${Date.now()}.png`);
  };

  return (
    <div className="final-result">
      <h1 className="final-result__title">광고 포스터가 완성됐어요</h1>
      <p className="final-result__description">문구와 이미지가 모두 준비됐어요. 마음에 들면 다운로드해보세요.</p>

      <div className="final-result__card">
        <span className={`final-result__badge ${badge.className}`}>{badge.label}</span>

        <div className="final-result__image-wrap">
          <img className="final-result__image" src={image} alt="완성된 광고 포스터" />
        </div>

        <p className="final-result__ai-caption">이 콘텐츠는 생성형 AI로 제작되었습니다.</p>

        <div className="final-result__copy">
          <div className="final-result__headline">{headline}</div>
          <div className="final-result__sub">{sub}</div>
        </div>
      </div>

      <div className="final-result__size-section">
        <div className="final-result__size-label">용도별 사이즈</div>
        <div className="final-result__size-options">
          {SIZE_OPTIONS.map((opt) => (
            <button
              key={opt.id}
              type="button"
              disabled={!opt.available}
              className={
                'final-result__size-chip' +
                (sizeId === opt.id ? ' final-result__size-chip--active' : '') +
                (!opt.available ? ' final-result__size-chip--disabled' : '')
              }
              onClick={() => opt.available && setSizeId(opt.id)}
            >
              {opt.label}
              {!opt.available && <span className="final-result__size-soon">준비 중</span>}
            </button>
          ))}
        </div>
        <p className="final-result__size-note">
          현재는 정사각형(1024×1024) 결과만 제공돼요. 용도별 사이즈는 크롭 기능이 준비되면 열릴 예정이에요.
        </p>
      </div>

      <div className="final-result__actions">
        <button type="button" className="final-result__restart" onClick={onRestart}>
          처음부터 다시 만들기
        </button>
        <button type="button" className="final-result__download" onClick={handleDownload}>
          다운로드
        </button>
      </div>
      <p className="final-result__download-note">다운로드되는 이미지에는 AI 생성 표기가 포함됩니다.</p>
    </div>
  );
}

export default FinalResult;
