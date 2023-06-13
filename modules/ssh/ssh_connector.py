"""
This module is for the class wich will be used to connect to the server
"""

import os
from paramiko import SSHClient, Ed25519Key, AutoAddPolicy
from dotenv import load_dotenv

load_dotenv()  # Load the .env file
host: str | None = os.getenv("HOST")


class SSHConnector:
    """Class for the SSH Connector"""

    __client = SSHClient()  # Create a new SSH Clients
    __private_key: Ed25519Key = Ed25519Key.from_private_key_file(
        "./modules/ssh/id_ed25519",
        password="qaqa.QA21",  # This should be possible to change
    )

    def __init__(
        self,
        private_key_path: str | None = None,
        private_key_password: str | None = None,
    ) -> None:
        if private_key_path is not None:
            self.__private_key = Ed25519Key.from_private_key_file(
                private_key_path,
                password=private_key_password,  # This should be possible to change
            )
        self.__client.set_missing_host_key_policy(AutoAddPolicy())

    def test_connection(self) -> bool:
        """Test the connection to the server

        Returns:
            bool: status of the connection
        """

        print(f"Host: {host}, Username: wharf")
        self.__client.connect(
            host or "url", port=1022, username="wharf", pkey=self.__private_key
        )
        if (
            self.__client.get_transport().is_active()
        ):  # pylance: disable=maybe-no-member
            print("Connection is active")
            self.__client.close()
            return True

        print("Connection is not active")
        self.__client.close()
        return False

    def generate_connection(self) -> str:
        """Generate the connection to the server

        Returns:
            str: status of the connection, if is active or not
        """
        self.__client.connect(
            host or "url", port=1022, username="wharf", pkey=self.__private_key
        )
        print("Connection generated")
        return "Connection is active"

    def verify_connection(self):
        """Verify if the connection is active

        Returns:
            bool: true if server is active, false if not
        """
        if self.__client.get_transport() is not None:
            return self.__client.get_transport().is_active()
        return False

    def close_connection(self):
        """Close the connection to the server

        Returns:
            str: status of closing the connection
        """
        self.__client.close()
        return "Connection closed"

    # não sinto que é correto deixar esta função aqui, mas mais tarde refatoremos esta classe

    def run_command(self, command: str):
        """Run a command in the server

        Args:
            command (str): needs to be a linux command

        Returns:
            list[str]: list of the output of the command
        """
        _, stdout, stderr = self.__client.exec_command(command)
        print(stderr.readlines())
        response = stdout.read().decode().splitlines()
        print(response)
        return response
