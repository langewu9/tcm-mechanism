"""Main-branch q searches keep the current researcher ownership boundary."""

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.core.models import MedicalCase, ResearchDataset


class RecordSearchTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.owner = user_model.objects.create_user(username="search-owner")
        cls.other = user_model.objects.create_user(username="search-other")
        cls.staff = user_model.objects.create_user(username="search-staff", is_staff=True)
        cls.admin = user_model.objects.create_user(
            username="search-admin", is_staff=True, is_superuser=True
        )
        cls.named_dataset = ResearchDataset.objects.create(
            owner=cls.owner, name="肺纤维化研究", original_filename="cohort.csv"
        )
        cls.filename_dataset = ResearchDataset.objects.create(
            owner=cls.owner, name="动物实验", original_filename="fibrosis_cohort.xlsx"
        )
        cls.unmatched_dataset = ResearchDataset.objects.create(
            owner=cls.owner,
            name="正常对照",
            original_filename="control.csv",
            description="肺纤维化与 fibrosis 只出现在说明中",
        )
        cls.private_dataset = ResearchDataset.objects.create(
            owner=cls.other,
            name="肺纤维化外部研究",
            original_filename="fibrosis_private.csv",
        )
        cls.title_case = MedicalCase.objects.create(
            owner=cls.owner, title="肺纤维化医案", deidentified_text="干咳伴乏力"
        )
        cls.text_case = MedicalCase.objects.create(
            owner=cls.owner, title="随访医案", deidentified_text="呼吸困难，疑似肺纤维化"
        )
        cls.diagnosis_case = MedicalCase.objects.create(
            owner=cls.owner,
            title="影像随访",
            deidentified_text="活动后气促",
            structured_data={"diagnosis": "肺纤维化", "tongue_pulse": "舌红"},
        )
        cls.unmatched_case = MedicalCase.objects.create(
            owner=cls.owner,
            title="消化系统研究",
            deidentified_text="胃脘不适",
            structured_data={"tongue_pulse": "肺纤维化"},
            source_reference="肺纤维化研究资料",
            research_notes="肺纤维化只出现在其他字段",
        )
        cls.private_case = MedicalCase.objects.create(
            owner=cls.other,
            title="肺纤维化私人医案",
            deidentified_text="肺纤维化",
            structured_data={"diagnosis": "肺纤维化"},
        )

    def list_ids(self, route, user, query):
        self.client.force_authenticate(user)
        response = self.client.get(reverse(route), {"q": query})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], len(response.data["results"]))
        return {item["id"] for item in response.data["results"]}

    def test_dataset_query_matches_name_or_filename_and_excludes_description(self):
        self.assertEqual(
            self.list_ids("dataset-list", self.owner, "纤维化"),
            {self.named_dataset.pk},
        )
        self.assertEqual(
            self.list_ids("dataset-list", self.owner, "FIBROSIS"),
            {self.filename_dataset.pk},
        )

    def test_case_query_matches_title_text_and_mapped_diagnosis_only(self):
        self.assertEqual(
            self.list_ids("case-list", self.owner, "纤维化"),
            {self.title_case.pk, self.text_case.pk, self.diagnosis_case.pk},
        )

    def test_query_does_not_expose_another_researchers_matching_records(self):
        for route, query in [("dataset-list", "private"), ("case-list", "私人")]:
            with self.subTest(route=route):
                self.assertEqual(self.list_ids(route, self.owner, query), set())

    def test_staff_without_superuser_permission_cannot_search_other_owners(self):
        for route in ["dataset-list", "case-list"]:
            with self.subTest(route=route):
                self.assertEqual(self.list_ids(route, self.staff, "纤维化"), set())

    def test_superuser_searches_all_owners_but_query_still_filters(self):
        self.assertEqual(
            self.list_ids("dataset-list", self.admin, "fibrosis"),
            {self.filename_dataset.pk, self.private_dataset.pk},
        )
        self.assertEqual(
            self.list_ids("case-list", self.admin, "纤维化"),
            {self.title_case.pk, self.text_case.pk, self.diagnosis_case.pk, self.private_case.pk},
        )

    def test_query_whitespace_is_trimmed_and_blank_keeps_owned_listing(self):
        for query in ["纤维化", "  纤维化  "]:
            with self.subTest(query=query):
                self.assertEqual(
                    self.list_ids("dataset-list", self.owner, query),
                    {self.named_dataset.pk},
                )
                self.assertEqual(
                    self.list_ids("case-list", self.owner, query),
                    {self.title_case.pk, self.text_case.pk, self.diagnosis_case.pk},
                )
        self.assertEqual(
            self.list_ids("dataset-list", self.owner, "   "),
            {self.named_dataset.pk, self.filename_dataset.pk, self.unmatched_dataset.pk},
        )
        self.assertEqual(
            self.list_ids("case-list", self.owner, "   "),
            {self.title_case.pk, self.text_case.pk, self.diagnosis_case.pk, self.unmatched_case.pk},
        )

    def test_query_with_no_match_returns_empty_list(self):
        for route in ["dataset-list", "case-list"]:
            with self.subTest(route=route):
                self.assertEqual(self.list_ids(route, self.admin, "无匹配内容"), set())

    def test_list_query_does_not_change_detail_lookup(self):
        self.client.force_authenticate(self.owner)
        for route, record in [
            ("dataset-detail", self.named_dataset),
            ("case-detail", self.title_case),
        ]:
            with self.subTest(route=route):
                response = self.client.get(reverse(route, args=[record.pk]), {"q": "无匹配内容"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data["id"], record.pk)
