from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.sources.connectors.target_reference import ACCESSION
from apps.sources.connectors.uniprot_accession_taxonomy import download_reference
from apps.sources.target_identity import input_profiles


class Command(BaseCommand):
    help = "Download exact UniProtKB taxonomy for local accession identifiers with unknown species."

    def add_arguments(self, parser):
        parser.add_argument(
            "--directory",
            default=str(Path(settings.MEDIA_ROOT).parent / "target-reference"),
            help="Directory for the versioned local reference snapshot.",
        )

    def handle(self, *args, **options):
        accessions = {
            identifier.upper()
            for profile in input_profiles().values()
            if profile["taxon"] == "unknown"
            for namespace, identifier in profile["ids"]
            if namespace in {"uniprot", "uniprotkb"} and ACCESSION.fullmatch(str(identifier).upper())
        }
        try:
            path = download_reference(options["directory"], accessions)
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(str(path))
