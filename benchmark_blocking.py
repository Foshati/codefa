import json
import time
import asyncio

def parse_logs_sync(lines):
    parsed_logs = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            parsed_logs.append(json.loads(line))
        except Exception:
            parsed_logs.append({"message": line, "level": "INFO"})
    return parsed_logs

async def parse_logs_async(lines):
    return await asyncio.to_thread(parse_logs_sync, lines)

async def measure_blocking(func, lines):
    ticks = []
    async def ticker():
        try:
            while True:
                await asyncio.sleep(0.01)
                ticks.append(time.perf_counter())
        except asyncio.CancelledError:
            pass

    t = asyncio.create_task(ticker())

    start_time = time.perf_counter()
    if asyncio.iscoroutinefunction(func):
        await func(lines)
    else:
        func(lines)
    end_time = time.perf_counter()

    t.cancel()
    try:
        await t
    except asyncio.CancelledError:
        pass

    duration = end_time - start_time

    if len(ticks) < 2:
        max_delay = duration
    else:
        delays = [ticks[i] - ticks[i-1] for i in range(1, len(ticks))]
        max_delay = max(delays)

    return duration, max_delay

async def main():
    lines = ['{"message": "hello", "level": "INFO"}\n'] * 500000

    print("Running sync version...")
    sync_duration, sync_max_delay = await measure_blocking(parse_logs_sync, lines)
    print(f"Sync took: {sync_duration:.4f}s")
    print(f"Max event loop delay (blocking time): {sync_max_delay:.4f}s")

    print("\nRunning async version...")
    async_duration, async_max_delay = await measure_blocking(parse_logs_async, lines)
    print(f"Async took: {async_duration:.4f}s")
    print(f"Max event loop delay (blocking time): {async_max_delay:.4f}s")

if __name__ == "__main__":
    asyncio.run(main())
