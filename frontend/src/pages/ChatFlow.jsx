import { useEffect, useRef, useState } from 'react';
import {
  ALLOWED_IMAGE_TYPES,
  BACKGROUND_REFERENCE_GUIDE_TEXT,
  BACKGROUND_REFERENCE_LABEL,
  BUSINESS_TYPE_OPTIONS,
  BUSINESS_TYPE_QUESTION_TEXT,
  CATEGORY_HINT_TEXT,
  CATEGORY_OPTIONS_BY_TYPE,
  CATEGORY_QUESTION_TEXT_BY_TYPE,
  MAX_IMAGE_BYTES,
  PHOTO_GUIDE_TEXT,
  SERVICE_FLOW,
  TOTAL_STEPS_BY_TYPE,
  USAGE_OPTIONS_BY_TYPE,
  USAGE_QUESTION_TEXT,
  confirmProduct,
  generateCopy,
  generateVisualPrompt,
  serviceAdvance,
  suggestOptions,
  visionBackground,
  visionProduct,
} from '../api/copyApi';
import { toFriendlyMessage } from '../api/mockUtils';
import ErrorNotice from '../components/ErrorNotice';
import Mascot from '../components/Mascot';
import './ChatFlow.css';

// 챗봇 말풍선 옆 아바타 크기 — 말풍선 세로 높이보다 살짝 크게
const CHAT_AVATAR_SIZE = 92;

// 화면 진행 순서(느낌→강조점→추가요청)만 다루는 stage 순번 — product/service
// 둘 다 이 세 stage를 마지막에 공유한다(느낌/강조점/추가요청 문구·선택지 자체는
// business_type별로 다르지만 진행 순서는 같다).
const FLOW_STAGE_ORDER = ['tone', 'keywords', 'request'];
// stage → 실제 API 호출에 쓰는 step 번호. product는 백엔드 FLOW_STEPS 번호(3=Vision이
// 이미 처리, 4/5/6), service는 product 단계가 빠진 백엔드 fixed 번호(3/4/5)를 쓴다.
const API_STEP_BY_TYPE = {
  product: { tone: 4, keywords: 5, request: 6 },
  service: { tone: 3, keywords: 4, request: 5 },
};
// stage → 화면에 보여줄 진행 단계 번호(1부터). business_type이 정해지기 전(0단계)엔 1.
const UI_STEP_BY_TYPE = {
  product: { category: 2, usage: 3, photo: 4, tone: 5, keywords: 6, request: 7 },
  service: { category: 2, usage: 3, tone: 4, keywords: 5, request: 6 },
};

/**
 * 화면 A — 챗봇 진행 화면 (8/14 챗봇 분기 개편 반영 — docs/UIUX_스펙정리.md 3-3·3-4장)
 *
 * 0단계(제품/서비스)·업종·용도는 프론트 하드코딩이라 서버 호출이 없다. product는
 * 업종/용도 확정 직후 사진을 필수로 받아 Vision이 제품을 인식하고("맞아요"로
 * 확정 / "수정할게요"로 보정 / 인식 실패는 재업로드) — 제품명을 직접 묻는 질문은
 * 없다. service는 학원(academy)/체육관·도장(sports) 2업종만 지원하고 사진/제품명
 * 단계 자체가 없다(SNS 1:1 고정).
 *
 * 진행률 분모는 백엔드 total_steps(product 6 / service 5)에 프론트 전용
 * business_type 단계를 더해 product 7 / service 6으로 직접 표시한다.
 *
 * product 사진 단계(3단계)는 제품 사진(필수)과 배경 참고 이미지(선택)를 같은
 * 질문 화면 안에서 받되, 역할을 처음부터 분리해서 관리한다(8/18 신규 —
 * LLM이 이미지 역할을 자동 판별하는 구조 아님). productImage는 기존대로 Vision
 * 제품 인식과 화면 D(refine) original_image에 쓰이고, backgroundReference는
 * 제품 confirm 뒤 별도 background Vision에만 보낸다. 이후에는 state로 보존해
 * onComplete outcome에 함께 실어 보내되 poster API 요청에는 직접 추가하지 않는다.
 *
 * 느낌(tone)/강조점(keywords, 복수 선택)/추가요청(request, 자유 입력)은 각각
 * 독립된 질문 카드로 순서대로 나온다(8/11 PM 확인 — 한 화면에 합치지 않음).
 * 강조점은 [다음] 버튼으로 그 질문만 마무리하고, 추가 요청은 [이 내용으로 완료]
 * 버튼이 전체 흐름의 최종 마무리다.
 *
 * API 호출이 실패하면 말풍선 자리에 에러 카드를 띄우고 "다시 시도"를 누르면
 * 같은 요청을 다시 보낸다(mock 실패 재현은 api/mockUtils.js 참고).
 */
function ChatFlow({ onComplete }) {
  const [messages, setMessages] = useState([{ id: 'q0', role: 'bot', kind: 'business_type', answered: false }]);
  const [businessType, setBusinessType] = useState(null);
  const [spec, setSpec] = useState({});
  const [mode, setMode] = useState(null); // 'inpaint'(product) | 'text2img'(service) — business_type 확정 시 함께 정해짐
  const [productImage, setProductImage] = useState(null);
  // 배경 참고 이미지(선택) — productImage와 역할이 다른 별도 state. 제품 Vision과
  // 분리된 background Vision에만 사용한다. service 흐름에는 사진 단계가 없어 null.
  const [backgroundReference, setBackgroundReference] = useState(null);
  const [currentStep, setCurrentStep] = useState(1);
  const [totalSteps, setTotalSteps] = useState(TOTAL_STEPS_BY_TYPE.product);
  const [busy, setBusy] = useState(false);

  const idRef = useRef(0);
  const bottomRef = useRef(null);
  // 업종/용도/0단계처럼 서버 호출 없이 클릭 즉시 다음 질문을 붙이는 "즉시 처리"
  // 핸들러 전용 중복 클릭 가드 — 같은 메시지 id로 두 번째 호출이 들어오면
  // 무시한다. busy 상태를 쓰지 않는 이유: 이 핸들러들은 원래 로딩 표시 없이
  // 순간 전환되는 UX라(기존 동작 유지), busy를 true로 두면 그 UX가 바뀐다.
  // 각 메시지 id는 한 번만 쓰이므로 별도로 풀어줄 필요가 없다.
  const answeredOnceRef = useRef(new Set());
  const flowSubmissionRef = useRef(false);
  const answerOnce = (id) => {
    if (answeredOnceRef.current.has(id)) return false;
    answeredOnceRef.current.add(id);
    return true;
  };

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages]);

  const uid = () => `m${++idRef.current}`;
  const addMessage = (msg) => setMessages((prev) => [...prev, msg]);
  const markAnswered = (id) => setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, answered: true } : m)));
  const addUserBubble = (text) => addMessage({ id: uid(), role: 'user', kind: 'text', text });
  const addNote = (text) => {
    if (text) addMessage({ id: uid(), role: 'bot', kind: 'note', text });
  };

  const finishChat = async (finalSpec) => {
    setBusy(true);
    addMessage({ id: uid(), role: 'bot', kind: 'note', text: '제공해주신 정보를 바탕으로 문구를 만들고 있어요…' });
    try {
      const result = await generateCopy(finalSpec);
      // 이미지 모델에 보낼 영어 시각 프롬프트를 여기서 한 번만 만든다.
      // 시안 생성과 refine이 같은 값을 재사용하므로 흐름당 1회 호출이다.
      // 실패하면 null이고, 그 경우 planDesignPrompt()가 기존 조립으로 되돌아간다.
      // 이미 로딩 상태(busy)가 켜져 있는 구간이라 체감 지연이 늘지 않는다.
      const visualPrompt = await generateVisualPrompt(finalSpec);
      setBusy(false);
      // backgroundReference는 다음 화면들에 state로 전달된다. 분석 결과인
      // background_context는 finalSpec에 남지만 poster API 스키마는 변경하지 않는다.
      onComplete({
        spec: { ...finalSpec, visual_prompt: visualPrompt || undefined },
        mode,
        productImage,
        backgroundReference,
        result,
      });
    } catch (err) {
      setBusy(false);
      const errId = uid();
      addMessage({
        id: errId,
        role: 'bot',
        kind: 'error',
        text: toFriendlyMessage(err, 'copy'),
        retry: () => {
          setMessages((prev) => prev.filter((m) => m.id !== errId));
          finishChat(finalSpec);
        },
      });
    }
  };

  const pushQuestion = (res, stage) => {
    addNote(res.confirm_message);
    addMessage({
      id: uid(),
      role: 'bot',
      kind: 'question',
      stage,
      question: res.question,
      options: res.options,
      multiSelect: res.multiSelect,
      freeform: res.freeform,
      inputType: res.input_type,
      maxLength: res.max_length,
      regulation: res.regulation,
      answered: false,
    });
  };

  // --- 0단계: 제품/서비스 -------------------------------------------------
  const handleBusinessType = (value, label) => {
    if (!answerOnce('q0')) return; // 빠른 연속 클릭 시 질문 중복 추가 방지
    setMessages((prev) => prev.map((m) => (m.kind === 'business_type' ? { ...m, answered: true } : m)));
    addUserBubble(label);
    setBusinessType(value);
    setMode(value === 'product' ? 'inpaint' : 'text2img');
    setSpec({ business_type: value });
    setTotalSteps(TOTAL_STEPS_BY_TYPE[value]);
    setCurrentStep(UI_STEP_BY_TYPE[value].category);
    addMessage({
      id: uid(),
      role: 'bot',
      kind: 'question',
      stage: 'category',
      noOther: true,
      question: CATEGORY_QUESTION_TEXT_BY_TYPE[value],
      options: CATEGORY_OPTIONS_BY_TYPE[value].map((o) => o.label),
      multiSelect: false,
      freeform: false,
      answered: false,
    });
  };

  // --- 1단계: 업종 (product food/beauty/goods, service academy/sports) ----
  const handleCategoryAnswer = (question, label) => {
    if (!answerOnce(question.id)) return; // 빠른 연속 클릭 시 질문 중복 추가 방지
    markAnswered(question.id);
    addUserBubble(label);
    const opt = CATEGORY_OPTIONS_BY_TYPE[businessType].find((o) => o.label === label);
    const value = opt?.value || label;
    setSpec((prev) => ({ ...prev, category: value }));
    setCurrentStep(UI_STEP_BY_TYPE[businessType].usage);
    addNote(`${label} 업종이시군요!`);
    addMessage({
      id: uid(),
      role: 'bot',
      kind: 'question',
      stage: 'usage',
      noOther: true,
      question: USAGE_QUESTION_TEXT,
      options: USAGE_OPTIONS_BY_TYPE[businessType].map((o) => o.label),
      multiSelect: false,
      freeform: false,
      answered: false,
    });
  };

  // --- 2단계: 용도 (product SNS/배너/상세, service SNS 1:1 고정) ----------
  const handleUsageAnswer = (question, label) => {
    if (!answerOnce(question.id)) return; // 빠른 연속 클릭 시 질문 중복 추가 방지
    markAnswered(question.id);
    addUserBubble(label);
    const opt = USAGE_OPTIONS_BY_TYPE[businessType].find((o) => o.label === label);
    const nextSpec = { ...spec, purpose: opt?.value, aspect_ratio: opt?.aspect_ratio };
    setSpec(nextSpec);
    addNote(`${label}에 맞는 비율로 준비할게요!`);

    if (businessType === 'product') {
      setCurrentStep(UI_STEP_BY_TYPE.product.photo);
      addMessage({ id: uid(), role: 'bot', kind: 'photo', resolved: false });
    } else {
      setCurrentStep(UI_STEP_BY_TYPE.service.tone);
      const first = SERVICE_FLOW[0];
      addMessage({
        id: uid(),
        role: 'bot',
        kind: 'question',
        stage: 'tone',
        question: first.question,
        options: first.options,
        multiSelect: first.multiSelect,
        freeform: first.freeform,
        answered: false,
      });
    }
  };

  // --- 4/7(product 전용): 제품 confirm 후 배경 선택까지 완료해야 다음 질문으로 --
  const handlePhotoResolved = (photoMsgId, { image, backgroundReference: bgRef, spec: nextSpec, suggestion, backgroundWarning }) => {
    setMessages((prev) => prev.map((m) => (m.id === photoMsgId ? { ...m, resolved: true } : m)));
    setProductImage(image);
    setBackgroundReference(bgRef || null);
    setSpec(nextSpec);
    setCurrentStep(UI_STEP_BY_TYPE.product.tone);
    addNote(backgroundWarning);
    pushQuestion(suggestion, 'tone');
  };

  // --- 느낌/강조점/추가요청 공통 처리 (product는 실제 API, service는 고정 진행) --
  const handleFlowAnswer = async (question, answerText, isRetry = false) => {
    if (flowSubmissionRef.current) return;
    flowSubmissionRef.current = true;
    if (!isRetry) {
      markAnswered(question.id);
      addUserBubble(answerText);
    }
    setBusy(true);
    try {
      const advance = businessType === 'service' ? serviceAdvance : suggestOptions;
      const step = API_STEP_BY_TYPE[businessType][question.stage];
      const res = await advance({ message: answerText, step, spec });
      flowSubmissionRef.current = false;
      setBusy(false);
      setSpec(res.spec);
      if (res.done && res.regulation?.severity === 'warn') {
        addMessage({ id: uid(), role: 'bot', kind: 'regulation', regulation: res.regulation });
      }
      if (res.done) {
        await finishChat(res.spec);
        return;
      }
      const staysInStage = res.next_step === step;
      const nextStage = staysInStage
        ? question.stage
        : FLOW_STAGE_ORDER[FLOW_STAGE_ORDER.indexOf(question.stage) + 1];
      if (!staysInStage) setCurrentStep(UI_STEP_BY_TYPE[businessType][nextStage]);
      pushQuestion(res, nextStage);
    } catch (err) {
      flowSubmissionRef.current = false;
      setBusy(false);
      const errId = uid();
      addMessage({
        id: errId,
        role: 'bot',
        kind: 'error',
        text: toFriendlyMessage(err, 'options'),
        retry: () => {
          setMessages((prev) => prev.filter((m) => m.id !== errId));
          handleFlowAnswer(question, answerText, true);
        },
      });
    }
  };

  const handleAnswerStep = (question, answerText) => {
    if (question.stage === 'category') return handleCategoryAnswer(question, answerText);
    if (question.stage === 'usage') return handleUsageAnswer(question, answerText);
    return handleFlowAnswer(question, answerText);
  };

  const progress = Math.min(currentStep, totalSteps);

  return (
    <div className="chat-flow">
      <div className="chat-flow__header">
        <div className="chat-flow__progress-label">진행률 {progress}/{totalSteps}</div>
        <div className="chat-flow__progress-bar">
          <div
            className="chat-flow__progress-fill"
            style={{ width: `${(progress / totalSteps) * 100}%` }}
          />
        </div>
      </div>

      <div className="chat-flow__thread">
        {messages.map((m) => (
          <ChatMessage
            key={m.id}
            message={m}
            busy={busy}
            spec={spec}
            onBusinessType={handleBusinessType}
            onAnswer={(text) => handleAnswerStep(m, text)}
            onPhotoResolved={(payload) => handlePhotoResolved(m.id, payload)}
          />
        ))}
        {busy && (
          <div className="chat-row chat-row--bot">
            <Mascot expression="idle" size={CHAT_AVATAR_SIZE} className="chat-row__avatar" />
            <div className="chat-bubble chat-bubble--bot chat-bubble--typing" aria-live="polite">
              <span />
              <span />
              <span />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

function ChatMessage({ message, busy, spec, onBusinessType, onAnswer, onPhotoResolved }) {
  if (message.kind === 'text') {
    return <div className={`chat-bubble chat-bubble--${message.role}`}>{message.text}</div>;
  }

  if (message.kind === 'note') {
    return <div className="chat-flow__note">{message.text}</div>;
  }

  if (message.kind === 'error') {
    return <ErrorNotice message={message.text} onRetry={message.retry} retrying={busy} compact />;
  }

  if (message.kind === 'regulation') {
    return <RegulationNotice regulation={message.regulation} />;
  }

  if (message.kind === 'business_type') {
    return (
      <div className="chat-row chat-row--bot">
        <Mascot expression="idle" size={CHAT_AVATAR_SIZE} className="chat-row__avatar" />
        <div className="chat-bubble chat-bubble--bot">
          <div className="chat-bubble__text">{BUSINESS_TYPE_QUESTION_TEXT}</div>
          {!message.answered && (
            <div className="chat-question__options">
              {BUSINESS_TYPE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  className="chat-question__chip"
                  disabled={busy}
                  onClick={() => onBusinessType(opt.value, opt.label)}
                >
                  <span>{opt.label}</span>
                  <span className="chat-question__chip-description">{opt.description}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  if (message.kind === 'question') {
    return (
      <div className="chat-row chat-row--bot">
        <Mascot expression="idle" size={CHAT_AVATAR_SIZE} className="chat-row__avatar" />
        <div className="chat-bubble chat-bubble--bot">
          <div className="chat-bubble__text">{message.question}</div>
          {message.stage === 'category' && <p className="chat-flow__hint">{CATEGORY_HINT_TEXT}</p>}
          {message.regulation && <RegulationNotice regulation={message.regulation} />}
          {!message.answered && <QuestionCard question={message} busy={busy} onAnswer={onAnswer} />}
        </div>
      </div>
    );
  }

  if (message.kind === 'photo') {
    return (
      <div className="chat-row chat-row--bot">
        <Mascot expression="idle" size={CHAT_AVATAR_SIZE} className="chat-row__avatar" />
        <div className="chat-bubble chat-bubble--bot">
          <div className="chat-bubble__text">
            제품 이미지 업로드 <span className="chat-photo__required-badge">필수</span>
          </div>
          <p className="chat-flow__hint">{PHOTO_GUIDE_TEXT}</p>
          {!message.resolved && <ProductPhotoQuestion spec={spec} onResolved={onPhotoResolved} />}
        </div>
      </div>
    );
  }

  return null;
}

/**
 * 질문 카드 — 질문 종류에 따라 세 변형 중 하나로 렌더링한다. 각 질문은
 * 독립된 카드로 순서대로 나온다(강조점→추가 요청도 별도 카드, 8/11 PM 확인).
 *   - 단일 선택(업종/용도/느낌): 칩 클릭 즉시 제출
 *   - 복수 선택(강조점): 칩 토글 + [다음] 버튼으로 그 질문만 마무리
 *   - 자유 입력(추가 요청): 칩은 텍스트칸을 채울 뿐, [이 내용으로 완료]가 최종 제출
 *
 * 업종/용도는 선택지가 서버 enum과 1:1로 고정돼야 해서(Vision·CopyRequest가
 * 요구하는 값과 어긋나면 안 됨) "기타" 직접입력을 노출하지 않는다
 * (question.noOther — 8/14 스펙: 0단계·용도·product 제품명에는 기타 미적용).
 */
function QuestionCard({ question, busy, onAnswer }) {
  if (question.multiSelect) {
    return <MultiSelectQuestion question={question} busy={busy} onAnswer={onAnswer} />;
  }
  if (question.freeform) {
    return <FreeformQuestion question={question} busy={busy} onAnswer={onAnswer} />;
  }
  return <SingleSelectQuestion question={question} busy={busy} onAnswer={onAnswer} allowOther={!question.noOther} />;
}

function RegulationNotice({ regulation }) {
  const flags = regulation?.flags || [];
  return (
    <div className={`chat-regulation chat-regulation--${regulation?.severity || 'warn'}`} role={regulation?.severity === 'block' ? 'alert' : 'status'}>
      <strong>{regulation?.severity === 'block' ? '수정이 필요해요' : '확인해주세요'}</strong>
      {regulation?.suggestion_text && <p>{regulation.suggestion_text}</p>}
      {flags.map((flag, index) => (
        <p key={`${flag.reason || flag.matched || 'flag'}-${index}`}>
          {flag.reason}{flag.suggestion ? ` · 제안: ${flag.suggestion}` : ''}
        </p>
      ))}
    </div>
  );
}

/** 단일 선택 질문(업종/용도/느낌) — 칩을 클릭하면 그 즉시 답변으로 제출된다. */
function SingleSelectQuestion({ question, busy, onAnswer, allowOther = true }) {
  const [showOther, setShowOther] = useState(false);
  const [otherText, setOtherText] = useState('');

  const submitOther = () => {
    const value = otherText.trim();
    if (!value) return;
    onAnswer(value);
  };

  return (
    <div className="chat-question">
      <div className="chat-question__options">
        {question.options.map((opt) => (
          <button
            key={opt}
            type="button"
            className="chat-question__chip"
            disabled={busy}
            onClick={() => onAnswer(opt)}
          >
            {opt}
          </button>
        ))}
        {allowOther && (
          <button
            type="button"
            className={'chat-question__chip chat-question__chip--other' + (showOther ? ' chat-question__chip--active' : '')}
            disabled={busy}
            onClick={() => setShowOther((v) => !v)}
          >
            기타
          </button>
        )}
      </div>

      {allowOther && showOther && (
        <div className="chat-question__inline-form">
          <input
            type="text"
            value={otherText}
            onChange={(e) => setOtherText(e.target.value)}
            placeholder="직접 입력해주세요"
            disabled={busy}
          />
          <button
            type="button"
            className="chat-question__submit"
            disabled={busy || !otherText.trim()}
            onClick={submitOther}
          >
            이렇게 입력할게요
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * 복수 선택 질문(강조점) — 여러 개 고를 수 있어야 하므로 칩은 토글만 하고,
 * [다음] 버튼을 눌러야 그 질문이 마무리되고 추가 요청 질문으로 넘어간다.
 * "다 골랐어요"처럼 전체 완료 느낌이 아니라 이 질문만 끝내고 계속 진행된다는
 * 느낌으로 문구를 골랐다 — 전체 흐름의 마무리는 추가 요청 쪽 [이 내용으로 완료]가 맡는다.
 */
function MultiSelectQuestion({ question, busy, onAnswer }) {
  const [selected, setSelected] = useState([]);
  const [showOther, setShowOther] = useState(false);
  const [otherText, setOtherText] = useState('');

  const toggleOption = (opt) => {
    setSelected((prev) => (prev.includes(opt) ? prev.filter((o) => o !== opt) : [...prev, opt]));
  };

  // 기타로 직접 입력하면 곧바로 제출하지 않고, 이미 고른 칩들과 함께 선택 목록에
  // 추가만 한다 — 그래야 커스텀 항목 하나 때문에 다른 선택이 날아가지 않는다.
  const addCustom = () => {
    const value = otherText.trim();
    if (!value) return;
    setSelected((prev) => (prev.includes(value) ? prev : [...prev, value]));
    setOtherText('');
    setShowOther(false);
  };

  const submit = () => {
    onAnswer(selected.length ? selected.join(', ') : '특별히 없음');
  };

  return (
    <div className="chat-question">
      <div className="chat-question__options">
        {question.options.map((opt) => (
          <button
            key={opt}
            type="button"
            className={'chat-question__chip' + (selected.includes(opt) ? ' chat-question__chip--active' : '')}
            disabled={busy}
            onClick={() => toggleOption(opt)}
          >
            {opt}
          </button>
        ))}
        <button
          type="button"
          className={'chat-question__chip chat-question__chip--other' + (showOther ? ' chat-question__chip--active' : '')}
          disabled={busy}
          onClick={() => setShowOther((v) => !v)}
        >
          기타
        </button>
      </div>

      {showOther && (
        <div className="chat-question__inline-form">
          <input
            type="text"
            value={otherText}
            onChange={(e) => setOtherText(e.target.value)}
            placeholder="직접 입력해주세요"
            disabled={busy}
          />
          <button
            type="button"
            className="chat-question__submit"
            disabled={busy || !otherText.trim()}
            onClick={addCustom}
          >
            이렇게 추가할게요
          </button>
        </div>
      )}

      <button type="button" className="chat-question__submit chat-question__submit--block" disabled={busy} onClick={submit}>
        다음
      </button>
    </div>
  );
}

/**
 * 서버 input_type=text 질문 — 조건부 후속질문과 마지막 추가요청이 공유한다.
 */
function FreeformQuestion({ question, busy, onAnswer }) {
  const [freeText, setFreeText] = useState('');

  const submit = () => {
    const value = freeText.trim();
    if (value) onAnswer(value);
  };

  const skip = () => onAnswer('건너뛰기');

  return (
    <div className="chat-question">
      <div className="chat-question__inline-form chat-question__inline-form--stacked">
        <input
          type="text"
          value={freeText}
          onChange={(e) => setFreeText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              submit();
            }
          }}
          placeholder="짧게 입력해주세요 (선택 사항)"
          maxLength={question.maxLength || undefined}
          disabled={busy}
        />
        {question.maxLength && <div className="chat-question__counter">{freeText.length} / {question.maxLength}</div>}
        <div className="chat-question__text-actions">
          <button type="button" className="chat-question__skip" disabled={busy} onClick={skip}>건너뛰기</button>
          <button type="button" className="chat-question__submit" disabled={busy || !freeText.trim()} onClick={submit}>제출</button>
        </div>
      </div>
    </div>
  );
}

/**
 * product 4/7 내부 sub-flow — 제품 업로드/확정 후 배경 선택(8/19 확정 UX).
 *
 * 이 화면 하나에서 역할이 다른 두 이미지를 받는다:
 *   - 제품 사진(필수): 기존 그대로 Vision 제품 인식에 쓰인다. 단계는
 *     upload(파일 선택) → analyzing(/vision/product 호출 중) →
 *     result(인식값 확인 — [맞아요]/[수정할게요]) | edit(제품명 직접 보정).
 *     인식 실패(next_action=reupload)는 upload로 되돌아가 같은 단계에 머문다.
 *   - 배경 참고 이미지(선택): 제품 confirm이 끝난 뒤 같은 4/7 카드의 background
 *     phase에서만 선택할 수 있다. 업로드 또는 [배경 없이 진행]을 명시적으로
 *     선택해야 부모 onResolved가 호출되고 5/7 tone으로 넘어간다.
 *
 * Vision은 인식만 수행하며 auto_fill도 자동 진행하지 않는다. [맞아요]는
 * vision_confirmed, 사용자가 이름을 고친 경우는 user_corrected로
 * /vision/product/confirm 응답은 background phase 동안 보관하고, 배경 선택이
 * 끝난 뒤 서버가 반환한 tone 질문으로 진행한다.
 */
function ProductPhotoQuestion({ spec, onResolved }) {
  const fileInputRef = useRef(null);
  const [preview, setPreview] = useState(null);
  const [fileError, setFileError] = useState('');
  const [phase, setPhase] = useState('upload'); // 'upload' | 'analyzing' | 'result' | 'edit' | 'background'
  const [reuploadNote, setReuploadNote] = useState('');
  const [visionError, setVisionError] = useState('');
  const [context, setContext] = useState(null);
  // --- 제품 confirm 후 배경 선택 sub-phase (8/19 확정) -------------------
  const backgroundFileInputRef = useRef(null);
  const [backgroundPreview, setBackgroundPreview] = useState(null);
  const [backgroundFileError, setBackgroundFileError] = useState('');
  const [backgroundFileReading, setBackgroundFileReading] = useState(false);
  const [backgroundVisionBusy, setBackgroundVisionBusy] = useState(false);
  const [confirmedResult, setConfirmedResult] = useState(null);
  const [confirmedProduct, setConfirmedProduct] = useState('');
  // /vision/product 응답의 spec(product_context 포함) — confirm/edit 경로에서
  // 제품명을 확정할 때도 이 spec을 기반으로 써야 auto_fill과 최종 spec 모양이
  // 달라지지 않는다(원래 spec prop에는 product_context가 없다).
  const [visionSpec, setVisionSpec] = useState(null);
  const [editValue, setEditValue] = useState('');
  const [bridgeBusy, setBridgeBusy] = useState(false);
  // 맞아요/수정 확정을 빠르게 두 번 누르면 다음 질문이 중복 추가될 수 있어
  // 동기적으로 즉시 잠그는 ref 가드 — bridgeBusy(상태)는 다음 렌더에야 반영되므로
  // 그 사이의 아주 짧은 창(연속 클릭)까지는 막지 못한다. 실패 시에는 재시도할 수
  // 있어야 하므로 catch에서 다시 풀어준다.
  const actionLockRef = useRef(false);
  const backgroundActionLockRef = useRef(false);

  const handleFile = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileError('');
    setReuploadNote('');

    if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
      setFileError('PNG, JPEG, WebP 형식의 사진만 업로드할 수 있어요.');
      e.target.value = '';
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      setFileError('사진 용량이 너무 커요. 8MB 이하의 사진으로 올려주세요.');
      e.target.value = '';
      return;
    }

    const reader = new FileReader();
    reader.onload = () => setPreview(reader.result);
    reader.readAsDataURL(file);
  };

  const finishBackgroundSelection = (nextSpec, bgRef = null, backgroundWarning = '') => {
    onResolved({
      image: preview,
      backgroundReference: bgRef,
      spec: nextSpec,
      suggestion: confirmedResult,
      backgroundWarning,
    });
  };

  const analyzeBackground = async (imageDataUrl) => {
    setBackgroundVisionBusy(true);
    try {
      const backgroundRes = await visionBackground({ imageDataUrl, spec: confirmedResult.spec });
      const backgroundContext = backgroundRes.meta?.spec?.background_context;
      if (
        backgroundRes.context?.usable === true &&
        backgroundContext &&
        typeof backgroundContext === 'object' &&
        !Array.isArray(backgroundContext)
      ) {
        finishBackgroundSelection(
          { ...confirmedResult.spec, background_context: backgroundContext },
          imageDataUrl,
        );
        return;
      }
      const { background_context: _staleContext, ...specWithoutBackground } = confirmedResult.spec;
      finishBackgroundSelection(
        specWithoutBackground,
        imageDataUrl,
        '배경 참고 이미지는 적용하기 어려워 제외했어요. 제품 광고는 그대로 진행할게요.',
      );
    } catch {
      const { background_context: _staleContext, ...specWithoutBackground } = confirmedResult.spec;
      finishBackgroundSelection(
        specWithoutBackground,
        imageDataUrl,
        '배경 참고 이미지 분석에 실패해 배경 없이 진행할게요.',
      );
    }
  };

  // 파일 선택 직후 FileReader를 완료한 다음 background Vision을 한 번만 호출한다.
  const handleBackgroundFile = (e) => {
    const file = e.target.files?.[0];
    if (!file || backgroundActionLockRef.current) return;
    backgroundActionLockRef.current = true;
    setBackgroundFileError('');

    if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
      setBackgroundFileError('PNG, JPEG, WebP 형식의 사진만 업로드할 수 있어요.');
      e.target.value = '';
      backgroundActionLockRef.current = false;
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      setBackgroundFileError('사진 용량이 너무 커요. 8MB 이하의 사진으로 올려주세요.');
      e.target.value = '';
      backgroundActionLockRef.current = false;
      return;
    }

    setBackgroundFileReading(true);
    const reader = new FileReader();
    reader.onload = async () => {
      const imageDataUrl = reader.result;
      setBackgroundPreview(imageDataUrl);
      setBackgroundFileReading(false);
      await analyzeBackground(imageDataUrl);
    };
    reader.onerror = () => {
      backgroundActionLockRef.current = false;
      setBackgroundFileReading(false);
      setBackgroundFileError('사진을 불러오지 못했어요. 다시 시도해주세요.');
    };
    reader.readAsDataURL(file);
  };

  const proceedWithoutBackground = () => {
    if (!confirmedResult || backgroundActionLockRef.current) return;
    backgroundActionLockRef.current = true;
    const { background_context: _staleContext, ...specWithoutBackground } = confirmedResult.spec;
    finishBackgroundSelection(specWithoutBackground);
  };

  const analyze = async () => {
    if (!preview) return;
    setPhase('analyzing');
    setVisionError('');
    try {
      const res = await visionProduct({ imageDataUrl: preview, spec });
      if (res.context.next_action === 'reupload') {
        actionLockRef.current = false;
        backgroundActionLockRef.current = false;
        setConfirmedResult(null);
        setConfirmedProduct('');
        setBackgroundPreview(null);
        setBackgroundFileError('');
        setBackgroundFileReading(false);
        setBackgroundVisionBusy(false);
        setPhase('upload');
        setPreview(null);
        // input의 value도 함께 비워야 같은 파일을 다시 선택했을 때도 브라우저가
        // change 이벤트를 다시 발생시킨다(동일 파일이면 value가 안 바뀌어 change가
        // 안 일어남) — preview만 초기화하면 재선택이 씹힌다.
        if (fileInputRef.current) fileInputRef.current.value = '';
        setReuploadNote('제품을 인식하지 못했어요. 다른 사진으로 다시 시도해주세요.');
        return;
      }
      setContext(res.context);
      // auto_fill/confirm/reupload 어느 경로든 최종 spec 모양이 같아야 하므로
      // (product_context 포함) 여기서 항상 보존해둔다 — confirm/edit 확정 시
      // 이 spec을 기반으로 쓴다(원래 spec prop에는 product_context가 없음).
      setVisionSpec(res.spec);
      if (res.context.product) {
        setPhase('result');
      } else {
        // ambiguous라 후보 이름이 없는 경우 — 확인 단계 없이 바로 보정 입력으로 안내
        setEditValue('');
        setPhase('edit');
      }
    } catch (err) {
      setPhase('upload');
      setVisionError(toFriendlyMessage(err, 'vision'));
    }
  };

  // 사용자 확정 뒤에는 tone으로 가지 않고 같은 4/7의 배경 선택 phase에 머문다.
  const submitProductName = async (name, confirmationSource = 'user_corrected') => {
    const trimmed = (name || '').trim();
    if (!trimmed || actionLockRef.current) return;
    actionLockRef.current = true;
    setBridgeBusy(true);
    setVisionError('');
    try {
      const res = await confirmProduct({
        confirmedProduct: trimmed,
        confirmationSource,
        spec: visionSpec || spec,
      });
      setConfirmedResult(res);
      setConfirmedProduct(trimmed);
      setBridgeBusy(false);
      setPhase('background');
    } catch (err) {
      actionLockRef.current = false;
      setBridgeBusy(false);
      setVisionError(toFriendlyMessage(err, 'productConfirm'));
    }
  };

  const confirmRecognized = () => {
    if (actionLockRef.current) return;
    submitProductName(context?.product, 'vision_confirmed');
  };

  const openEdit = () => {
    setEditValue(context?.product || '');
    setPhase('edit');
  };

  const isAnalyzing = phase === 'analyzing';

  return (
    <div className="chat-photo">
      {(phase === 'upload' || phase === 'analyzing') && (
        <>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            hidden
            onChange={handleFile}
            disabled={isAnalyzing}
          />

          {preview && <img className="chat-photo__preview" src={preview} alt="업로드한 제품 사진 미리보기" />}
          {reuploadNote && <p className="chat-photo__reupload-note">{reuploadNote}</p>}
          {fileError && <p className="chat-photo__error-text">{fileError}</p>}
          {visionError && <ErrorNotice message={visionError} onRetry={analyze} retrying={isAnalyzing} compact />}

          <div className="chat-photo__actions">
            <button
              type="button"
              className="chat-question__chip"
              disabled={isAnalyzing}
              onClick={() => fileInputRef.current?.click()}
            >
              {preview ? '다시 선택' : '이미지 업로드'}
            </button>
            <button
              type="button"
              className="chat-question__submit"
              disabled={!preview || isAnalyzing}
              onClick={analyze}
            >
              {isAnalyzing ? '인식하는 중…' : '사진 확인하기'}
            </button>
          </div>
        </>
      )}

      {phase === 'result' && context && (
        <div className="chat-vision-result">
          {preview && <img className="chat-photo__preview" src={preview} alt="업로드한 제품 사진 미리보기" />}
          <p className="chat-vision-result__label">제품을 이렇게 인식했어요!</p>
          <p className="chat-vision-result__name">{context.product}</p>
          <div className="chat-photo__actions">
            <button
              type="button"
              className="chat-question__submit"
              disabled={bridgeBusy}
              onClick={confirmRecognized}
            >
              맞아요
            </button>
            <button type="button" className="chat-question__chip" disabled={bridgeBusy} onClick={openEdit}>
              수정할게요
            </button>
          </div>
          {visionError && <ErrorNotice message={visionError} onRetry={confirmRecognized} retrying={bridgeBusy} compact />}
        </div>
      )}

      {phase === 'edit' && (
        <div className="chat-vision-edit">
          {!context?.product && (
            <p className="chat-vision-result__label">제품 종류를 정확히 파악하지 못했어요. 제품명을 알려주세요.</p>
          )}
          {context?.candidates?.length > 0 && (
            <div className="chat-question__options">
              {context.candidates.map((c) => (
                <button key={c} type="button" className="chat-question__chip" onClick={() => setEditValue(c)}>
                  {c}
                </button>
              ))}
            </div>
          )}
          <div className="chat-question__inline-form">
            <input
              type="text"
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              placeholder="제품명을 입력해주세요"
              disabled={bridgeBusy}
            />
            <button
              type="button"
              className="chat-question__submit"
              disabled={bridgeBusy || !editValue.trim()}
              onClick={() => submitProductName(editValue)}
            >
              이 이름으로 확정할게요
            </button>
          </div>
          {visionError && (
            <ErrorNotice message={visionError} onRetry={() => submitProductName(editValue)} retrying={bridgeBusy} compact />
          )}
        </div>
      )}

      {phase === 'background' && confirmedResult && <div className="chat-photo__section">
        <p className="chat-photo__confirmed">✓ 제품 확인 완료 — {confirmedProduct}</p>
        <div className="chat-photo__section-header">
          <span className="chat-photo__section-title">{BACKGROUND_REFERENCE_LABEL}</span>
          <span className="chat-photo__optional-badge">선택</span>
        </div>
        <p className="chat-flow__hint">{BACKGROUND_REFERENCE_GUIDE_TEXT}</p>

        <input
          ref={backgroundFileInputRef}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          hidden
          onChange={handleBackgroundFile}
          disabled={backgroundFileReading || backgroundVisionBusy}
        />

        {backgroundFileReading && <p className="chat-flow__hint">이미지를 불러오는 중…</p>}
        {backgroundVisionBusy && <p className="chat-flow__hint">배경을 분석하는 중…</p>}
        {backgroundPreview && !backgroundFileReading && (
          <img
            className="chat-photo__preview chat-photo__preview--background"
            src={backgroundPreview}
            alt="업로드한 배경 참고 이미지 미리보기"
          />
        )}
        {backgroundFileError && <p className="chat-photo__error-text">{backgroundFileError}</p>}

        <div className="chat-photo__actions">
          <button
            type="button"
            className="chat-question__chip"
            disabled={backgroundFileReading || backgroundVisionBusy}
            onClick={() => backgroundFileInputRef.current?.click()}
          >
            이미지 업로드
          </button>
          <button
            type="button"
            className="chat-question__submit"
            disabled={backgroundFileReading || backgroundVisionBusy}
            onClick={proceedWithoutBackground}
          >
            배경 없이 진행
          </button>
        </div>
      </div>}
    </div>
  );
}

export default ChatFlow;
