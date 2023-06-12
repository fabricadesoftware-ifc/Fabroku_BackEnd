from paramiko import SSHClient, Ed25519Key, AutoAddPolicy
from dotenv import load_dotenv
import os

load_dotenv()  # Load the .env file

client = SSHClient()  # Create a new SSH Clients

# Load the private key
private_key = Ed25519Key.from_private_key_file(
    "./modules/ssh/id_ed25519", password="qaqa.QA21"
)
# Automatically add the remote server's host key
# If the server isn't known, this will automatically add the key to the client
client.set_missing_host_key_policy(AutoAddPolicy())

host = os.getenv("HOST")


class SSHConnector:
    __client = SSHClient()  # Create a new SSH Clients
    __private_key = Ed25519Key.from_private_key_file(
        "./modules/ssh/id_ed25519", password="qaqa.QA21"
    )

    def __init__(self):
        self.__client.set_missing_host_key_policy(AutoAddPolicy())

    def testConnection(self):
        print(f"Host: {host}, Username: wharf")
        self.__client.connect(
            host, port=1022, username="wharf", pkey=self.__private_key
        )
        if self.__client.get_transport().is_active():
            print("Connection is active")
            self.__client.close()
            return True
        else:
            print("Connection is not active")
            self.__client.close()
            return False

    def generateConnection(self):
        self.__client.connect(
            host, port=1022, username="wharf", pkey=self.__private_key
        )
        return "Connection is active"

    def verifyConnection(self):
        if (
            self.__client.get_transport() is not None
            and self.__client.get_transport().is_active()
        ):
            return True
        else:
            return False

    def closeConnection(self):
        self.__client.close()
        return "Connection closed"

    # não sinto que é correto deixar esta função aqui, mas mais tarde refatoremos esta classe

    def runCommand(self, command):
        _, stdout, stderr = self.__client.exec_command(command)
        if stderr == None:
            return stdout.readlines()
        else:
            return stderr.readlines()
