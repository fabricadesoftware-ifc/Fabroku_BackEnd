from core.logs.ssh_audit import ssh_audit_context


class SSHCommandAuditContextMiddleware:
    """Adiciona metadados HTTP básicos ao contexto de auditoria SSH."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        with ssh_audit_context(
            origin='http',
            request_path=request.path[:512],
            request_method=request.method,
        ):
            return self.get_response(request)
