import homeFoodImg from '../assets/examples/home-food.png';
import homeBeautyImg from '../assets/examples/home-beauty.png';
import homeServiceImg from '../assets/examples/home-service.png';

// 홈 화면 우측에 세로로 자동 스크롤되는 예시 결과 카드(TickerPreview.jsx).
// image: 최종 시연용 실제 예시 이미지 — 헤드라인/서브 문구가 이미지 자체에
//   이미 완성된 형태로 들어있어(실제 포스터 결과 예시), 카드에서 별도 텍스트를
//   다시 그리지 않고 이 이미지를 그대로 보여준다.
// text: 화면에는 그리지 않고 <img alt>로만 쓴다(이미지 내용 설명).
// caption: 카드 우상단 caption 배지 문구("업종 · 용도").
//
// 세 번째 카드는 원래 굿즈였으나, 최종 데모에서는 서비스 지원 업종(학원/체육관)
// 중 이미지 내용에 맞는 학원 예시로 교체했다(home-service.png가 강사/스터디룸
// 사진이라 학원 쪽에 해당).
export const TICKER_ITEMS = [
  { image: homeFoodImg, text: '상큼함 한 잔! 오렌지 본연의 맛을 담았어요', caption: '푸드 · SNS 카드뉴스' },
  { image: homeBeautyImg, text: '한 번에 선명하게! 입술에 또렷하게 물드는 립 틴트', caption: '뷰티 · 상세페이지' },
  { image: homeServiceImg, text: '맞춤 강사로 시작, 전문 강사진이 학습 방향에 맞춰 지도합니다', caption: '학원 · SNS 광고' },
];
