import { useEffect, useRef, useState } from 'react';
import { INITIAL_QUESTION, TOTAL_STEPS, generateCopy, suggestOptions } from '../api/copyApi';
import { toFriendlyMessage } from '../api/mockUtils';
import ErrorNotice from '../components/ErrorNotice';
import Mascot from '../components/Mascot';
import './ChatFlow.css';

// 챗봇 말풍선 옆 아바타 크기(카카오톡 프로필 사진 정도의 작은 크기)
const CHAT_AVATAR_SIZE = 36;

/**
 * 화면 A — 챗봇 진행 화면
 * 6단계 질문을 순서대로 하나씩 진행한다(2번=용도→비율 매핑, 3번 직후 제품 사진
 * 업로드 여부를 물어 mode(inpaint/text2img) 결정). (docs/UIUX_스펙정리.md 4장 참고)
 *
 * 강조점(복수 선택)과 추가 요청(자유 입력)은 각각 독립된 질문 카드로 순서대로
 * 나온다(8/11 PM 확인 — 한 화면에 합치지 않음). 강조점은 여러 개 고를 수 있어야
 * 하므로 [다음] 버튼으로 그 질문만 마무리하고 추가 요청으로 넘어가며(완료가 아닌
 * "계속 진행" 느낌), 추가 요청은 [이 내용으로 완료] 버튼이 전체 흐름의 최종 마무리다.
 *
 * /suggest/options, /generate/copy 호출이 실패하면 말풍선 자리에 에러 카드를
 * 띄우고 "다시 시도"를 누르면 같은 요청을 다시 보낸다(mock 실패 재현은
 * api/mockUtils.js 참고).
 */
function ChatFlow({ onComplete }) {
  const [messages, setMessages] = useState([
    {
      id: 'q1',
      role: 'bot',
      kind: 'question',
      step: INITIAL_QUESTION.step,
      question: INITIAL_QUESTION.question,
      options: INITIAL_QUESTION.options,
      multiSelect: INITIAL_QUESTION.multiSelect,
      freeform: INITIAL_QUESTION.freeform,
      answered: false,
    },
  ]);
  const [spec, setSpec] = useState({});
  const [mode, setMode] = useState(null); // 'inpaint' | 'text2img' — 나중에 포스터 API 호출 시 필요
  const [productImage, setProductImage] = useState(null);
  const [currentStep, setCurrentStep] = useState(1);
  // 진행률 n/총단계는 서버 응답의 total_steps를 그대로 따른다 — 단계 수가 나중에
  // 바뀌어도 프론트 수정 없이 맞춰지도록 하드코딩하지 않는다. 첫 질문은 API 호출 전
  // 프론트에 고정돼 있어 INITIAL_QUESTION.total_steps를 초기값으로 쓴다.
  const [totalSteps, setTotalSteps] = useState(INITIAL_QUESTION.total_steps || TOTAL_STEPS);
  const [busy, setBusy] = useState(false);

  const idRef = useRef(0);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages]);

  const uid = () => `m${++idRef.current}`;
  const addMessage = (msg) => setMessages((prev) => [...prev, msg]);

  const pushQuestion = (res) => {
    addMessage({
      id: uid(),
      role: 'bot',
      kind: 'question',
      step: res.next_step,
      question: res.question,
      options: res.options,
      multiSelect: res.multiSelect,
      freeform: res.freeform,
      answered: false,
    });
    setCurrentStep(res.next_step);
  };

  const finishChat = async (finalSpec) => {
    setBusy(true);
    addMessage({ id: uid(), role: 'bot', kind: 'note', text: '제공해주신 정보를 바탕으로 문구를 만들고 있어요…' });
    try {
      const result = await generateCopy(finalSpec);
      setBusy(false);
      onComplete({ spec: finalSpec, mode, productImage, result });
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

  const runSuggestOptions = async (question, answerText) => {
    setBusy(true);
    try {
      const res = await suggestOptions({ message: answerText, step: question.step, spec });
      setBusy(false);
      setSpec(res.spec);
      if (typeof res.total_steps === 'number') setTotalSteps(res.total_steps);

      if (res.confirm_message) {
        addMessage({ id: uid(), role: 'bot', kind: 'note', text: res.confirm_message });
      }

      // 3번 질문(제품/가게) 답변 직후엔 사진 업로드 여부부터 물어본다.
      if (question.step === 3) {
        addMessage({ id: uid(), role: 'bot', kind: 'photo', resolved: false, pendingResult: res });
        return;
      }

      if (res.done) {
        await finishChat(res.spec);
        return;
      }

      pushQuestion(res);
    } catch (err) {
      setBusy(false);
      const errId = uid();
      addMessage({
        id: errId,
        role: 'bot',
        kind: 'error',
        text: toFriendlyMessage(err, 'options'),
        retry: () => {
          setMessages((prev) => prev.filter((m) => m.id !== errId));
          runSuggestOptions(question, answerText);
        },
      });
    }
  };

  const handleAnswerStep = async (question, answerText) => {
    setMessages((prev) => prev.map((m) => (m.id === question.id ? { ...m, answered: true } : m)));
    addMessage({ id: uid(), role: 'user', kind: 'text', text: answerText });
    await runSuggestOptions(question, answerText);
  };

  const handlePhotoConfirm = (photoMsg, { mode: chosenMode, image }) => {
    setMode(chosenMode);
    setProductImage(image);
    setMessages((prev) => prev.map((m) => (m.id === photoMsg.id ? { ...m, resolved: true } : m)));
    addMessage({
      id: uid(),
      role: 'user',
      kind: 'text',
      text: chosenMode === 'inpaint' ? '제품 사진을 업로드했어요.' : '사진 없이 진행할게요.',
    });

    const res = photoMsg.pendingResult;
    if (res.done) {
      finishChat(res.spec);
    } else {
      pushQuestion(res);
    }
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
            onAnswer={(text) => handleAnswerStep(m, text)}
            onPhotoConfirm={(payload) => handlePhotoConfirm(m, payload)}
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

function ChatMessage({ message, busy, onAnswer, onPhotoConfirm }) {
  if (message.kind === 'text') {
    return <div className={`chat-bubble chat-bubble--${message.role}`}>{message.text}</div>;
  }

  if (message.kind === 'note') {
    return <div className="chat-flow__note">{message.text}</div>;
  }

  if (message.kind === 'error') {
    return <ErrorNotice message={message.text} onRetry={message.retry} retrying={busy} compact />;
  }

  if (message.kind === 'question') {
    return (
      <div className="chat-row chat-row--bot">
        <Mascot expression="idle" size={CHAT_AVATAR_SIZE} className="chat-row__avatar" />
        <div className="chat-bubble chat-bubble--bot">
          <div className="chat-bubble__text">{message.question}</div>
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
          <div className="chat-bubble__text">제품 사진이 있으신가요?</div>
          <p className="chat-flow__hint">있으면 사진을 살려서, 없으면 새로 만들어드려요.</p>
          {!message.resolved && <PhotoStep busy={busy} onConfirm={onPhotoConfirm} />}
        </div>
      </div>
    );
  }

  return null;
}

/**
 * 질문 카드 — 질문 종류에 따라 세 변형 중 하나로 렌더링한다. 각 질문은
 * 독립된 카드로 순서대로 나온다(강조점→추가 요청도 별도 카드, 8/11 PM 확인).
 *   - 단일 선택(업종/용도/제품/느낌): 칩 클릭 즉시 제출
 *   - 복수 선택(강조점): 칩 토글 + [다음] 버튼으로 그 질문만 마무리
 *   - 자유 입력(추가 요청): 칩은 텍스트칸을 채울 뿐, [이 내용으로 완료]가 최종 제출
 */
function QuestionCard({ question, busy, onAnswer }) {
  if (question.multiSelect) {
    return <MultiSelectQuestion question={question} busy={busy} onAnswer={onAnswer} />;
  }
  if (question.freeform) {
    return <FreeformQuestion question={question} busy={busy} onAnswer={onAnswer} />;
  }
  return <SingleSelectQuestion question={question} busy={busy} onAnswer={onAnswer} />;
}

/** 단일 선택 질문(업종/용도/제품/느낌) — 칩을 클릭하면 그 즉시 답변으로 제출된다. */
function SingleSelectQuestion({ question, busy, onAnswer }) {
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
 * 자유 입력 질문(추가 요청) — 이 흐름의 마지막 질문. 선택지 칩은 눌러도 바로
 * 제출되지 않고 텍스트칸을 채우기만 한다 — 실제 제출은 [이 내용으로 완료]
 * 버튼을 눌러야만 일어난다.
 */
function FreeformQuestion({ question, busy, onAnswer }) {
  const [freeText, setFreeText] = useState('');

  const submit = () => {
    onAnswer(freeText.trim() || '특별히 없어요');
  };

  return (
    <div className="chat-question">
      <div className="chat-question__options">
        {question.options.map((opt) => (
          <button
            key={opt}
            type="button"
            className={'chat-question__chip' + (freeText === opt ? ' chat-question__chip--active' : '')}
            disabled={busy}
            onClick={() => setFreeText(opt)}
          >
            {opt}
          </button>
        ))}
      </div>

      <div className="chat-question__inline-form chat-question__inline-form--stacked">
        <textarea
          value={freeText}
          onChange={(e) => setFreeText(e.target.value)}
          placeholder="자유롭게 남겨주세요 (선택 사항)"
          rows={2}
          disabled={busy}
        />
        <button
          type="button"
          className="chat-question__submit chat-question__submit--block"
          disabled={busy}
          onClick={submit}
        >
          이 내용으로 완료
        </button>
      </div>
    </div>
  );
}

function PhotoStep({ busy, onConfirm }) {
  const fileInputRef = useRef(null);
  const [preview, setPreview] = useState(null);

  const handleFile = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setPreview(reader.result);
    reader.readAsDataURL(file);
  };

  return (
    <div className="chat-photo">
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        hidden
        onChange={handleFile}
        disabled={busy}
      />

      {preview && (
        <img className="chat-photo__preview" src={preview} alt="업로드한 제품 사진 미리보기" />
      )}

      <div className="chat-photo__actions">
        <button type="button" className="chat-question__chip" disabled={busy} onClick={() => fileInputRef.current?.click()}>
          {preview ? '다시 선택' : '사진 업로드'}
        </button>
        {preview ? (
          <button
            type="button"
            className="chat-question__submit"
            disabled={busy}
            onClick={() => onConfirm({ mode: 'inpaint', image: preview })}
          >
            이 사진으로 계속하기
          </button>
        ) : (
          <button
            type="button"
            className="chat-question__chip"
            disabled={busy}
            onClick={() => onConfirm({ mode: 'text2img', image: null })}
          >
            사진 없이 진행하기
          </button>
        )}
      </div>
    </div>
  );
}

export default ChatFlow;
