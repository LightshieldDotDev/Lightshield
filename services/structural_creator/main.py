import asyncio
import os

import aio_pika
from aio_pika import ExchangeType

server = os.environ['SERVER']

args = {
    'x-overflow': 'reject-publish',
    'x-max-length': 2000}


async def main(loop):
    print("Creating channels")

    connection = await aio_pika.connect_robust(
        "amqp://guest:guest@rabbitmq/", loop=loop)

    async with connection:
        channel = await connection.channel()

        # League Rankings
        rankings_out = await channel.declare_exchange(
            name="%s_RANKED" % server,
            durable=True,
            type=ExchangeType.TOPIC)
        await asyncio.sleep(1)
        # Summoner IDs
        summoner_in = await channel.declare_queue(
            name='%s_RANKED_TO_SUMMONER' % server,
            durable=True,
            arguments=args
        )
        await summoner_in.bind(rankings_out, routing_key="#")
        summoner_out = await channel.declare_exchange(
            name="%s_SUMMONER" % server,
            durable=True,
            type=ExchangeType.TOPIC)
        await asyncio.sleep(1)

        # Match History
        history_in = await channel.declare_queue(
            name='%s_SUMMONER_TO_HISTORY' % server,
            durable=True,
            arguments=args
        )
        await history_in.bind(summoner_out, routing_key="#")
        history_out = await channel.declare_exchange(
            name="%s_HISTORY" % server,
            durable=True,
            type=ExchangeType.TOPIC)
        await asyncio.sleep(1)

        # Match Details
        details_in = await channel.declare_queue(
            name="%s_HISTORY_TO_DETAILS" % server,
            durable=True,
            arguments=args
        )
        await details_in.bind(history_out, routing_key="#")
        details_out = await channel.declare_exchange(
            name="%s_DETAILS" % server,
            durable=True,
            type=ExchangeType.TOPIC)
        await asyncio.sleep(1)

        # Processor
        processor_summoner_in = await channel.declare_queue(
            name="%s_SUMMONER_TO_PROCESSOR" % server,
            durable=True,
            arguments=args
        )
        await processor_summoner_in.bind(summoner_out, routing_key="#")
        processor_details_in = await channel.declare_queue(
            name="%s_DETAILS_TO_PROCESSOR" % server,
            durable=True,
            arguments=args
        )
        await processor_details_in.bind(details_out, routing_key="#")


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main(loop))
    loop.close()
