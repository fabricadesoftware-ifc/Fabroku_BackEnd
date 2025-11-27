import paramiko
from django.conf import settings


class SSHAdapter:
    def __init__(self,):

        self.host = settings.DOKKU_SSH_HOST
        self.username = settings.DOKKU_SSH_USERNAME
        self.ssh_key_path = settings.DOKKU_SSH_KEY

    def _run_command(self, command: str) -> bool:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(self.host, username=self.username, key_filename=self.ssh_key_path)
            stdin, stdout, stderr = client.exec_command(command)
            exit_status = stdout.channel.recv_exit_status()
            if exit_status != 0:
                print(f"Error executing '{command}': {stderr.read().decode()}")
                return False
            return True
        except Exception as e:
            print(f"SSH Connection Error: {e}")
            return False
        finally:
            client.close()
