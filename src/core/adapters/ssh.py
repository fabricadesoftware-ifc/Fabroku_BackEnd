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
            client.connect(self.host, username=self.username, key_filename=self.ssh_key_path)
            stdin, stdout, stderr = client.exec_command(command)
            exit_status = stdout.channel.recv_exit_status()
            if exit_status != 0:
                print(f"Error executing '{command}': {stderr.read().decode()}")
                return f"Failed to execute command: {command}"
            return stdout.read().decode('utf-8')
        except Exception as e:
            print(f"SSH Connection Error: {e}, paramters: host={self.host}, username={self.username}, port={self.port}")  # noqa: E501
            return f"SSH Connection Error: {e}"
        finally:
            client.close()
