import { useEffect, useMemo, useRef, useState } from 'react';
import { generateRefine, toImageSrc } from '../api/posterApi';
import { toFriendlyMessage, withMinDuration } from '../api/mockUtils';
import ErrorNotice from '../components/ErrorNotice';
import LoadingChecklist from '../components/LoadingChecklist';
import './PosterEditor.css';

// 로딩 B — [완성하기] 클릭 후 /generate/refine 호출 중 보여주는 체크리스트
// (docs/UIUX_스펙정리.md 3장). 로딩 A(화면 C)와 문구·강조색을 다르게 해서
// "왜 또 기다리지" 하고 헷갈리지 않게 한다.
const REFINE_LOADING_STEPS = ['이미지 고품질화 중', '문구 배치 최적화 중', '규격에 맞게 마무리 중'];
// mock 응답이 이보다 빨리 와도 체크리스트 3단계가 순서대로 다 보일 때까지는
// 화면을 넘기지 않는다. 항목별로 균등하게 배분(3초 ÷ 3단계 = 1초씩).
const REFINE_LOADING_MIN_MS = 3000;

// ResizeObserver가 실제 폭을 알려주기 전까지 쓰는 초기값(px).
// headline_size/sub_size와 외곽선 두께는 캔버스 폭에 비례하므로,
// 첫 렌더 이후에는 이 상수가 아니라 측정된 canvasWidth를 쓴다.
const CANVAS_SIZE = 480;

// 3단계 프리셋 → headline_size/sub_size(짧은 변 대비 비율) 매핑.
// margin은 "최소" 드래그 안전 여백(비율) — 실제 여백은 렌더된 텍스트 박스 크기에 따라
// 이보다 더 커질 수 있다 (아래 ResizeObserver 보정 참고).
const SIZE_PRESETS = {
  small: { label: '작게', headline_size: 0.045, sub_size: 0.026, margin: 0.05 },
  medium: { label: '보통', headline_size: 0.065, sub_size: 0.038, margin: 0.065 },
  large: { label: '크게', headline_size: 0.085, sub_size: 0.05, margin: 0.08 },
};

// 줄바꿈 지점을 정하는 글자 수 상한 — 폰트 크기(preset)와 무관하게 고정이다.
// 실제로는 도혁님 문구 모델이 줄바꿈까지 고정해서 내려주므로, 여기 값은 그 자리를
// 대신하는 mock 기준값일 뿐 폰트 크기에 따라 달라지면 안 된다.
const HEADLINE_CHARS_PER_LINE = 10;
const SUB_CHARS_PER_LINE = 15;

// 확정 폰트 5종 (8/10, 진우님 완성형 검증 — 한글 음절 11,172자 전체 지원).
// font_id는 백엔드 whitelist 매핑에 그대로 쓰이는 값이라 이름 그대로 유지해야 한다.
// CSS @font-face가 백엔드 FONT_IDS와 같은 저장소 내 TTF 파일을 로드한다.
const FONT_OPTIONS = [
  { id: 'pretendard', label: 'Pretendard', family: '"Pretendard", sans-serif' },
  { id: 'nanummyeongjo', label: '나눔명조 Bold', family: '"Nanum Myeongjo", serif' },
  { id: 'gmarketsans', label: 'Gmarket Sans', family: '"Gmarket Sans", sans-serif' },
  { id: 'galmuri11', label: 'Galmuri11', family: '"Galmuri11", monospace' },
  { id: 'nanumpen', label: '나눔손글씨펜', family: '"Nanum Pen Script", cursive' },
];

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

/**
 * 문구를 정해진 글자 수 상한에 맞춰 줄바꿈한다. 폰트 크기(px)가 아니라
 * "글자 수"만 기준으로 삼기 때문에, preset이 바뀌어 폰트가 커지거나 작아져도
 * 줄이 갈리는 지점은 항상 동일하게 유지된다 (요청사항 1).
 */
function wrapTextByChars(text, maxChars) {
  if (!text) return [];
  const words = text.split(' ');
  const lines = [];
  let current = '';

  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word;
    if (candidate.length <= maxChars) {
      current = candidate;
      continue;
    }
    if (current) lines.push(current);
    let rest = word;
    while (rest.length > maxChars) {
      lines.push(rest.slice(0, maxChars));
      rest = rest.slice(maxChars);
    }
    current = rest;
  }
  if (current) lines.push(current);
  return lines;
}

/**
 * 화면 D — 문구 위치·크기 자유 조정
 * 선택한 시안(화면 C) 위에 문구를 얹어 드래그로 위치를, 프리셋 버튼으로 크기를
 * 정한다. 서버 호출 없이 CSS로 실시간 미리보기만 하다가 [완성하기]를 누를 때
 * 딱 한 번 /generate/refine(mock)을 호출한다. (docs/UIUX_스펙정리.md 4장·5장 참고)
 *
 * [완성하기]를 누르면 로딩 B(고품질화 중) 체크리스트로 화면이 전환되고,
 * /generate/refine이 실패하면 편집 화면으로 돌아와 ErrorNotice와 "다시 시도"를
 * 보여준다(문구 위치·크기·서체 등 지금까지 정한 값은 그대로 유지된다).
 */
function PosterEditor({ draftImage, background, originalImage, prompt, category, ratio = '1:1', subjectKind = 'product', headline, sub, onComplete, onBack }) {
  const canvasRef = useRef(null);
  const textGroupRef = useRef(null);
  const draggingRef = useRef(false);
  const submitLockRef = useRef(false);
  const [pos, setPos] = useState({ x: 0.5, y: 0.5 });
  const [preset, setPreset] = useState('medium');
  const [fontId, setFontId] = useState(FONT_OPTIONS[0].id);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  // 실제로 적용되는 안전 여백(비율) — 프리셋 최소값과 "지금 렌더된 텍스트 박스의
  // 절반 크기" 중 더 큰 쪽. 텍스트 중심이 아니라 텍스트 박스 가장자리가 안전선을
  // 넘지 않도록 하기 위한 보정값이다.
  const [safeMargin, setSafeMargin] = useState({ x: 0.065, y: 0.065 });
  // 실제로 렌더된 캔버스 폭(px). 캔버스는 width:100% / max-width:640px이라
  // 뷰포트에 따라 달라진다. headline_size·sub_size와 외곽선 두께는 모두
  // "캔버스 대비 비율"이므로 고정 상수가 아니라 이 값을 곱해야 최종 출력과 맞는다.
  const [canvasWidth, setCanvasWidth] = useState(CANVAS_SIZE);

  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return undefined;
    const observer = new ResizeObserver(([entry]) => {
      setCanvasWidth(entry.contentRect.width || CANVAS_SIZE);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const sizeInfo = SIZE_PRESETS[preset];
  // 서버는 1024px 캔버스에 STROKE_WIDTH=3으로 글자 둘레를 두른다(비율 3/1024).
  // -webkit-text-stroke는 윤곽선 위에 안팎 절반씩 그리므로 바깥쪽 두께를 맞추려면
  // 2배를 준다. paint-order로 안쪽 절반은 글자에 덮인다.
  const strokeWidth = (canvasWidth * 3 / 1024) * 2;
  const selectedFont = FONT_OPTIONS.find((f) => f.id === fontId) ?? FONT_OPTIONS[0];

  // headline/sub 자체가 바뀔 때만 다시 계산 — preset(폰트 크기)은 의도적으로
  // deps에서 뺐다. 그래야 크기를 바꿔도 줄바꿈 지점이 그대로 유지된다.
  const headlineLines = useMemo(() => wrapTextByChars(headline, HEADLINE_CHARS_PER_LINE), [headline]);
  const subLines = useMemo(() => wrapTextByChars(sub, SUB_CHARS_PER_LINE), [sub]);

  // 텍스트 박스 실측 크기가 바뀔 때마다(프리셋 변경, 문구 변경, 리사이즈) 안전 여백을
  // 다시 계산하고, 현재 위치가 그 여백을 벗어났으면 안쪽으로 당겨준다.
  useEffect(() => {
    const canvasEl = canvasRef.current;
    const textEl = textGroupRef.current;
    if (!canvasEl || !textEl) return undefined;

    const recompute = () => {
      const canvasRect = canvasEl.getBoundingClientRect();
      const textRect = textEl.getBoundingClientRect();
      if (!canvasRect.width || !canvasRect.height) return;

      // 텍스트 박스의 절반 크기 위에 프리셋 여백을 "더해서" 항상 눈에 보이는
      // 간격이 남도록 한다 (max만 쓰면 텍스트가 캔버스 폭 대부분을 차지할 때
      // 여백이 0으로 사라짐). 0.499로만 상한을 둬서 clamp 범위가 뒤집히는 것만
      // 막는다 — 문구가 캔버스 폭을 거의 다 채울 만큼 길면 좌우로 움직일 여지가
      // 실제로 거의 없는 게 맞다(그래야 여백이 항상 지켜짐).
      const marginX = Math.min(0.499, textRect.width / 2 / canvasRect.width + sizeInfo.margin);
      const marginY = Math.min(0.499, textRect.height / 2 / canvasRect.height + sizeInfo.margin);
      setSafeMargin({ x: marginX, y: marginY });
      setPos((prev) => {
        const next = { x: clamp(prev.x, marginX, 1 - marginX), y: clamp(prev.y, marginY, 1 - marginY) };
        return next.x === prev.x && next.y === prev.y ? prev : next;
      });
    };

    recompute();
    const observer = new ResizeObserver(recompute);
    observer.observe(canvasEl);
    observer.observe(textEl);
    return () => observer.disconnect();
  }, [sizeInfo.margin, headline, sub]);

  const updateFromPointer = (e) => {
    const rect = canvasRef.current.getBoundingClientRect();
    const relX = (e.clientX - rect.left) / rect.width;
    const relY = (e.clientY - rect.top) / rect.height;
    setPos({
      x: clamp(relX, safeMargin.x, 1 - safeMargin.x),
      y: clamp(relY, safeMargin.y, 1 - safeMargin.y),
    });
  };

  const handlePointerDown = (e) => {
    e.preventDefault();
    draggingRef.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
    updateFromPointer(e);
  };

  const handlePointerMove = (e) => {
    if (!draggingRef.current) return;
    updateFromPointer(e);
  };

  const handlePointerUp = (e) => {
    draggingRef.current = false;
    e.currentTarget.releasePointerCapture(e.pointerId);
  };

  // 프리셋 변경에 따른 재클램프는 위 useEffect(ResizeObserver)가 텍스트 박스
  // 실측 크기를 반영해서 자동으로 처리한다.
  const handlePresetChange = (key) => setPreset(key);

  const handleComplete = async () => {
    if (submitLockRef.current) return;
    submitLockRef.current = true;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const res = await withMinDuration(
        generateRefine({
          draft_image: draftImage,
          original_image: originalImage,
          background,
          prompt,
          category,
          subject_kind: subjectKind,
          text: {
            headline,
            sub,
            x: pos.x,
            y: pos.y,
            headline_size: sizeInfo.headline_size,
            sub_size: sizeInfo.sub_size,
            style: 'plain', // 기본값이 "bar"라 생략하면 반투명 배경 박스가 깔림 — 반드시 명시
            font_id: fontId, // 화면 D 드롭다운에서 고른 서체 — 백엔드 whitelist 매핑에 사용
            align: 'center', // x/y가 중심 기준(8/10 확정)이라 명시 안 하면 서버 기본값 left로 어긋남
          },
        }),
        REFINE_LOADING_MIN_MS,
      );
      setSubmitting(false);
      onComplete({
        image: toImageSrc(res.image),
        meta: res.meta,
        text: { headline, sub, ...pos, ...sizeInfo, font_id: fontId, align: 'center' },
      });
    } catch (err) {
      setSubmitting(false);
      submitLockRef.current = false;
      setSubmitError(toFriendlyMessage(err, 'refine'));
    }
  };

  // 로딩 B — [완성하기] 클릭 후 /generate/refine 응답을 기다리는 동안은 편집
  // UI 대신 전체 화면 체크리스트로 전환한다(로딩 A와 시각적으로 구분, 8/10 요구사항).
  if (submitting) {
    return (
      // key를 다르게 줘서 편집 화면 <div>와 서로 다른 노드로 취급되게 한다 —
      // 그래야 React가 기존 노드를 재사용(업데이트)하지 않고 새로 마운트해서
      // .poster-editor에 걸린 page-fade-in 애니메이션이 전환마다 다시 재생된다.
      <div key="submitting" className="poster-editor poster-editor--loading">
        <LoadingChecklist
          variant="refine"
          title="고품질 이미지로 다듬고 있어요"
          caption="원본을 살려 배경을 다듬고 문구를 자연스럽게 얹는 중이에요"
          steps={REFINE_LOADING_STEPS}
          stepDurationMs={REFINE_LOADING_MIN_MS / REFINE_LOADING_STEPS.length}
        />
      </div>
    );
  }

  return (
    <div key="editing" className="poster-editor">
      <h1 className="poster-editor__title">문구 위치와 크기를 정해주세요</h1>
      <p className="poster-editor__description">
        문구를 드래그해서 원하는 위치로 옮기고, 크기를 골라보세요. 서버에는 완성하기를 눌렀을 때 한 번만 전송돼요.
      </p>

      <div className="poster-editor__canvas" ref={canvasRef} style={{ '--canvas-ratio': ratio.replace(':', ' / ') }}>
        <img className="poster-editor__bg" src={toImageSrc(draftImage)} alt="선택한 시안 배경" />
        <div
          className="poster-editor__safe-guide"
          style={{
            left: `${safeMargin.x * 100}%`,
            right: `${safeMargin.x * 100}%`,
            top: `${safeMargin.y * 100}%`,
            bottom: `${safeMargin.y * 100}%`,
          }}
          aria-hidden="true"
        />
        <div
          ref={textGroupRef}
          className="poster-editor__text-group"
          style={{
            left: `${pos.x * 100}%`,
            top: `${pos.y * 100}%`,
            // width: max-content — 줄바꿈은 이제 headline/subLines가 글자 수
            // 기준으로 미리 정해서(polling font size와 무관) 각 줄을
            // white-space:nowrap으로 그리므로, 여기서는 그 결과물이 차지하는
            // 실제 폭만큼만 박스가 갖게 하면 된다. (더 이상 CSS 자동 줄바꿈에
            // 기대지 않으므로 maxWidth로 잘라낼 필요도, position:absolute의
            // shrink-to-fit 버그를 걱정할 필요도 없다.)
            width: 'max-content',
            fontFamily: selectedFont.family,
            // 외곽선 두께는 캔버스 폭에 비례한다. CSS에서 고정값을 쓰면
            // 창 크기에 따라 최종 출력과 어긋난다.
            '--stroke-width': `${strokeWidth}px`,
          }}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
        >
          <div className="poster-editor__headline" style={{ fontSize: `${sizeInfo.headline_size * canvasWidth}px` }}>
            {headlineLines.map((line, idx) => (
              <div key={idx} className="poster-editor__line">
                {line}
              </div>
            ))}
          </div>
          <div className="poster-editor__sub" style={{ fontSize: `${sizeInfo.sub_size * canvasWidth}px` }}>
            {subLines.map((line, idx) => (
              <div key={idx} className="poster-editor__line">
                {line}
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="poster-editor__size-presets">
        {Object.entries(SIZE_PRESETS).map(([key, info]) => (
          <button
            key={key}
            type="button"
            className={'poster-editor__preset-chip' + (preset === key ? ' poster-editor__preset-chip--active' : '')}
            onClick={() => handlePresetChange(key)}
          >
            {info.label}
          </button>
        ))}
      </div>

      <div className="poster-editor__font-section">
        <label className="poster-editor__font-label" htmlFor="poster-font-select">
          서체
        </label>
        <select
          id="poster-font-select"
          className="poster-editor__font-select"
          value={fontId}
          style={{ fontFamily: selectedFont.family }}
          onChange={(e) => setFontId(e.target.value)}
        >
          {FONT_OPTIONS.map((font) => (
            <option key={font.id} value={font.id} style={{ fontFamily: font.family }}>
              {font.label}
            </option>
          ))}
        </select>
      </div>

      {submitError && (
        <div className="poster-editor__submit-error">
          <ErrorNotice message={submitError} onRetry={handleComplete} />
        </div>
      )}

      <div className="poster-editor__actions">
        <button type="button" className="poster-editor__secondary" onClick={onBack}>
          이전으로
        </button>
        <button type="button" className="poster-editor__primary" onClick={handleComplete}>
          포스터 완성하기
        </button>
      </div>
    </div>
  );
}

export default PosterEditor;
