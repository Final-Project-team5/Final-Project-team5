import Mascot from '../components/Mascot';
import './FinalResult.css';

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
 * 사이즈는 챗봇 용도 질문(화면 A)에서 미리 정해지므로 여기엔 사이즈 토글이 없다
 * (8/8 확정). "같은 배경으로 다른 이미지 생성하기" 재생성 기능은 flat/AI 배경별로
 * 각각 구현이 필요해 1차 서비스 스코프에서 제외하기로 팀 논의로 확정됨(8/11) —
 * 관련 버튼/로직은 넣지 않는다.
 *
 * 이 화면은 API를 직접 호출하지 않는다(화면 D에서 이미 받은 결과를 보여주고
 * 로컬 다운로드만 수행) — 그래서 로딩/에러 UI 고도화 대상에서 제외됨
 * (8/11 요청 범위: 화면 A~D). 다운로드 실패 같은 로컬 동작 에러는 스코프 밖.
 */
function FinalResult({ image, ratio = '1:1', headline, sub, status, onRestart }) {
  const badge = BADGE_INFO[status] || BADGE_INFO.pass;
  const aspectRatio = ratio.replace(':', ' / ');

  const handleDownload = () => {
    downloadDataUri(image, `ad-poster-${Date.now()}.png`);
  };

  return (
    <div className="final-result">
      <h1 className="final-result__title">광고 포스터가 완성됐어요</h1>
      <p className="final-result__description">문구와 이미지가 모두 준비됐어요. 마음에 들면 다운로드해보세요.</p>

      <div className="final-result__scene">
        <div className="final-result__card">
          <span className={`final-result__badge ${badge.className}`}>{badge.label}</span>

          <div className="final-result__image-wrap" style={{ '--result-ratio': aspectRatio }}>
            <img className="final-result__image" src={image} alt="완성된 광고 포스터" />
          </div>

          <p className="final-result__ai-caption">이 콘텐츠는 생성형 AI로 제작되었습니다.</p>

          <div className="final-result__copy">
            <div className="final-result__headline">{headline}</div>
            <div className="final-result__sub">{sub}</div>
          </div>
        </div>

        {/* 완성을 축하하는 success 캐릭터 — 카드 오른쪽 아래, 카드 밖에 독립적으로
            서 있게 배치한다(카드 안 제목·배지·시안 이미지는 가리지 않음). */}
        <div className="final-result__mascot-wrap">
          <Mascot expression="success" size={250} className="final-result__mascot" />
        </div>
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
