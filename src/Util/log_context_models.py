"""
Log Context Models

Pydantic models for logging context in authenticated and unauthenticated endpoints.
"""

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime, timezone


class LogContext(BaseModel):
    """
    Base log context model for authenticated endpoints.
    
    All authenticated endpoints should include this in their parameters
    to enable automatic logging and error handling.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_id: Optional[str] = Field(None, description="User ID performing the action")
    user_hash: Optional[str] = Field(None, description="User hash")
    username: Optional[str] = Field(None, description="Username")
    project_id: Optional[str] = Field(None, description="Project ID context")
    project_hash: Optional[str] = Field(None, description="Project hash")
    ip_address: Optional[str] = Field(None, description="Client IP address")
    user_agent: Optional[str] = Field(None, description="Client user agent")
    endpoint: Optional[str] = Field(None, description="API endpoint")
    method: Optional[str] = Field(None, description="HTTP method")
    request_id: Optional[str] = Field(None, description="Unique request ID")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Request timestamp")


class UnauthenticatedLogContext(BaseModel):
    """
    Log context for unauthenticated endpoints (login, register, etc.)
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    ip_address: Optional[str] = Field(None, description="Client IP address")
    user_agent: Optional[str] = Field(None, description="Client user agent")
    endpoint: Optional[str] = Field(None, description="API endpoint")
    method: Optional[str] = Field(None, description="HTTP method")
    request_id: Optional[str] = Field(None, description="Unique request ID")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="Request timestamp")
    username: Optional[str] = Field(None, description="Username attempting action")


class OperationMetadata(BaseModel):
    """
    Additional metadata for specific operations
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    operation_name: str = Field(..., description="Name of the operation")
    target_resource: Optional[str] = Field(None, description="Target resource (user_hash, project_hash, etc.)")
    target_resource_type: Optional[str] = Field(None, description="Type of resource (user, project, group)")
    changes: Optional[Dict[str, Any]] = Field(None, description="Changes being made")
    additional_data: Optional[Dict[str, Any]] = Field(None, description="Additional operation-specific data")
