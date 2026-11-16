from pathlib import Path

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError

from development_mcp.drafting import DraftError, draft_model
from development_mcp.schema import PROGRAMS


class Command(BaseCommand):
    help = 'Propose an MCP registry declaration; never changes models, data or permissions.'

    def add_arguments(self, parser):
        parser.add_argument('model', help='Django app.Model label')
        parser.add_argument('--program', action='append', choices=list(PROGRAMS), default=[])
        parser.add_argument('--via', help='Parent ForeignKey/OneToOne field, e.g. user')
        parser.add_argument('--output', type=Path, help='New draft file; existing files are never overwritten')

    def handle(self, *args, **options):
        try:
            model = apps.get_model(options['model'])
        except (LookupError, ValueError):
            raise CommandError('unknown_model') from None
        try:
            text = draft_model(model, options['program'], options['via'])
            if options['output']:
                with options['output'].open('x', encoding='utf-8') as stream:
                    stream.write(text)
                self.stdout.write('draft_saved')
            else:
                self.stdout.write(text, ending='')
        except DraftError as exc:
            raise CommandError(str(exc)) from None
        except OSError:
            raise CommandError('cannot_write_draft_no_overwrite') from None
