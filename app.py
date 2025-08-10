# IMPORTANT: This must be the very first thing to run!
from gevent import monkey
monkey.patch_all()

import os
import docker
import logging
import gevent
from flask import Flask, render_template
from flask_sock import Sock

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

app = Flask(__name__)
sock = Sock(app)

# --- Docker Constants ---
DOCKER_IMAGE_NAME = "gemini-terminal-box"
DOCKER_CONTAINER_NAME = "gemini-terminal-instance"

def build_docker_image():
    """Builds the Docker image if it doesn't exist."""
    client = docker.from_env()
    try:
        client.images.get(DOCKER_IMAGE_NAME)
        logging.info(f"Docker image '{DOCKER_IMAGE_NAME}' already exists.")
    except docker.errors.ImageNotFound:
        logging.info(f"Docker image '{DOCKER_IMAGE_NAME}' not found. Building...")
        try:
            client.images.build(
                path=".",
                dockerfile="Dockerfile",
                tag=DOCKER_IMAGE_NAME,
                rm=True
            )
            logging.info(f"Successfully built image '{DOCKER_IMAGE_NAME}'")
        except docker.errors.BuildError as e:
            logging.error(f"Error building Docker image: {e}")
            raise

def get_or_create_container(client):
    """Gets the running container or creates a new one."""
    try:
        container = client.containers.get(DOCKER_CONTAINER_NAME)
        if container.status != "running":
            logging.info("Container exists but is not running. Starting...")
            container.start()
        else:
            logging.info("Attaching to existing running container.")
        return container
    except docker.errors.NotFound:
        logging.info(f"Container '{DOCKER_CONTAINER_NAME}' not found. Creating a new one...")
        container = client.containers.run(
            DOCKER_IMAGE_NAME,
            name=DOCKER_CONTAINER_NAME,
            tty=True,
            stdin_open=True,
            detach=True,
            command="/bin/bash"
        )
        logging.info(f"Container '{DOCKER_CONTAINER_NAME}' created.")
        return container

@app.route('/')
def index():
    return render_template('index.html')

@sock.route('/ws')
def ws(ws):
    """Handle the websocket connection."""
    logging.info("WebSocket connection accepted.")
    client = docker.from_env()
    try:
        container = get_or_create_container(client)
        
        exec_instance = client.api.exec_create(
            container.id, 'bash', stdout=True, stderr=True, stdin=True, tty=True
        )
        
        socket = client.api.exec_start(exec_instance['Id'], tty=True, socket=True)
        socket_stream = socket._sock
        logging.info("Attached to container exec instance.")

        def forward_container_to_ws():
            try:
                while True:
                    data = socket_stream.recv(1024)
                    if not data:
                        break
                    ws.send(data.decode('utf-8', errors='ignore'))
            except Exception as e:
                logging.warning(f"Container->WS forwarder error: {e}")

        def forward_ws_to_container():
            try:
                while True:
                    message = ws.receive()
                    if message:
                        socket_stream.sendall(message.encode('utf-8'))
            except Exception as e:
                logging.warning(f"WS->Container forwarder error: {e}")

        # With monkey-patching, we can use gevent.spawn for concurrency
        output_greenlet = gevent.spawn(forward_container_to_ws)
        input_greenlet = gevent.spawn(forward_ws_to_container)

        # Wait for both to complete
        gevent.joinall([input_greenlet, output_greenlet], raise_error=True)

    except Exception as e:
        logging.error(f"Main handler error: {e}")
    finally:
        logging.info("WebSocket handler finished.")


if __name__ == '__main__':
    try:
        build_docker_image()
        print("\n--- Application Ready ---")
        print("Navigate to http://127.0.0.1:8080")
        print("-------------------------\n")
        
        # We need the gevent-native server, not Flask's default one
        from gevent.pywsgi import WSGIServer
        http_server = WSGIServer(('0.0.0.0', 8080), app)
        http_server.serve_forever()

    except docker.errors.DockerException as e:
        logging.critical(f"Failed to initialize Docker: {e}")
        logging.critical("Please ensure Docker is running and you have the correct permissions.")
    except Exception as e:
        logging.critical(f"Failed to start server: {e}")
