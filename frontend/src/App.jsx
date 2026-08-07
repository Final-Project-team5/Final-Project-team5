import { useEffect, useState } from 'react';
import Sidebar from './components/Sidebar';
import Home from './pages/Home';
import ChatFlow from './pages/ChatFlow';
import CopyResult from './pages/CopyResult';
import DraftSelect from './pages/DraftSelect';
import PosterEditor from './pages/PosterEditor';
import { buildPrompt } from './api/posterApi';
import { REG_TIPS } from './constants/regulationTips';
import './App.css';

const REG_TIP_INTERVAL_MS = 4800;
const REG_TIP_FADE_MS = 350;

function App() {
  // 'home' | 'chat' | 'result' | 'drafts' | 'poster' | 'next'
  // 'next' = 최종 결과 화면(화면 E) 자리 — 아직 미구현, 버튼만 연결
  const [view, setView] = useState('home');
  const [chatOutcome, setChatOutcome] = useState(null); // { spec, mode, productImage, result }
  const [confirmedCopy, setConfirmedCopy] = useState(null); // { headline, sub } — 화면 B에서 확정
  // { id, image, seed, background } — 화면 C에서 선택. 서버가 stateless라 image(base64)와
  // background를 화면 D(refine 호출)에서 draft_image/background로 그대로 재전송해야 한다.
  const [selectedDraft, setSelectedDraft] = useState(null);
  const [refineResult, setRefineResult] = useState(null); // 화면 D에서 완성한 최종 결과(mock)
  const [regTipIndex, setRegTipIndex] = useState(0);
  const [regTipVisible, setRegTipVisible] = useState(true);

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
    setView('home');
    setChatOutcome(null);
    setConfirmedCopy(null);
    setSelectedDraft(null);
    setRefineResult(null);
  };
  const newFlow = () => {
    setChatOutcome(null);
    setConfirmedCopy(null);
    setSelectedDraft(null);
    setRefineResult(null);
    setView('chat');
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
  // TODO: 화면 E(최종 결과) 구현 후 실제 흐름으로 연결
  const handlePosterComplete = (result) => {
    setRefineResult(result);
    setView('next');
  };

  return (
    <div className="app">
      <Sidebar
        regTip={REG_TIPS[regTipIndex]}
        regTipVisible={regTipVisible}
        onGoHome={goHome}
        onNewFlow={newFlow}
      />
      <main className="app__main">
        {view === 'home' && <Home onNewFlow={newFlow} />}
        {view === 'chat' && <ChatFlow onComplete={handleChatComplete} />}
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
            prompt={buildPrompt(chatOutcome.spec)}
            headline={confirmedCopy.headline}
            sub={confirmedCopy.sub}
            onComplete={handlePosterComplete}
            onBack={handlePosterBack}
          />
        )}
        {view === 'next' && (
          <div className="app__placeholder">
            <div>
              최종 결과 화면(화면 E)은 다음 단계에서 구현될 예정입니다.
              {confirmedCopy && (
                <>
                  <br />
                  확정 문구: “{confirmedCopy.headline}”
                </>
              )}
            </div>
            {refineResult && (
              <img className="app__placeholder-thumb" src={refineResult.image} alt="완성된 포스터" />
            )}
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
