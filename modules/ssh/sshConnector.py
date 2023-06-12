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


def testConnection():
    print(f"Host: {host}, Username: wharf")
    client.connect(host, port=1022, username="wharf", pkey=private_key)
    if client.get_transport().is_active():
        print("Connection is active")
        client.close()
        return True
    else:
        print("Connection is not active")
        client.close()
        return False


def generateConnection():
    client.connect(host, port=1022, username="wharf", pkey=private_key)
    return "Connection is active"


def verifyConnection():
    if client.get_transport() is not None and client.get_transport().is_active():
        return True
    else:
        return False


def runCommand(command):
    _, stdout, stderr = client.exec_command(command)
    return stdout.readlines()
