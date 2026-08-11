import idleImg from '../assets/mascot/idle.png';
import workingImg from '../assets/mascot/working.png';
import './Mascot.css';

// success.png는 아직 준비되지 않았다 — 매핑에 없는 표정은 idle로 대체된다.
// 나중에 파일이 추가되면 이 객체에 success: successImg 한 줄만 추가하면 된다.
const EXPRESSIONS = {
  idle: idleImg,
  working: workingImg,
};

/**
 * 서비스 마스코트 캐릭터. expression(idle/working/success)에 따라 이미지를
 * 바꿔 끼우고, size(px)로 렌더 크기를 정한다. 홈 화면의 큰 사이즈부터 챗봇
 * 아바타의 작은 사이즈까지 이 컴포넌트 하나로 대응한다.
 */
function Mascot({ expression = 'idle', size = 96, className = '', ...rest }) {
  const src = EXPRESSIONS[expression] || EXPRESSIONS.idle;

  return (
    <img
      src={src}
      alt=""
      aria-hidden="true"
      className={`mascot${className ? ` ${className}` : ''}`}
      style={{ width: size, height: size }}
      {...rest}
    />
  );
}

export default Mascot;
