import { useEffect, useState } from 'react';
import Sidebar from './components/Sidebar';
import Home from './pages/Home';
import ChatFlow from './pages/ChatFlow';
import CopyResult from './pages/CopyResult';
import { REG_TIPS } from './constants/regulationTips';
import './App.css';

const REG_TIP_INTERVAL_MS = 4800;
const REG_TIP_FADE_MS = 350;

function App() {
  // 'home' | 'chat' | 'result' | 'next'
  // 'next' = 시안 선택 화면(화면 C) 자리 — 아직 미구현, 버튼만 연결
  const [view, setView] = useState('home');
  const [chatOutcome, setChatOutcome] = useState(null); // { spec, mode, productImage, result }
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
  };
  const newFlow = () => {
    setChatOutcome(null);
    setView('chat');
  };
  const handleChatComplete = (outcome) => {
    setChatOutcome(outcome);
    setView('result');
  };
  // TODO: 화면 C(시안 선택) 구현 후 실제 흐름으로 연결
  const handleCopyConfirmed = () => setView('next');

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
          <CopyResult result={chatOutcome.result} onConfirm={handleCopyConfirmed} onRestart={goHome} />
        )}
        {view === 'next' && (
          <div className="app__placeholder">시안 선택 화면(화면 C)은 다음 단계에서 구현될 예정입니다.</div>
        )}
      </main>
    </div>
  );
}

export default App;
