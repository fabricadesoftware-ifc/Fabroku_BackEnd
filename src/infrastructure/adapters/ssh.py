import io
import os
import socket
from collections.abc import Generator
from typing import Callable

import paramiko

from observability.ssh_audit import begin_ssh_audit, finish_ssh_audit

INTERACTIVE_CHANNEL_OUTPUT_CHUNK_SIZE = 4096


class ParamikoInteractiveChannel:
    """Wraps a paramiko PTY channel behind the `InteractiveChannel` shape.

    Ports `_open_interactive_command`/`_read_channel_output` from
    `core/apps/mixins/apps/interactive_run.py` verbatim (Fase E of
    ADJUSTS_REFACTOR.md) — same recv/recv_stderr draining, same
    `socket.timeout` swallowed into an empty read, same stdin-close-then-
    client-close teardown order. Behavior is unchanged, only the location
    (isolated inside the adapter, not touched by use case/loop code).
    """

    def __init__(self, client: paramiko.SSHClient, stdin, stdout, stderr):
        self._client = client
        self._stdin = stdin
        self._stdout = stdout
        self._stderr = stderr

    def settimeout(self, timeout: float) -> None:
        self._stdout.channel.settimeout(timeout)
        self._stderr.channel.settimeout(timeout)

    def write(self, data: str) -> None:
        self._stdin.write(data)
        self._stdin.flush()

    def read_output(self) -> str:
        channel = self._stdout.channel
        parts = []
        try:
            while channel.recv_ready():
                parts.append(channel.recv(INTERACTIVE_CHANNEL_OUTPUT_CHUNK_SIZE).decode('utf-8', errors='replace'))
            while channel.recv_stderr_ready():
                parts.append(
                    channel.recv_stderr(INTERACTIVE_CHANNEL_OUTPUT_CHUNK_SIZE).decode('utf-8', errors='replace')
                )
        except socket.timeout:
            # Matches the original call-site behavior in interactive_run.py exactly: a
            # timeout anywhere in this read discards any partial output from this call,
            # not just the chunk that timed out.
            return ''
        return ''.join(parts)

    def exit_status_ready(self) -> bool:
        return self._stdout.channel.exit_status_ready()

    def exit_status(self) -> int:
        return self._stdout.channel.recv_exit_status()

    def close(self) -> None:
        try:
            self._stdin.close()
        except Exception:
            pass
        self._client.close()


class SSHAdapter:
    """Adapter para executar comandos via SSH."""

    def __init__(  # noqa: PLR0913
        self,
        host,
        username,
        ssh_key_path,
        port,
        *,
        connect_timeout=30,
        command_timeout=120,
        audit_context=None,
    ):
        self.host = host
        self.username = username
        self.ssh_key_path = ssh_key_path
        self.port = port
        self.connect_timeout = connect_timeout
        self.command_timeout = command_timeout
        self.audit_context = audit_context or {}
        self._temp_key_file = None

    @staticmethod
    def _successful_command_output(output: str, error_output: str) -> str:
        """Use stderr as Dokku progress output when stdout is empty."""
        if output.strip():
            return output
        return error_output

    def _get_pkey(self) -> paramiko.PKey:
        """
        Obtém a chave privada SSH.
        Suporta tanto caminho de arquivo quanto conteúdo da chave diretamente.
        """
        key_data = self.ssh_key_path

        if os.path.isfile(key_data):
            with open(key_data, encoding='utf-8') as f:
                key_data = f.read()

        if '\\n' in key_data:
            key_data = key_data.replace('\\n', '\n')

        key_file = io.StringIO(key_data)

        for key_class in [paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey]:
            try:
                key_file.seek(0)
                return key_class.from_private_key(key_file)
            except Exception:
                continue

        raise ValueError('Não foi possível carregar a chave SSH. Formato não suportado.')

    def _run_command(self, command: str) -> str:
        audit = begin_ssh_audit(command, self.audit_context)
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            pkey = self._get_pkey()
            client.connect(
                self.host,
                port=self.port,
                username=self.username,
                pkey=pkey,
                timeout=self.connect_timeout,
                banner_timeout=self.connect_timeout,
                auth_timeout=self.connect_timeout,
            )
            stdin, stdout, stderr = client.exec_command(command)
            stdout.channel.settimeout(self.command_timeout)
            stderr.channel.settimeout(self.command_timeout)
            output = stdout.read().decode('utf-8')
            error_output = stderr.read().decode('utf-8')
            exit_status = stdout.channel.recv_exit_status()
            if exit_status != 0:
                detail = error_output.strip() or output.strip() or '(sem detalhes)'
                finish_ssh_audit(
                    audit,
                    status='failed',
                    exit_status=exit_status,
                    error_summary=detail,
                )
                return f'Failed to execute command: {command}\n{detail}'
            finish_ssh_audit(audit, status='success', exit_status=exit_status)
            return self._successful_command_output(output, error_output)
        except socket.timeout:
            finish_ssh_audit(
                audit,
                status='timeout',
                error_summary=f'Timeout after {self.command_timeout}s',
            )
            return f'SSH Command Timeout after {self.command_timeout}s while executing: {command}'
        except Exception as e:
            finish_ssh_audit(audit, status='error', error_summary=str(e))
            return f'SSH Connection Error: {e}'
        finally:
            client.close()

    def _run_command_with_stdin(self, command: str, stdin_data: str) -> str:
        """Executa um comando via SSH enviando dados no stdin."""
        audit = begin_ssh_audit(command, self.audit_context)
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            pkey = self._get_pkey()
            client.connect(self.host, port=self.port, username=self.username, pkey=pkey)
            stdin, stdout, stderr = client.exec_command(command)
            stdin.write(stdin_data)
            stdin.channel.shutdown_write()
            output = stdout.read().decode('utf-8')
            error_output = stderr.read().decode('utf-8')
            exit_status = stdout.channel.recv_exit_status()
            if exit_status != 0:
                detail = error_output.strip() or output.strip() or '(sem detalhes)'
                finish_ssh_audit(
                    audit,
                    status='failed',
                    exit_status=exit_status,
                    error_summary=detail,
                )
                return f'Failed to execute command: {command}\n{detail}'
            finish_ssh_audit(audit, status='success', exit_status=exit_status)
            return self._successful_command_output(output, error_output)
        except Exception as e:
            finish_ssh_audit(audit, status='error', error_summary=str(e))
            return f'SSH Connection Error: {e}'
        finally:
            client.close()

    def _run_command_streaming(self, command: str) -> Generator[str, None, int]:
        """
        Executa um comando SSH e faz yield de cada linha conforme ela chega.
        Retorna o exit status no final.

        Uso:
            for line in adapter._run_command_streaming('git:sync ...'):
                print(line)
        """
        audit = begin_ssh_audit(command, self.audit_context)
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        exit_status = -1

        try:
            pkey = self._get_pkey()
            client.connect(self.host, port=self.port, username=self.username, pkey=pkey)
            stdin, stdout, stderr = client.exec_command(command, get_pty=True)

            for line in iter(stdout.readline, ''):
                yield line.rstrip('\n\r')

            exit_status = stdout.channel.recv_exit_status()

            if exit_status != 0:
                for line in stderr:
                    yield f'[ERROR] {line.rstrip()}'
                finish_ssh_audit(audit, status='failed', exit_status=exit_status)
            else:
                finish_ssh_audit(audit, status='success', exit_status=exit_status)

        except Exception as e:
            finish_ssh_audit(audit, status='error', error_summary=str(e))
            yield f'[SSH ERROR] {e}'

        finally:
            client.close()

        return exit_status

    def _run_command_streaming_controlled(  # noqa: PLR0912
        self,
        command: str,
        *,
        should_stop: Callable[[], bool],
        get_pty: bool = True,
    ) -> Generator[str, None, int]:
        """Executa comando streaming permitindo encerrar quando `should_stop` retornar True."""
        audit = begin_ssh_audit(command, self.audit_context)
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        exit_status = -1
        text_buffer = ''
        stopped_by_request = False

        try:
            pkey = self._get_pkey()
            client.connect(
                self.host,
                port=self.port,
                username=self.username,
                pkey=pkey,
                timeout=self.connect_timeout,
                banner_timeout=self.connect_timeout,
                auth_timeout=self.connect_timeout,
            )
            _stdin, stdout, stderr = client.exec_command(command, get_pty=get_pty)
            channel = stdout.channel
            channel.settimeout(1)

            while not channel.exit_status_ready():
                if should_stop():
                    stopped_by_request = True
                    channel.close()
                    break

                if channel.recv_ready():
                    chunk = channel.recv(4096).decode('utf-8', errors='replace')
                    text_buffer += chunk
                    while '\n' in text_buffer:
                        line, text_buffer = text_buffer.split('\n', 1)
                        yield line.rstrip('\r')
                    continue

                if channel.recv_stderr_ready():
                    chunk = channel.recv_stderr(4096).decode('utf-8', errors='replace')
                    text_buffer += chunk
                    while '\n' in text_buffer:
                        line, text_buffer = text_buffer.split('\n', 1)
                        yield f'[ERROR] {line.rstrip("\r")}'
                    continue

            if text_buffer.strip():
                yield text_buffer.rstrip('\r\n')

            if channel.exit_status_ready():
                exit_status = channel.recv_exit_status()
            if stopped_by_request:
                finish_ssh_audit(audit, status='success', exit_status=exit_status)
            elif exit_status == 0:
                finish_ssh_audit(audit, status='success', exit_status=exit_status)
            else:
                error_output = stderr.read().decode('utf-8', errors='replace') if not stderr.channel.closed else ''
                finish_ssh_audit(
                    audit,
                    status='failed',
                    exit_status=exit_status,
                    error_summary=error_output.strip(),
                )
        except Exception as e:
            finish_ssh_audit(audit, status='error', error_summary=str(e))
            yield f'[SSH ERROR] {e}'
        finally:
            client.close()

        return exit_status

    def open_interactive_channel(self, command: str) -> ParamikoInteractiveChannel:
        """Open a duplex PTY channel for `command`, left running for the caller to drive.

        Ports `_open_interactive_command` from `core/apps/mixins/apps/interactive_run.py`
        verbatim, including the deliberate omission of `connect_timeout`/`banner_timeout`/
        `auth_timeout` that `_run_command` passes — this call never had them, and Fase E's
        hard restriction is byte-identical behavior, not fixing that inconsistency.
        """
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        pkey = self._get_pkey()
        client.connect(self.host, port=self.port, username=self.username, pkey=pkey)
        stdin, stdout, stderr = client.exec_command(command, get_pty=True)
        return ParamikoInteractiveChannel(client, stdin, stdout, stderr)
