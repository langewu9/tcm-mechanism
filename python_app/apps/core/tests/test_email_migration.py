"""Existing duplicate accounts block migration without modifying research data."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class EmailIdentityMigrationTests(TransactionTestCase):
    migrate_from = [("core", "0020_analysistask_parent_task")]
    migrate_to = [("core", "0022_datasource_last_preview_requested_at")]

    def setUp(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        apps = executor.loader.project_state(self.migrate_from).apps
        self.User = apps.get_model("auth", "User")

    def tearDown(self):
        # Only these temporary test accounts; never operates on a real database.
        self.User.objects.filter(username__startswith="migration-test-").delete()
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_duplicate_existing_emails_stop_migration_without_mutation(self):
        first = self.User.objects.create(username="migration-test-one", email="Reader@example.test")
        second = self.User.objects.create(username="migration-test-two", email=" reader@example.test ")
        before = list(self.User.objects.filter(pk__in=[first.pk, second.pk]).values_list("pk", "email"))
        with self.assertRaisesRegex(RuntimeError, "Duplicate normalized user emails"):
            MigrationExecutor(connection).migrate(self.migrate_to)
        after = list(self.User.objects.filter(pk__in=[first.pk, second.pk]).values_list("pk", "email"))
        self.assertEqual(after, before)

    def test_nonduplicate_existing_accounts_are_preserved(self):
        account = self.User.objects.create(username="migration-test-one", email="reader@example.test")
        MigrationExecutor(connection).migrate(self.migrate_to)
        self.assertEqual(self.User.objects.get(pk=account.pk).email, "reader@example.test")
