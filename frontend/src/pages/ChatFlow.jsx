import { useEffect, useRef, useState } from 'react';
import { INITIAL_QUESTION, TOTAL_STEPS, generateCopy, suggestOptions } from '../api/copyApi';
import './ChatFlow.css';

/**
 * 화면 A — 챗봇 진행 화면
 * 6단계 질문을 순서대로 진행하고(2번=용도→비율 매핑, 3번 직후 제품 사진 업로드
 * 여부를 물어 mode(inpaint/text2img) 결정). (docs/UIUX_스펙정리.md 4장 참고)
 *
 * 로딩 디테일/재시도/에러 UI는 다음 단계 고도화 스코프 — 이번엔 뼈대만 구현.
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
    const result = await generateCopy(finalSpec);
    setBusy(false);
    onComplete({ spec: finalSpec, mode, productImage, result });
  };

  const handleAnswerStep = async (question, answerText) => {
    setMessages((prev) => prev.map((m) => (m.id === question.id ? { ...m, answered: true } : m)));
    addMessage({ id: uid(), role: 'user', kind: 'text', text: answerText });

    setBusy(true);
    const res = await suggestOptions({ message: answerText, step: question.step, spec });
    setBusy(false);
    setSpec(res.spec);

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

  const progress = Math.min(currentStep, TOTAL_STEPS);

  return (
    <div className="chat-flow">
      <div className="chat-flow__header">
        <div className="chat-flow__progress-label">진행률 {progress}/{TOTAL_STEPS}</div>
        <div className="chat-flow__progress-bar">
          <div
            className="chat-flow__progress-fill"
            style={{ width: `${(progress / TOTAL_STEPS) * 100}%` }}
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
          <div className="chat-bubble chat-bubble--bot chat-bubble--typing" aria-live="polite">
            <span />
            <span />
            <span />
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

  if (message.kind === 'question') {
    return (
      <div className="chat-bubble chat-bubble--bot">
        <div className="chat-bubble__text">{message.question}</div>
        {!message.answered && <QuestionCard question={message} busy={busy} onAnswer={onAnswer} />}
      </div>
    );
  }

  if (message.kind === 'photo') {
    return (
      <div className="chat-bubble chat-bubble--bot">
        <div className="chat-bubble__text">제품 사진이 있으신가요?</div>
        <p className="chat-flow__hint">있으면 사진을 살려서, 없으면 새로 만들어드려요.</p>
        {!message.resolved && <PhotoStep busy={busy} onConfirm={onPhotoConfirm} />}
      </div>
    );
  }

  return null;
}

function QuestionCard({ question, busy, onAnswer }) {
  const [selected, setSelected] = useState([]);
  const [showOther, setShowOther] = useState(false);
  const [otherText, setOtherText] = useState('');
  const [freeText, setFreeText] = useState('');

  const toggleOption = (opt) => {
    if (question.multiSelect) {
      setSelected((prev) => (prev.includes(opt) ? prev.filter((o) => o !== opt) : [...prev, opt]));
    } else {
      onAnswer(opt);
    }
  };

  const submitOther = () => {
    const value = otherText.trim();
    if (!value) return;
    onAnswer(value);
  };

  const submitMulti = () => {
    onAnswer(selected.length ? selected.join(', ') : '특별히 없음');
  };

  const submitFree = () => {
    onAnswer(freeText.trim() || '특별히 없어요');
  };

  return (
    <div className="chat-question">
      <div className="chat-question__options">
        {question.options.map((opt) => (
          <button
            key={opt}
            type="button"
            className={
              'chat-question__chip' +
              (question.multiSelect && selected.includes(opt) ? ' chat-question__chip--active' : '')
            }
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
            onClick={submitOther}
          >
            이렇게 입력할게요
          </button>
        </div>
      )}

      {question.multiSelect && (
        <button type="button" className="chat-question__submit chat-question__submit--block" disabled={busy} onClick={submitMulti}>
          다 골랐어요
        </button>
      )}

      {question.freeform && (
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
            onClick={submitFree}
          >
            이 내용으로 완료
          </button>
        </div>
      )}
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
