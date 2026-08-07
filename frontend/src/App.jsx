import { useEffect, useState } from 'react';
import Sidebar from './components/Sidebar';
import Home from './pages/Home';
import ChatFlow from './pages/ChatFlow';
import CopyResult from './pages/CopyResult';
import DraftSelect from './pages/DraftSelect';
import { REG_TIPS } from './constants/regulationTips';
import './App.css';

const REG_TIP_INTERVAL_MS = 4800;
const REG_TIP_FADE_MS = 350;

function App() {
  // 'home' | 'chat' | 'result' | 'drafts' | 'next'
  // 'next' = 문구 위치·크기 조정 화면(화면 D) 자리 — 아직 미구현, 버튼만 연결
  const [view, setView] = useState('home');
  const [chatOutcome, setChatOutcome] = useState(null); // { spec, mode, productImage, result }
  const [confirmedCopy, setConfirmedCopy] = useState(null); // { headline, sub } — 화면 B에서 확정
  // { id, image, seed } — 화면 C에서 선택. 서버가 stateless라 image(base64)를
  // 다음 화면(화면 D)에서 draft_image로 그대로 재전송해야 하므로 여기서 들고 있는다.
  const [selectedDraft, setSelectedDraft] = useState(null);
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
  };
  const newFlow = () => {
    setChatOutcome(null);
    setConfirmedCopy(null);
    setSelectedDraft(null);
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
  // TODO: 화면 D(문구 위치·크기 조정) 구현 후 실제 흐름으로 연결
  const handleDraftConfirmed = (draft) => {
    setSelectedDraft(draft);
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
        {view === 'next' && (
          <div className="app__placeholder">
            <div>
              문구 위치·크기 조정 화면(화면 D)은 다음 단계에서 구현될 예정입니다.
              {confirmedCopy && (
                <>
                  <br />
                  확정 문구: “{confirmedCopy.headline}”
                </>
              )}
            </div>
            {selectedDraft && (
              <img className="app__placeholder-thumb" src={selectedDraft.image} alt="선택한 시안" />
            )}
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
