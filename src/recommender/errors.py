from __future__ import annotations


class RecommendationError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        field: str | None = None,
        status_code: int = 400,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field
        self.status_code = status_code

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"code": self.code, "message": self.message}
        if self.field:
            payload["field"] = self.field
        return {"error": payload}
