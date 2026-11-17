"""Safe, content-free AI gateway error codes."""


class AIGatewayError(RuntimeError):
    code = "AI_GATEWAY_ERROR"


class AIExecutionDenied(AIGatewayError):
    code = "AI_EXECUTION_DENIED"


class AIProviderNotConfigured(AIGatewayError):
    code = "AI_PROVIDER_NOT_CONFIGURED"


class AIInvocationAlreadyExists(AIGatewayError):
    code = "AI_INVOCATION_ALREADY_EXISTS"


class AIInvocationConflict(AIGatewayError):
    code = "AI_INVOCATION_REQUEST_HASH_CONFLICT"


class AIUsageLedgerConflict(AIGatewayError):
    code = "AI_USAGE_LEDGER_CONFLICT"


class AIProviderOutcomeUnknown(AIGatewayError):
    code = "AI_PROVIDER_OUTCOME_UNKNOWN"


class AIProviderFailure(AIGatewayError):
    def __init__(self, safe_code: str, *, definitive: bool) -> None:
        super().__init__(safe_code)
        if (
            not safe_code
            or len(safe_code) > 64
            or not safe_code.replace("_", "").isalnum()
            or not safe_code.isascii()
            or safe_code.upper() != safe_code
        ):
            raise ValueError(
                "safe provider error code must be 1..64 uppercase alphanumeric characters"
            )
        self.safe_code = safe_code
        self.definitive = definitive


class AIActualCostExceededReservation(AIGatewayError):
    code = "AI_ACTUAL_COST_EXCEEDED_RESERVATION"


class AIReservationSettlementFailed(AIGatewayError):
    code = "AI_RESERVATION_SETTLEMENT_FAILED"


class AIUsageAccountingUnknown(AIGatewayError):
    code = "AI_USAGE_ACCOUNTING_UNKNOWN"
