"""Keep the curated reference-case corpus in its own database."""


class CaseRagRouter:
    app_label = "case_rag"
    database = "case_rag"

    def db_for_read(self, model, **hints):
        if model._meta.app_label == self.app_label:
            return self.database
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label == self.app_label:
            return self.database
        return None

    def allow_relation(self, obj1, obj2, **hints):
        if self.app_label in {obj1._meta.app_label, obj2._meta.app_label}:
            return obj1._meta.app_label == obj2._meta.app_label == self.app_label
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label == self.app_label:
            return db == self.database
        if db == self.database:
            return False
        return None
