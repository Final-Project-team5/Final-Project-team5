import { useEffect, useMemo, useState } from 'react';
import { generateDrafts, planDesignPrompt, toImageSrc } from '../api/posterApi';
import { BACKGROUND_MODES, getSupportedBackgroundModes } from '../constants/backgroundModes';
import { toFriendlyMessage, withMinDuration } from '../api/mockUtils';
import aiBackgroundThumbnail from '../assets/faq/draft-grid.png';
import ErrorNotice from '../components/ErrorNotice';
import LoadingChecklist from '../components/LoadingChecklist';
import './DraftSelect.css';

const LOADING_STEPS = ['키워드 분석 중', '배경 시안 그리는 중', '시안 3장 정리하는 중'];
const PALETTE = ['#F4E7DC', '#DFA48E', '#CFE7DE', '#D9E7F5', '#DED7F5'];
const POSTER_PRODUCT_CATEGORIES = new Set(['food', 'beauty', 'goods']);

function Icon({ name }) {
  const paths = {
    sparkles: <><path d="m12 3 1.1 3.1L16 7.3l-2.9 1.1L12 12l-1.1-3.6L8 7.3l2.9-1.2L12 3Z"/><path d="m5.5 12 .8 2.2 2.2.8-2.2.8L5.5 18l-.8-2.2-2.2-.8 2.2-.8.8-2.2ZM18 13l.7 1.8 1.8.7-1.8.7L18 18l-.7-1.8-1.8-.7 1.8-.7L18 13Z"/></>,
    palette: <><path d="M12 3a9 9 0 0 0 0 18h1.2a1.8 1.8 0 0 0 1.3-3.1 1.8 1.8 0 0 1 1.3-3.1H18A3 3 0 0 0 21 12a9 9 0 0 0-9-9Z"/><path d="M7.5 10h.01M9.5 6.5h.01M14 6h.01M17 9h.01"/></>,
    square: <rect x="4" y="4" width="16" height="16" rx="3"/>,
    blend: <><circle cx="9" cy="12" r="6"/><circle cx="15" cy="12" r="6"/></>,
    wand: <><path d="m4 20 11-11"/><path d="m14 4 .7 2.1L17 7l-2.3.9L14 10l-.7-2.1L11 7l2.3-.9L14 4ZM19 12l.5 1.5L21 14l-1.5.5L19 16l-.5-1.5L17 14l1.5-.5L19 12Z"/></>,
    pipette: <><path d="m19 3 2 2-9 9-3-3 9-9Z"/><path d="m11 13-5.5 5.5L3 21l2.5-2.5"/></>,
  };
  return <svg className="draft-select__icon" viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}

function ArrowIcon({ back = false }) {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d={back ? 'm15 18-6-6 6-6' : 'm9 6 6 6-6 6'} /></svg>;
}

function ChoiceCard({ icon, title, description, preview, onClick, selected = false, compact = false }) {
  return <button type="button" aria-pressed={selected} className={`draft-select__choice-card${selected ? ' draft-select__choice-card--selected' : ''}${compact ? ' draft-select__choice-card--compact' : ''}`} onClick={onClick}>
    <span className="draft-select__choice-icon"><Icon name={icon} /></span>
    <span className="draft-select__choice-copy"><strong>{title}</strong><span>{description}</span></span>
    <span className={`draft-select__choice-preview draft-select__choice-preview--${preview}`}>
      {preview === 'ai' && <img src={aiBackgroundThumbnail} alt="AI 배경 예시" />}
      {preview === 'palette' && <span className="draft-select__mini-palette">{PALETTE.slice(0, 4).map((color) => <i key={color} style={{ background: color }} />)}</span>}
    </span>
    <span className="draft-select__choice-arrow">{selected ? '✓' : <ArrowIcon />}</span>
  </button>;
}

function BackButton({ onClick }) {
  return <button type="button" className="draft-select__secondary" onClick={onClick}><ArrowIcon back />이전으로</button>;
}

function SetupPage({ title, description, children, onBack }) {
  return <div className="draft-select draft-select--setup">
    <h1 className="draft-select__title">{title}</h1>
    {description && <p className="draft-select__description">{description}</p>}
    <div className="draft-select__choice-list">{children}</div>
    <div className="draft-select__actions draft-select__actions--back"><BackButton onClick={onBack} /></div>
  </div>;
}

function ColorField({ label, value, onChange }) {
  return <div className="draft-select__color-field">
    <span className="draft-select__color-label">{label}</span>
    <div className="draft-select__palette">
      {PALETTE.map((chip) => <button key={chip} type="button" title={chip} aria-label={`${chip} 선택`} className={`draft-select__color-chip${value === chip ? ' draft-select__color-chip--active' : ''}`} style={{ backgroundColor: chip }} onClick={() => onChange(chip)}>{value === chip && '✓'}</button>)}
      <label className="draft-select__picker"><input type="color" value={value} onChange={(event) => onChange(event.target.value.toUpperCase())} /><Icon name="palette" /><span>직접 선택</span></label>
    </div>
    <code className="draft-select__hex">{value}</code>
  </div>;
}

function DraftSelect({ mode, productImage, spec, onConfirm, onBack }) {
  const ratio = spec?.aspect_ratio || '1:1';
  const posterCategory = spec?.business_type === 'product' && POSTER_PRODUCT_CATEGORIES.has(spec?.category)
    ? spec.category
    : undefined;
  const supported = useMemo(() => getSupportedBackgroundModes(spec?.business_type, ratio), [spec?.business_type, ratio]);
  const needsModeChoice = supported.length > 1;
  const onlyMode = needsModeChoice ? null : supported[0];
  const initialPhase = onlyMode === BACKGROUND_MODES.SIMPLE ? 'simple-settings' : onlyMode === BACKGROUND_MODES.AI ? 'drafts' : 'background-mode';
  const [phase, setPhase] = useState(initialPhase);
  const [simpleType, setSimpleType] = useState(null);
  const [colorMethod, setColorMethod] = useState(null);
  const [color, setColor] = useState(PALETTE[0]);
  const [gradientStart, setGradientStart] = useState(PALETTE[0]);
  const [gradientEnd, setGradientEnd] = useState(PALETTE[1]);
  const [config, setConfig] = useState(onlyMode === BACKGROUND_MODES.AI ? { backgroundMode: 'ai' } : null);
  const [drafts, setDrafts] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [error, setError] = useState(null);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    if (phase !== 'drafts' || !config) return undefined;
    let cancelled = false;
    const controller = new AbortController();
    setDrafts(null); setError(null);
    withMinDuration(generateDrafts({ mode, image: productImage, prompt: planDesignPrompt(spec), category: posterCategory, ratio, ...config, num_images: 3, signal: controller.signal }), 3000)
      .then((result) => { if (!cancelled) { setDrafts(result.drafts); setSelectedId(result.drafts[0]?.id ?? null); } })
      .catch((reason) => { if (!cancelled) setError(toFriendlyMessage(reason, 'drafts')); });
    return () => { cancelled = true; controller.abort(); };
  }, [config, mode, phase, posterCategory, productImage, ratio, retry, spec]);

  const beginAi = () => { setConfig({ backgroundMode: 'ai' }); setPhase('drafts'); };
  const beginSimple = () => setPhase('simple-settings');
  const startSimple = () => {
    const manual = colorMethod === 'manual';
    setConfig({
      backgroundMode: simpleType,
      bgColors: manual ? (simpleType === 'solid' ? [color] : [gradientStart, gradientEnd]) : undefined,
      gradientDirection: simpleType === 'gradient' ? 'diagonal' : undefined,
    });
    setPhase('drafts');
  };
  const backFromSimple = () => needsModeChoice ? setPhase('background-mode') : onBack();
  const selectedDraft = drafts?.find((draft) => draft.id === selectedId) || null;
  const aspectRatio = ratio.replace(':', ' / ');

  if (phase === 'background-mode') return <SetupPage title="어떤 배경으로 시안을 만들어볼까요?" description="제품과 광고 분위기에 맞는 방식을 먼저 골라주세요." onBack={onBack}>
    <ChoiceCard icon="sparkles" title="AI 배경" description={<>제품과 분위기에 어울리는 배경을<br />AI가 자연스럽게 만들어드려요.</>} preview="ai" onClick={beginAi} />
    <ChoiceCard icon="palette" title="심플 배경" description={<>원하는 색상의 단색 또는<br />그라데이션 배경으로 만들어요.</>} preview="brand-simple" onClick={beginSimple} />
  </SetupPage>;

  if (phase === 'simple-settings') return <div className="draft-select draft-select--setup">
    <h1 className="draft-select__title">심플 배경을 설정해주세요</h1>
    <p className="draft-select__description">원하는 항목을 위에서부터 차례로 선택해주세요.</p>
    <section className="draft-select__progressive-section">
      <h2 className="draft-select__section-title">1. 배경 형태</h2>
      <div className="draft-select__choice-list draft-select__choice-list--compact">
        <ChoiceCard compact selected={simpleType === 'solid'} icon="square" title="단색 배경" description="하나의 색으로 깔끔하게 만들어요." preview="solid" onClick={() => setSimpleType('solid')} />
        <ChoiceCard compact selected={simpleType === 'gradient'} icon="blend" title="그라데이션 배경" description="두 색을 자연스럽게 연결해 만들어요." preview="simple" onClick={() => setSimpleType('gradient')} />
      </div>
    </section>
    {simpleType && <section className="draft-select__progressive-section draft-select__progressive-section--revealed">
      <h2 className="draft-select__section-title">2. 색상 선택</h2>
      <div className="draft-select__choice-list draft-select__choice-list--compact">
        <ChoiceCard compact selected={colorMethod === 'recommended'} icon="wand" title="알아서 추천" description="광고 분위기에 어울리는 색감으로 만들어요." preview="recommend" onClick={() => setColorMethod('recommended')} />
        <ChoiceCard compact selected={colorMethod === 'manual'} icon="pipette" title="직접 선택" description="추천 색상이나 컬러피커에서 직접 골라요." preview="palette" onClick={() => setColorMethod('manual')} />
      </div>
    </section>}
    {simpleType && colorMethod === 'manual' && <section className="draft-select__picker-panel draft-select__progressive-section--revealed">
      <h2 className="draft-select__section-title">3. 색상 설정</h2>
      {simpleType === 'solid' ? <ColorField label="추천 색상" value={color} onChange={setColor} /> : <><ColorField label="시작 색상" value={gradientStart} onChange={setGradientStart} /><ColorField label="끝 색상" value={gradientEnd} onChange={setGradientEnd} /></>}
      <div className={`draft-select__large-preview${simpleType === 'solid' ? ' draft-select__large-preview--solid' : ''}`} style={{ background: simpleType === 'solid' ? color : `linear-gradient(135deg, ${gradientStart}, ${gradientEnd})` }} aria-label="선택한 배경 미리보기" />
    </section>}
    <div className="draft-select__actions"><BackButton onClick={backFromSimple} /><button type="button" className="draft-select__primary" disabled={!simpleType || !colorMethod} onClick={startSimple}>시안 만들기</button></div>
  </div>;

  return <div className="draft-select"><h1 className="draft-select__title">마음에 드는 시안을 골라주세요</h1><p className="draft-select__description">가벼운 모델로 빠르게 만든 초안이에요. 하나를 고르면 다음 단계에서 고품질로 다듬어드려요.</p>
    {!drafts && !error && <LoadingChecklist variant="draft" title="배경 시안을 만들고 있어요" caption={spec?.business_type === 'service' ? '서비스 광고에 어울리는 AI 시안 3장을 만들고 있어요' : '가벼운 모델로 3장을 빠르게 그려드릴게요'} steps={LOADING_STEPS} stepDurationMs={1000} />}{error && <ErrorNotice message={error} onRetry={() => setRetry((value) => value + 1)} />}
    {drafts && <><div className="draft-select__grid" style={{ '--draft-ratio': aspectRatio }}>{drafts.map((draft, index) => <button key={draft.id} type="button" className={`draft-select__card${draft.id === selectedId ? ' draft-select__card--active' : ''}`} onClick={() => setSelectedId(draft.id)}><img src={toImageSrc(draft.image)} alt={`시안 ${index + 1}`} />{draft.id === selectedId && <span className="draft-select__check">✓</span>}</button>)}</div>{selectedDraft && <div className="draft-select__preview" style={{ '--draft-ratio': aspectRatio }}><img src={toImageSrc(selectedDraft.image)} alt="선택한 시안 확대 보기" /></div>}</>}
    <div className="draft-select__actions"><button type="button" className="draft-select__secondary" onClick={onBack}><ArrowIcon back />문구 선택으로 돌아가기</button><button type="button" className="draft-select__primary" disabled={!selectedDraft} onClick={() => onConfirm(selectedDraft)}>이 배경으로 꾸미러 가기</button></div></div>;
}

export default DraftSelect;
