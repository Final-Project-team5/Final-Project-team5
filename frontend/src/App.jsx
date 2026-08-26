import { useEffect, useState } from 'react';
import Sidebar from './components/Sidebar';
import Home from './pages/Home';
import ChatFlow from './pages/ChatFlow';
import CopyResult from './pages/CopyResult';
import DraftSelect from './pages/DraftSelect';
import PosterEditor from './pages/PosterEditor';
import FinalResult from './pages/FinalResult';
import FaqPage from './pages/FaqPage';
import { getPosterCategory, planDesignPrompt } from './api/posterApi';
import { REG_TIPS } from './constants/regulationTips';
import './App.css';

const REG_TIP_INTERVAL_MS = 4800;
const REG_TIP_FADE_MS = 350;

// URL과 view 상태를 맞추는 최소한의 매핑. 라우팅 라이브러리 없이 History API만으로
// /faq 하나만 실제 주소를 갖게 한다 — 나머지 흐름 화면은 지금처럼 URL 변경 없이
// view 상태로만 전환된다(서버가 stateless라 새로고침 시 흐름 state 자체가 유지되지
// 않으므로, 그 화면들까지 새로고침 가능한 URL로 만드는 건 의미가 없다).
const pathToView = (pathname) => (pathname === '/faq' ? 'faq' : 'home');

function App() {
  // 'home' | 'chat' | 'result' | 'drafts' | 'poster' | 'final' | 'faq'
  const [view, setView] = useState(() => pathToView(window.location.pathname));
  // { spec, mode, productImage, backgroundReference, result } — backgroundReference는
  // product 사진 단계(선택)에서 올린 배경 참고 이미지. 확정된 poster API 계약이
  // 없어 아직 어떤 화면/요청에도 실제 전달하지 않는다(posterApi.js 상단 doc 참고).
  const [chatOutcome, setChatOutcome] = useState(null);
  const [confirmedCopy, setConfirmedCopy] = useState(null); // { headline, sub } — 화면 B에서 확정
  // { id, image, seed, background } — 화면 C에서 선택. 서버가 stateless라 image(base64)와
  // background를 화면 D(refine 호출)에서 draft_image/background로 그대로 재전송해야 한다.
  const [selectedDraft, setSelectedDraft] = useState(null);
  const [refineResult, setRefineResult] = useState(null); // 화면 D에서 완성한 최종 결과(mock)
  const [regTipIndex, setRegTipIndex] = useState(0);
  const [regTipVisible, setRegTipVisible] = useState(true);
  // ChatFlow를 강제로 리마운트시키기 위한 key. view가 이미 'chat'인 상태(챗봇
  // 진행 중)에서 사이드바 "새로 만들기"를 다시 누르면 setView('chat')이
  // 동일 값 재설정이라 React가 리렌더를 스킵해 ChatFlow가 리마운트되지
  // 않고 messages/spec/productImage/backgroundReference 등 내부 state가 그대로
  // 남는 문제가 있었다. newFlow()마다 이 값을 증가시켜 key={chatKey}로 넘기면
  // view 값이 바뀌지 않아도 매번 새 ChatFlow 인스턴스로 강제 교체된다.
  const [chatKey, setChatKey] = useState(0);
  // 사이드바 진행 스텝은 /faq를 보는 중에도 직전 흐름 단계를 그대로 보여줘야 하므로,
  // faq가 아닌 마지막 view를 별도로 기억해둔다.
  const [lastFlowView, setLastFlowView] = useState('home');

  useEffect(() => {
    if (view !== 'faq') setLastFlowView(view);
  }, [view]);

  // 브라우저 뒤로/앞으로 가기로 /faq ↔ 그 외 주소를 오갈 때도 view를 맞춘다.
  // /faq가 아닌 쪽으로 돌아올 땐 무조건 'home'이 아니라 lastFlowView로 복원해야
  // 흐름 중간(예: poster)에 FAQ를 봤다가 뒤로가기를 눌러도 그 자리로 돌아온다.
  // (lastFlowView를 deps에 넣어 매번 최신값을 읽는 클로저로 다시 등록한다.)
  useEffect(() => {
    const onPopState = () => {
      setView(window.location.pathname === '/faq' ? 'faq' : lastFlowView);
    };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, [lastFlowView]);

  // 이미 같은 경로면 중복 history 엔트리를 쌓지 않는다.
  const syncUrl = (path) => {
    if (window.location.pathname !== path) window.history.pushState(null, '', path);
  };

  // 사이드바 "오늘의 상식" 카드 페이드 인/아웃 순환
  useEffect(() => {
    const timer = setInterval(() => {
      setRegTipVisible(false);
      setTimeout(() => {
        setRegTipIndex((prev) => (prev + 1) % REG_TIPS.length);
        setRegTipVisible(true);
      }, REG_TIP_FADE_MS);
    }, REG_TIP_INTERVAL_MS);
    return () => clearInterval(timer);
  }, []);

  const goHome = () => {
    syncUrl('/');
    setView('home');
    setChatOutcome(null);
    setConfirmedCopy(null);
    setSelectedDraft(null);
    setRefineResult(null);
  };
  const newFlow = () => {
    syncUrl('/');
    setChatOutcome(null);
    setConfirmedCopy(null);
    setSelectedDraft(null);
    setRefineResult(null);
    setChatKey((k) => k + 1); // 이미 'chat' 화면이어도 ChatFlow를 강제 리마운트
    setView('chat');
  };
  // FAQ는 흐름 상태를 건드리지 않는다 — 어느 화면에서 보든 그대로 돌아올 수 있게.
  const goFaq = () => {
    syncUrl('/faq');
    setView('faq');
  };
  const handleChatComplete = (outcome) => {
    setChatOutcome(outcome);
    setView('result');
  };
  const handleCopyConfirmed = (copy) => {
    setConfirmedCopy(copy);
    setView('drafts');
  };
  const handleDraftBack = () => setView('result');
  const handleDraftConfirmed = (draft) => {
    setSelectedDraft(draft);
    setView('poster');
  };
  const handlePosterBack = () => setView('drafts');
  const handlePosterComplete = (result) => {
    setRefineResult(result);
    setView('final');
  };

  return (
    <div className="app">
      <Sidebar
        regTip={REG_TIPS[regTipIndex]}
        regTipVisible={regTipVisible}
        currentView={view === 'faq' ? lastFlowView : view}
        onGoHome={goHome}
        onNewFlow={newFlow}
        onGoFaq={goFaq}
      />
      <main className="app__main">
        {view === 'home' && <Home onNewFlow={newFlow} />}
        {view === 'faq' && <FaqPage />}
        {view === 'chat' && <ChatFlow key={chatKey} onComplete={handleChatComplete} />}
        {view === 'result' && chatOutcome && (
          <CopyResult
            result={chatOutcome.result}
            spec={chatOutcome.spec}
            onConfirm={handleCopyConfirmed}
            onRestart={goHome}
          />
        )}
        {view === 'drafts' && chatOutcome && (
          <DraftSelect
            mode={chatOutcome.mode}
            productImage={chatOutcome.productImage}
            spec={chatOutcome.spec}
            onConfirm={handleDraftConfirmed}
            onBack={handleDraftBack}
          />
        )}
        {view === 'poster' && chatOutcome && selectedDraft && confirmedCopy && (
          <PosterEditor
            draftImage={selectedDraft.image}
            background={selectedDraft.background}
            originalImage={chatOutcome.productImage}
            prompt={planDesignPrompt(chatOutcome.spec)}
            category={getPosterCategory(chatOutcome.spec)}
            ratio={chatOutcome.spec?.aspect_ratio}
            // PosterEditor는 spec을 통째로 받지 않으므로 여기서 변환해 넘긴다.
            // refine도 서버에서 resolve_prompt()를 다시 타기 때문에 필요하다.
            subjectKind={chatOutcome.spec?.business_type === 'service' ? 'service' : 'product'}
            headline={confirmedCopy.headline}
            sub={confirmedCopy.sub}
            onComplete={handlePosterComplete}
            onBack={handlePosterBack}
          />
        )}
        {view === 'final' && refineResult && confirmedCopy && (
          <FinalResult
            image={refineResult.image}
            ratio={chatOutcome?.spec?.aspect_ratio}
            headline={confirmedCopy.headline}
            sub={confirmedCopy.sub}
            status={confirmedCopy.status}
            onRestart={goHome}
          />
        )}
      </main>
    </div>
  );
}

export default App;
