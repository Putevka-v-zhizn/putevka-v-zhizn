import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from development_mcp.bundle import MAX_BYTES, BundleError, loads
from development_mcp.local_import import ImportCaseError, ensure_local, import_bundle


class Command(BaseCommand):
    help = 'Import a cleaned MCP case into an explicitly enabled local development DB.'

    def add_arguments(self, parser):
        parser.add_argument('bundle', type=Path)
        parser.add_argument('--database', default='default')
        parser.add_argument('--password', help='Optional password for the new local test user; otherwise login is disabled')
        parser.add_argument('--suffix', default='', help='Create another isolated copy with this short suffix')

    def handle(self, *args, **options):
        try:
            ensure_local(options['database'])
            with options['bundle'].open('rb') as stream:
                raw = stream.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise BundleError('bundle_too_large')
            result = import_bundle(loads(raw.decode('utf-8')), options['database'], options['password'], options['suffix'])
        except (BundleError, ImportCaseError) as exc:
            raise CommandError(str(exc)) from None
        except Exception:
            raise CommandError('import_failed_rolled_back') from None
        self.stdout.write(json.dumps(result, ensure_ascii=False))
