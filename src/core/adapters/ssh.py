from collections.abc import Generator

import paramiko


class SSHAdapter:
    """Adapter para executar comandos via SSH."""

    def __init__(self, host, username, ssh_key_path, port):
        self.host = host
        self.username = username
        self.ssh_key_path = ssh_key_path
        self.port = port

    def _run_command(self, command: str) -> str:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(self.host, port=self.port, username=self.username, key_filename=self.ssh_key_path)
            stdin, stdout, stderr = client.exec_command(command)
            exit_status = stdout.channel.recv_exit_status()
            if exit_status != 0:
                print(f"Error executing '{command}': {stderr.read().decode()}")
                return f'Failed to execute command: {command}'
            return stdout.read().decode('utf-8')
        except Exception as e:
            print(f'SSH Connection Error: {e}, paramters: host={self.host}, username={self.username}, port={self.port}')  # noqa: E501
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
            client.connect(self.host, port=self.port, username=self.username, key_filename=self.ssh_key_path)
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
