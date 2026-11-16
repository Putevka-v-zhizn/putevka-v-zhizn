"""Validate real stdio startup without printing or persisting case contents."""

import asyncio
import logging
import os
import sys
from datetime import timedelta


async def check(sample_cases=False):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-m", "development_mcp"],
                                   env={name: os.environ[name] for name in ("MCP_DATABASE_URL", "MCP_HMAC_SECRET")})
    checked = 0
    with open(os.devnull, "w") as errors:
        async with stdio_client(params, errlog=errors) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=90)) as session:
                await session.initialize()
                described = await session.call_tool("describe_dataset", {})
                if described.isError or not described.structuredContent or "error" in described.structuredContent:
                    raise RuntimeError()
                if sample_cases:
                    for program in described.structuredContent["programs"]:
                        result = await session.call_tool("list_cases", {"program": program, "limit": 1})
                        data = result.structuredContent
                        if result.isError or not data or "error" in data:
                            raise RuntimeError()
                        if data["cases"]:
                            # Exercise an actual filter without emitting values or texts.
                            features = data["cases"][0].get("features", {})
                            for name, definition in described.structuredContent["programs"][program].get("filters", {}).items():
                                if definition["kind"] == "text" and type(features.get(name)) is bool:
                                    sample_filters = {name: features[name]}
                                elif definition["kind"] == "count" and type(features.get(name)) is int:
                                    sample_filters = {name: {"min": features[name], "max": features[name]}}
                                else:
                                    continue
                                filtered = await session.call_tool("list_cases", {"program": program, "limit": 1, "filters": sample_filters})
                                if filtered.isError or not filtered.structuredContent or "error" in filtered.structuredContent:
                                    raise RuntimeError()
                                break
                            case = await session.call_tool("get_case", {"case_id": data["cases"][0]["case_id"]})
                            if case.isError or not case.structuredContent or "error" in case.structuredContent:
                                raise RuntimeError()
                            from .export import collect
                            await collect(session, data['cases'][0]['case_id'])
                            checked += 1
    return checked


def main():
    logging.disable(sys.maxsize)
    try:
        checked = asyncio.run(asyncio.wait_for(check("--sample-cases" in sys.argv), timeout=300))
        print('{"code":"ok","cases_checked":' + str(checked) + '}')
        return 0
    except BaseException:
        print('{"code":"smoke_failed"}', file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
