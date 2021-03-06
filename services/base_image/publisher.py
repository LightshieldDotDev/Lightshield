"""The Publisher is the output segment of the service. It will broadcast all packages processed.

Each service can limit the output by providing a list of Required Subscriber. As long as not all
required subscriber are connected the publisher will pause.
Additional service can connect without halting/interrupting the publishing (e.g. logging systems).
"""
import asyncio
import logging
import os
import threading

import aioredis
import websockets


class Publisher(threading.Thread):
    """Threaded class that handles the sending of local requests to downstream services.

    Data is taken from an outgoing buffer and broadcasted.
    """

    def __init__(self, host='0.0.0.0', port=9999):
        """Initiate logging and global variables."""
        super().__init__()
        self.logging = logging.getLogger("Publisher")
        self.logging.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        handler.setFormatter(
            logging.Formatter('%(asctime)s [Publisher] %(message)s'))
        self.logging.addHandler(handler)
        os.environ['OUTGOING'] = "0"
        self.logging.info("Initiating publisher service.")
        if 'REQUIRED_SUBSCRIBER' in os.environ and os.environ['REQUIRED_SUBSCRIBER'] != '':
            self.required_subs = os.environ['REQUIRED_SUBSCRIBER'].split(',')
            self.logging.info("Required subs: %s" % self.required_subs)
        else:
            self.required_subs = []
            self.logging.info("No required subs.")
        self.connection_params = [host, port]
        self.stopped = False
        self.redisc = None
        self.clients = set()
        self.client_names = {}
        self.runner = None  # Async server runner
        self.sent_packages = 0

    def stop(self) -> None:
        """Initiate shutdown."""
        self.logging.info("Received shutdown signal. Shutting down.")
        self.stopped = True

    def run(self) -> None:
        """Initiate the async loop/websocket server."""

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        asyncio.run(self.async_run())

    async def init(self) -> None:
        """Initiate redis connection."""
        self.redisc = await aioredis.create_redis_pool(
            ('redis', 6379), db=0, encoding='utf-8')

    async def async_run(self) -> None:
        """Run async initiation and start websocket server."""
        await self.init()
        sender_task = asyncio.create_task(self.sender())
        logger = asyncio.create_task(self.logger())
        shutdown_handler = asyncio.create_task(self.shutdown_handler())

        async with websockets.serve(self.handler, *self.connection_params):
            while not self.stopped:
                await asyncio.sleep(1)

        await shutdown_handler
        await sender_task
        self.logging.info("Shutdown server.")
        await logger

    async def logger(self) -> None:
        """Handle passive logging tasks."""
        while not self.stopped:
            await asyncio.sleep(15)
            self.logging.info(
                "Sent: %s | Buffered out: %s/500. Connections: %s",
                self.sent_packages,
                await self.redisc.llen('packages'),
                list(self.client_names.keys()))
            self.sent_packages = 0

    async def shutdown_handler(self):
        """Set server to exit on shutdown signal."""
        while not self.stopped:
            await asyncio.sleep(1)
        await self.runner.cleanup()

    async def send(self, client, message):
        try:
            await client.send(message)
            return True
        except websockets.ConnectionClosed:
            return False
        except Exception as err:
            self.logging.info("Exception %s received: %s", err.__class__.__name__, err)
            await asyncio.sleep(0.5)
            return False

    async def sender(self):
        """Send data to clients as long as all clients are connected.

        Initiated by the first connected client to avoid it running multiple times.
        Once no more clients are connected this terminates itself.
        """
        while True:
            if not self.client_names:
                await asyncio.sleep(5)
                continue
            missing = False
            for sub in self.required_subs:
                if sub not in self.client_names.keys():
                    missing = True
                    await asyncio.sleep(1)
            if missing:
                continue
            task = await self.redisc.lpop('packages')
            if task:
                if not all(
                        await asyncio.gather(*[self.send(client, task) for client in self.clients])):
                    await asyncio.sleep(1)
                self.sent_packages += 1
            else:
                await asyncio.sleep(0.5)

    async def handler(self, websocket, path) -> None:
        """Handle the websocket client connection."""
        client_name = None
        try:
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=3)
            except asyncio.TimeoutError:
                self.logging.info("Receive timed out.")
                return

            if not message.startswith('ACK'):
                self.logging.info("Received non ACK message: %s", message)
                return
            client_name = message.split("_")[1]
            self.logging.info("Client %s opened connection." % client_name)
            await asyncio.sleep(0.1)
            self.clients.add(websocket)
            self.client_names[client_name] = True
            self.logging.info("Client %s now ready to receive." % client_name)

            while not self.stopped and websocket.open:
                await asyncio.sleep(0.2)

        except Exception as err:
            self.logging.info("%s: %s", err.__class__.__name__, err)
            return

        finally:
            del self.client_names[client_name]
            self.clients.remove(websocket)
            self.logging.info("Client %s closed connection." % client_name)
