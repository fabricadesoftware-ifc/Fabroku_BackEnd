from __future__ import annotations

from typing import Optional

from fabroku.domain.ports import DokkuService, OperationResult


class InstallPluginUseCase:
    def __init__(self, dokku_service: DokkuService) -> None:
        self._dokku = dokku_service

    def execute(self, plugin_git_url: str, name: Optional[str] = None) -> OperationResult:
        if not plugin_git_url:
            return OperationResult(False, "URL do plugin é obrigatória.")
        return self._dokku.plugin_install(plugin_git_url=plugin_git_url, name=name)


