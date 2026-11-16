import sys
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_stdio_handshake_tools_and_case(self):
        params = StdioServerParameters(command=sys.executable, args=['-m', 'development_mcp.tests.protocol_fixture'])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                self.assertEqual({t.name for t in tools}, {'describe_dataset', 'list_cases', 'get_case', 'export_case'})
                self.assertTrue(all(t.annotations.readOnlyHint for t in tools))
                result = await session.call_tool('describe_dataset', {})
                self.assertFalse(result.isError)
                self.assertIn('main', result.structuredContent['programs'])
                listed = await session.call_tool('list_cases', {'program': 'main'})
                case_id = listed.structuredContent['cases'][0]['case_id']
                case = await session.call_tool('get_case', {'case_id': case_id})
                self.assertFalse(case.isError)
                self.assertIn('items', case.structuredContent)
                self.assertNotIn('ivan@example.org', str(case))
                self.assertNotIn('Иван', str(case))
                filtered = await session.call_tool('list_cases', {'program': 'main', 'filters': {'has_interview_transcript': True, 'motivation_score': {'min': 4}}})
                self.assertEqual(len(filtered.structuredContent['cases']), 1)
                self.assertTrue(filtered.structuredContent['cases'][0]['features']['has_interview_transcript'])
                from development_mcp.export import collect
                exported = await collect(session, case_id)
                self.assertEqual(exported['format'], 'putevka.development-case')
                self.assertGreater(len(exported['records']), 1)
                self.assertNotIn('ivan@example.org', str(exported))
                rejected = await session.call_tool('list_cases', {'program': 'main', 'filters': {'phone': '123'}})
                self.assertEqual(rejected.structuredContent['error']['code'], 'invalid_request')
                invalid = await session.call_tool('get_case', {'case_id': '201'})
                self.assertEqual(invalid.structuredContent['error']['code'], 'invalid_request')
