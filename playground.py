import asyncio
from contextlib import aclosing


async def loop():
    i = 0
    try:
        for i in range(10):
            yield i
            await asyncio.sleep(1)
    finally:
        print(f"loop({i})")


async def main():
    count = 0
    async for i in loop():
        print(i)
        count += 1
        if count == 5:
            break
    async for i in loop():
        print(i)


async def main2():
    async with aclosing(loop()) as gen:
        count = 0
        async for i in gen:
            print(i)
            count += 1
            if count == 5:
                break
    async with aclosing(loop()) as gen:
        async for i in gen:
            print(i)


asyncio.run(main())
