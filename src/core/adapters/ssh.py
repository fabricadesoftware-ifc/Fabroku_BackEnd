import io
import os
import tempfile
from collections.abc import Generator

import paramiko


class SSHAdapter:
    """Adapter para executar comandos via SSH."""

    def __init__(self, host, username, ssh_key_path, port):
        self.host = host
        self.username = username
        self.ssh_key_path = ssh_key_path
        self.port = port
        self._temp_key_file = None

    def _get_pkey(self) -> paramiko.PKey:
        """
        Obtém a chave privada SSH.
        Suporta tanto caminho de arquivo quanto conteúdo da chave diretamente.
        """
        key_data = self.ssh_key_path

        # Se é um caminho de arquivo que existe, lê o conteúdo
        if os.path.isfile(key_data):
            with open(key_data) as f:
                key_data = f.read()

        # Se o conteúdo veio inline (variável de ambiente), pode ter \n escapado
        if '\\n' in key_data:
            key_data = key_data.replace('\\n', '\n')

        # Carrega a chave do conteúdo
        key_file = io.StringIO(key_data)

        # Tenta diferentes formatos de chave
        for key_class in [paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey]:
            try:
                key_file.seek(0)
                return key_class.from_private_key(key_file)
            except Exception:
                continue

        raise ValueError('Não foi possível carregar a chave SSH. Formato não suportado.')

    def _run_command(self, command: str) -> str:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            pkey = self._get_pkey()
            client.connect(self.host, port=self.port, username=self.username, pkey=pkey)
            stdin, stdout, stderr = client.exec_command(command)
            output = stdout.read().decode('utf-8')
            error_output = stderr.read().decode('utf-8')
            exit_status = stdout.channel.recv_exit_status()
            if exit_status != 0:
                detail = error_output.strip() or output.strip() or '(sem detalhes)'
                return f'Failed to execute command: {command}\n{detail}'
            return output
        except Exception as e:
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
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        exit_status = -1

        try:
            pkey = self._get_pkey()
            client.connect(self.host, port=self.port, username=self.username, pkey=pkey)
            stdin, stdout, stderr = client.exec_command(command, get_pty=True)

            # Lê linha por linha conforme chegam
            for line in iter(stdout.readline, ''):
                yield line.rstrip('\n\r')

            exit_status = stdout.channel.recv_exit_status()

            # Se houve erro, yield as linhas de erro também
            if exit_status != 0:
                for line in stderr:
                    yield f'[ERROR] {line.rstrip()}'

        except Exception as e:
            yield f'[SSH ERROR] {e}'

        finally:
            client.close()

        return exit_status
