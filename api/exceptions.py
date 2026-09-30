from starlette.exceptions import HTTPException


class ValidationError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=400, detail=detail)


class CalculationError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=500, detail=detail)
