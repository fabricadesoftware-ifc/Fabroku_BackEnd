"""Models moved to `identity.models` (Fase 3.2 of REFACTOR-PLAN.md): User, CLIToken.

AUTH_USER_MODEL is now `identity.User`. This app (`core.auth_user`) still hosts
views/serializers/admin/authentication/urls code — only the models themselves
relocated. Import them from `identity.models`.
"""
