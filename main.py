import asyncio
import logging

import runtime_v378


async def main():
    await runtime_v378.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
