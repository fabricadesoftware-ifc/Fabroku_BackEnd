"""Models for this app moved to `observability.models` (Fase 3.7 of REFACTOR-PLAN.md).

This app (`core.logs`) still hosts views/serializers/admin/middleware/log-streaming
code — only the models themselves (AppLog, SSHCommandAudit, AppLogManager, etc.)
relocated. Import them from `observability.models`.
"""
