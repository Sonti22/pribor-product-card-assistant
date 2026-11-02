class CardError(Exception):
    """A safe, actionable error; never includes raw provider responses."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class InputError(CardError):
    def __init__(self, message: str):
        super().__init__("invalid_input", message)
