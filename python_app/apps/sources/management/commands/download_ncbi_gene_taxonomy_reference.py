from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.sources.connectors.ncbi_gene_taxonomy_reference import download_reference
from apps.sources.target_identity import input_profiles


class Command(BaseCommand):
    help = "Download an immutable NCBI TaxID crosswalk for explicit local Entrez Gene IDs."

    def add_arguments(self, parser):
        parser.add_argument(
            "--directory",
            default=str(Path(settings.MEDIA_ROOT).parent / "target-reference"),
            help="Directory for the versioned local reference snapshot.",
        )

    def handle(self, *args, **options):
        gene_ids = {
            identifier
            for profile in input_profiles().values()
            if profile["taxon"] == "unknown"
            for namespace, identifier in profile["ids"]
            if namespace in {"entrez", "ncbi_gene"} and str(identifier).isdigit()
        }
        try:
            path = download_reference(options["directory"], gene_ids)
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(str(path))
