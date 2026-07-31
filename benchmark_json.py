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

async def main():
    # create dummy lines
    lines = ['{"message": "hello", "level": "INFO"}\n'] * 500000

    t0 = time.perf_counter()
    res1 = parse_logs_sync(lines)
    t1 = time.perf_counter()
    print(f"Sync took: {t1 - t0:.4f}s")

    t0 = time.perf_counter()
    res2 = await parse_logs_async(lines)
    t1 = time.perf_counter()
    print(f"Async took: {t1 - t0:.4f}s")

if __name__ == "__main__":
    asyncio.run(main())
