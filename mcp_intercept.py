import logging
import sys
import subprocess
import threading
import os
import argparse
from websocket_server import WebsocketServer
import websocket

# Configure logging at module level
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

# --- Globals ---
_client_lock = threading.Lock()
_client_joined = False
_shutdown_event = threading.Event()
_original_stdout = sys.stdout  # keep protocol writes here
sys.stdout = sys.stderr  # redirect protocol writes to stderr


def drain_stderr(proc):
    """Continuously read from subprocess stderr to avoid blocking."""
    try:
        while True:
            msg = proc.stderr.readline()
            if not msg:
                break
            sys.stderr.buffer.write(msg.encode("utf-8"))
            sys.stderr.flush()
    except (BrokenPipeError, ValueError, OSError) as e:
        logging.warning(f"Error draining stderr: {e}")
    except Exception as e:
        logging.error(f"Unexpected error in drain_stderr: {e}")


def on_message(client, server, msg: str, proc):
    """Forward WebSocket message to subprocess stdin."""
    try:
        proc.stdin.buffer.write(msg.encode("utf-8"))
        proc.stdin.flush()
    except BrokenPipeError:
        logging.warning("Subprocess stdin closed; dropping message")
    except (OSError, ValueError) as e:
        logging.warning(f"Error forwarding message to subprocess: {e}")
    except Exception as e:
        logging.error(f"Unexpected error in on_message: {e}")


def on_new_client(client, server, proc):
    """Handle new client connection."""
    global _client_joined
    with _client_lock:
        if _client_joined:
            logging.error("Client already joined; ignoring new connection.")
            # Just return - the server will handle the connection normally
            # but we won't process messages from this client
            return
        _client_joined = True
        logging.info("Client connected")

    t = threading.Thread(target=proc_to_ws_thread_func,
                         args=(proc, client, server),
                         daemon=True)
    t.start()


def on_client_left(client, server):
    """Handle client disconnection by triggering shutdown."""
    global _client_joined
    with _client_lock:
        _client_joined = False
    logging.info("Client disconnected, initiating shutdown...")
    _shutdown_event.set()


def cleanup(proc, server, threads=None):
    """Perform comprehensive cleanup of resources."""
    logging.info("Starting cleanup...")

    # Signal shutdown to all threads
    _shutdown_event.set()

    # Close subprocess stdin first to signal it to exit
    try:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
    except Exception as e:
        logging.warning(f"Error closing subprocess stdin: {e}")

    # Give the process a chance to exit gracefully
    try:
        proc.wait(timeout=3)
        logging.info("Subprocess exited gracefully")
    except subprocess.TimeoutExpired:
        logging.warning("Subprocess did not exit gracefully, terminating...")
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            logging.error("Subprocess did not respond to terminate, killing...")
            proc.kill()
            proc.wait()

    # Stop the WebSocket server
    try:
        server.shutdown()
        logging.info("WebSocket server stopped")
    except Exception as e:
        logging.warning(f"Error shutting down WebSocket server: {e}")

    # Wait for threads to finish
    if threads:
        for thread in threads:
            if thread.is_alive():
                try:
                    thread.join(timeout=2)
                    if thread.is_alive():
                        logging.warning(f"Thread {thread.name} did not exit cleanly")
                except KeyboardInterrupt:
                    logging.info(f"Interrupted while waiting for thread {thread.name}")
                    # Don't re-raise, just continue cleanup
                except Exception as e:
                    logging.warning(f"Error joining thread {thread.name}: {e}")

    logging.info("Cleanup completed")


def validate_args(args):
    """Validate command line arguments."""
    if args.proxy_port < 1 or args.proxy_port > 65535:
        raise ValueError(f"Invalid proxy port: {args.proxy_port}")

    if not args.program:
        raise ValueError("Program argument is required")

    # Check if the program exists in PATH
    import shutil
    if not shutil.which(args.program.split()[0] if ' ' in args.program else args.program):
        logging.warning(f"Program '{args.program}' not found in PATH")


def proc_to_ws_thread_func(proc, client, server):
    """Read from subprocess stdout and forward to WebSocket."""
    try:
        while True:
            msg = proc.stdout.readline()
            if not msg:
                break
            try:
                server.send_message(client, msg)
            except Exception as e:
                logging.warning(f"Error forwarding message to WebSocket: {e}")
                break
    except (BrokenPipeError, ValueError, OSError) as e:
        logging.warning(f"Error reading from subprocess stdout: {e}")
    except Exception as e:
        logging.error(f"Unexpected error in proc_to_ws_thread: {e}")


def ws_to_client_thread_func(ws):
    """Read from WebSocket and forward to original stdout."""
    try:
        while True:
            try:
                msg = ws.recv()
                if not msg:
                    break
                _original_stdout.buffer.write(msg.encode("utf-8"))
                _original_stdout.flush()
            except (websocket.WebSocketConnectionClosedException,
                    websocket._exceptions.WebSocketTimeoutException,
                    ConnectionResetError):
                logging.info("WebSocket connection closed")
                break
            except Exception as e:
                logging.warning(f"Error in WebSocket message handling: {e}")
                break
    except Exception as e:
        logging.error(f"Unexpected error in ws_to_client_thread: {e}")


def client_thread_func(server_address, proxy_port):
    """Connect a WebSocket client (optionally via proxy) and relay stdin/stdout."""
    url = f"ws://{server_address[0]}:{server_address[1]}"
    logging.info(f"Connecting WebSocket client to {url} via 127.0.0.1:{proxy_port}")

    ws = None
    try:
        ws = websocket.create_connection(url,
                                         http_proxy_host="127.0.0.1",
                                         http_proxy_port=proxy_port)

        t = threading.Thread(target=ws_to_client_thread_func, args=(ws,), daemon=True)
        t.start()

        try:
            while not _shutdown_event.is_set():
                # Cross-platform non-blocking stdin read
                try:
                    msg = sys.stdin.readline()
                    if not msg:
                        break
                    ws.send(msg)
                except Exception as e:
                    logging.warning(f"Error reading from stdin: {e}")
        except KeyboardInterrupt:
            logging.info("Received keyboard interrupt")
        except Exception as e:
            logging.error(f"Error in client thread: {e}")
    except Exception as e:
        logging.error(f"Failed to connect WebSocket client: {e}")
    finally:
        if ws:
            ws.close()
        _shutdown_event.set()  # Ensure shutdown is signaled


def main():
    parser = argparse.ArgumentParser(
        description="Intercept MCP via WebSocket and optional proxy.")
    parser.add_argument(
        "program", help="Program to run (e.g., node mcp-server-filesystem)")
    parser.add_argument("args",
                        nargs=argparse.REMAINDER,
                        help="Arguments for the subprocess")
    parser.add_argument(
        "--proxy-port",
        type=int,
        default=8080,
        help="Optional HTTP proxy port for WebSocket (e.g., 8080)")
    args = parser.parse_args()

    try:
        validate_args(args)
    except ValueError as e:
        logging.error(f"Invalid arguments: {e}")
        sys.exit(1)

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    logging.info(f"Starting subprocess: {[args.program] + args.args}")

    proc = None
    server = None
    threads = []

    try:
        proc = subprocess.Popen([args.program] + args.args,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True,
                                bufsize=1,
                                env=env,
                                encoding="utf-8")

        stderr_thread = threading.Thread(target=drain_stderr,
                                         args=(proc, ),
                                         daemon=True,
                                         name="stderr_drain")
        stderr_thread.start()
        threads.append(stderr_thread)

        server = WebsocketServer(host="127.0.0.1",
                                 port=0,
                                 loglevel=logging.ERROR)
        server.set_fn_message_received(
            lambda c, s, m: on_message(c, s, m, proc))
        server.set_fn_new_client(lambda c, s: on_new_client(c, s, proc))
        server.set_fn_client_left(on_client_left)

        host, port = server.server_address
        logging.info(f"WebSocket relay server listening on ws://{host}:{port}")

        client_thread = threading.Thread(target=client_thread_func,
                                         args=(server.server_address,
                                               args.proxy_port),
                                         daemon=True,
                                         name="client_thread")
        client_thread.start()
        threads.append(client_thread)

        # Run server in a separate thread so we can monitor shutdown
        server_thread = threading.Thread(target=server.run_forever,
                                         daemon=True,
                                         name="server_thread")
        server_thread.start()
        threads.append(server_thread)

        # Wait for shutdown signal
        while not _shutdown_event.is_set():
            try:
                _shutdown_event.wait(timeout=1)
            except KeyboardInterrupt:
                logging.info("Interrupted, shutting down...")
                _shutdown_event.set()  # Signal shutdown to all threads
                break

    except Exception as e:
        logging.error(f"Error in main: {e}")
    finally:
        if proc and server:
            try:
                cleanup(proc, server, threads)
            except KeyboardInterrupt:
                logging.info("Cleanup interrupted, forcing exit...")
                # Force cleanup of critical resources
                try:
                    if proc.stdin and not proc.stdin.closed:
                        proc.stdin.close()
                    proc.terminate()
                except:
                    pass
            except Exception as e:
                logging.error(f"Error during cleanup: {e}")


if __name__ == "__main__":
    main()
