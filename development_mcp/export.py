"""Download a cleaned case over personal SSH/stdin to a local JSON file."""

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import re
import sys
from datetime import timedelta

from .bundle import BundleError, Collector, ID


async def collect(session, case_id):
    collector, cursor = Collector(), None
    while True:
        args = {'case_id': case_id}
        if cursor:
            args['cursor'] = cursor
        result = await session.call_tool('export_case', args)
        if result.isError or not result.structuredContent:
            raise BundleError('export_failed')
        page = result.structuredContent
        collector.add(page)
        cursor = page.get('next_cursor')
        if not cursor:
            return collector.finish()


async def download(alias, case_id):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(command='ssh', args=['-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', alias])
    with open(os.devnull, 'w') as errors:
        async with stdio_client(params, errlog=errors) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=120)) as session:
                await session.initialize()
                return await collect(session, case_id)


def write_bundle(path, bundle):
    # Never overwrite a previous fixture, and don't create a file before downloading.
    payload = json.dumps(bundle, ensure_ascii=False, allow_nan=False, indent=2).encode('utf-8')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
    except BaseException:
        Path(path).unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ssh', required=True, help='Personal SSH alias, e.g. putevka-mcp')
    parser.add_argument('--case-id', required=True)
    parser.add_argument('--output', required=True, type=Path)
    options = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@:-]{0,250}', options.ssh) or not ID.fullmatch(options.case_id):
        parser.error('Invalid SSH alias or opaque case ID')
    logging.disable(sys.maxsize)
    try:
        if options.output.exists():
            raise BundleError('output_exists')
        bundle = asyncio.run(download(options.ssh, options.case_id))
        write_bundle(options.output, bundle)
        print(json.dumps({'code': 'ok', 'records': len(bundle['records'])}))
        return 0
    except Exception:
        print('{"code":"export_failed_no_overwrite"}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
