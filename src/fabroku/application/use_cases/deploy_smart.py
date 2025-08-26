from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Callable

from fabroku.domain.ports import DokkuService, OperationResult

import os
import tempfile
import subprocess
import shutil
from pathlib import Path


@dataclass
class DeployStateSync:
	"""Callback para sincronizar estado de deploy no backend.

	Implementações podem salvar em Django (modelo Deploy) os estados e metadados.
	"""
	set_status: Callable[[str], None]
	set_analysis: Callable[[Dict], None]
	append_log: Callable[[str], None]
	set_error: Callable[[str], None]


class SmartDeployUseCase:
	def __init__(self, dokku_service: DokkuService) -> None:
		self._dokku = dokku_service

	def execute(
		self,
		app_name: str,
		source_type: str,
		source_url: str,
		state_sync: Optional[DeployStateSync] = None,
		default_branch: str = "main",
		buildpack: Optional[str] = None,
	) -> OperationResult:
		if not app_name or not source_type or not source_url:
			return OperationResult(False, "'app_name', 'source_type' e 'source_url' são obrigatórios para smart-deploy.")

		try:
			if state_sync:
				state_sync.set_status("em_andamento")
				state_sync.append_log("Iniciando análise e deploy...")

			analysis: Dict[str, object] = {
				"has_dockerfile": False,
				"dockerfile_paths": [],
				"has_docker_dir": False,
				"strategy": None,
			}

			result: OperationResult

			if source_type == "docker_image":
				# Deploy via imagem Docker
				analysis["strategy"] = "dokku-tags-deploy"
				if state_sync:
					state_sync.append_log(f"Deployando imagem Docker: {source_url}...")
				result = self._dokku.deploy(app_name=app_name, image=source_url)
			elif source_type == "git":
				# Normaliza git_url e branch
				branch = default_branch
				repo_url = source_url
				if "#" in source_url:
					repo_url, branch = source_url.split("#", 1)

				# Clonagem rasa em diretório temporário para inspeção
				tmpdir = tempfile.mkdtemp(prefix="fabroku_")
				try:
					if state_sync:
						state_sync.append_log(f"Clonando {repo_url} (branch {branch}) para análise...")
					clone_cmd = [
						"git", "clone", "--depth=1", "--single-branch", "--branch", branch, repo_url, tmpdir,
					]
					clone_proc = subprocess.run(clone_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
					if clone_proc.returncode != 0 and state_sync:
						state_sync.append_log(f"Aviso: falha ao clonar para análise: {clone_proc.stderr or clone_proc.stdout}")

					# Procura Dockerfile
					root = Path(tmpdir)
					candidates: list[Path] = []
					for path in [root, root / "docker", root / "deploy", root / "ops", root / ".docker"]:
						if path.is_dir():
							for child in path.rglob("Dockerfile"):
								candidates.append(child)
					# case-insensitive fallback (Dockerfile vs dockerfile)
					if not candidates:
						for child in root.rglob("dockerfile"):
							candidates.append(child)

					docker_dir_exists = (root / "docker").exists()
					analysis["has_docker_dir"] = docker_dir_exists
					analysis["dockerfile_paths"] = [str(p.relative_to(root)) for p in candidates]
					analysis["has_dockerfile"] = len(candidates) > 0

					# Escolha de estratégia
					dockerfile_path: Optional[str] = None
					if candidates:
						# Prioriza Dockerfile na raiz
						root_df = [p for p in candidates if p.parent == root]
						if root_df:
							dockerfile_path = "Dockerfile"
						else:
							# Pega o primeiro candidato encontrado
							dockerfile_path = str(candidates[0].relative_to(root))

					if dockerfile_path:
						analysis["strategy"] = "dokku-git-dockerfile"
						if state_sync:
							state_sync.append_log(f"Dockerfile detectado em: {dockerfile_path}. Configurando Dokku...")
						# Informa ao Dokku o caminho alternativo (quando não está na raiz)
						if dockerfile_path != "Dockerfile":
							cfg = {"DOKKU_DOCKERFILE_PATH": dockerfile_path}
							set_cfg = self._dokku.config_set(app_name, cfg)
							if not set_cfg.success:
								if state_sync:
									state_sync.append_log(f"Falha ao configurar DOKKU_DOCKERFILE_PATH: {set_cfg.message}")
								return set_cfg
					else:
						analysis["strategy"] = "dokku-git"

				finally:
					# Limpa diretório temporário
					try:
						shutil.rmtree(tmpdir, ignore_errors=True)
					except Exception:
						pass

				# Executa deploy via Dokku
				result = self._dokku.deploy(app_name=app_name, git_url=f"{repo_url}#{branch}", buildpack=buildpack)
			else:
				return OperationResult(False, f"Tipo de fonte '{source_type}' não suportado.")

			if result.success:
				if state_sync:
					state_sync.set_analysis(analysis)
					state_sync.set_status("pronto")
					state_sync.append_log("Deploy concluído com sucesso.")
				return result

			# Falhou
			if state_sync:
				analysis["strategy"] = analysis.get("strategy") or f"dokku-{source_type}"
				state_sync.set_analysis(analysis)
				state_sync.set_status("erro")
				state_sync.set_error(result.message)
			return OperationResult(False, f"Falha no deploy: {result.message}")
		except Exception as exc:
			if state_sync:
				state_sync.set_status("erro")
				state_sync.set_error(str(exc))
			return OperationResult(False, f"Erro no smart-deploy: {exc}") 