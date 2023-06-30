"""
@snow-sr
Main file for FastApi routes
"""
from fastapi import FastAPI
from modules.ssh.ssh_connector import SSHConnector
from modules.server import server

app = FastAPI()

sshClient = SSHConnector()


@app.get("/")
def read_root():
    """
    Root route
    """
    return "Hello there! This is the Fabroku Api, for more info about how to use, go to /docs"


@app.get("/testSsh")
def test_ssh_connection():
    """Route for testing the SSH connection"""
    data = sshClient.test_connection()

    return {"data": data}


@app.post("/generatessh")
def generate_ssh_connection():
    """Route for generating the SSH connection"""
    data = sshClient.generate_connection()
    return {"data": data}


@app.get("/closeconnection")
def close_connection():
    """Route for closing the SSH connection"""
    sshClient.close_connection()
    return "Connection closed"


@app.get("/appslist")
def apps_list():
    """Route for getting the list of apps from dokku"""
    data = server.apps_list()
    return {"data": data}


@app.post("/runcommand")
def run_command(command: str):
    """Route for running a command"""
    data = sshClient.run_command(command)
    print(data, "Here")
    return {"data": data}
