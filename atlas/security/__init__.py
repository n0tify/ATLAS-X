"""Log redaction and the authorization boundary for user-owned data."""

from atlas.logging_config import configure_logging, get_logger
from atlas.security.errors import (
    AuthorizationError,
    InvalidAuthorizationRequest,
    PermissionDenied,
    Unauthenticated,
)
from atlas.security.identity import Identity, IdentityResolver
from atlas.security.logging import SecretsRedactionFilter
from atlas.security.policy import (
    PERMITTED_OPERATIONS,
    PROHIBITED_TOOL_CAPABILITIES,
    Decision,
    DenyReason,
    NoToolGrants,
    Operation,
    Resource,
    ToolGrant,
    ToolGrantSource,
    decide_operation,
    decide_tool_invocation,
)
from atlas.security.service import AuthorizationService

__all__ = [
    "SecretsRedactionFilter",
    "configure_logging",
    "get_logger",
    "AuthorizationService",
    "Identity",
    "IdentityResolver",
    "AuthorizationError",
    "InvalidAuthorizationRequest",
    "PermissionDenied",
    "Unauthenticated",
    "Decision",
    "DenyReason",
    "Operation",
    "Resource",
    "ToolGrant",
    "ToolGrantSource",
    "NoToolGrants",
    "PERMITTED_OPERATIONS",
    "PROHIBITED_TOOL_CAPABILITIES",
    "decide_operation",
    "decide_tool_invocation",
]
