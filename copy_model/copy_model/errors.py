"""copy_model 도메인 예외.

목적: 클라이언트 입력 오류와 서버/업스트림 오류를 구분해 HTTP 상태코드를
정확히 매핑하기 위함.

- CopyInputError: 스키마는 통과했으나 의미적으로 잘못된 클라이언트 입력
  (예: service(business_type=service) + auto 모드처럼 미지원 조합).
  api 레이어에서 400(Bad Request)으로 매핑한다.
  ValueError 하위라, pydantic 검증 단계에서 쓰이면 자동으로 422가 된다.

- 그 외 예외(모델/네트워크/서버 내부 오류)는 api 레이어에서 502로 매핑한다.
"""


class CopyInputError(ValueError):
    """클라이언트 입력이 의미적으로 잘못됨 → HTTP 400."""
