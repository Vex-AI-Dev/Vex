class AgentGuardError(Exception):
    """Base exception for AgentGuard SDK."""


class ConfigurationError(AgentGuardError):
    """Invalid SDK configuration."""


class IngestionError(AgentGuardError):
    """Failed to send telemetry to AgentGuard backend."""


class VerificationError(AgentGuardError):
    """Verification request failed."""
