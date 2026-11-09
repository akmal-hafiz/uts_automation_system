"""Tes untuk aturan regex dan klasifikasi bidang.

Jalankan dari folder proyek:
    python -m unittest discover tests
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402
from main import (  # noqa: E402
    JOB_URL_PATTERN, classify_field, clean_text, find_skills, humanize_code, safe_filename,
)


class SkillPatternTest(unittest.TestCase):
    def test_skill_at_end_of_sentence_is_found(self):
        self.assertIn("Python", find_skills("Experience with Python."))

    def test_skill_followed_by_hyphen_is_found(self):
        self.assertIn("Python", find_skills("Python-based automation"))

    def test_sql_inside_nosql_is_ignored(self):
        self.assertNotIn("SQL", find_skills("Familiar with NoSQL databases"))

    def test_java_inside_javascript_is_ignored(self):
        skills = find_skills("Strong JavaScript skills")
        self.assertIn("JavaScript", skills)
        self.assertNotIn("Java", skills)

    def test_symbols_in_name(self):
        skills = find_skills("C#, ASP.NET Core, and Node.js")
        self.assertIn("C#", skills)
        self.assertIn(".NET", skills)
        self.assertIn("Node.js", skills)


class FieldRuleTest(unittest.TestCase):
    def test_devsecops_goes_to_security_not_infra(self):
        self.assertEqual(classify_field("DevSecOps Sr. Specialist"), "Keamanan Siber")

    def test_sdet_goes_to_qa_not_developer(self):
        self.assertEqual(classify_field("Software Development Engineer in Test"), "QA dan Pengujian")

    def test_it_support(self):
        self.assertEqual(classify_field("IT Support Engineer (Shifting)"), "Dukungan IT")

    def test_database_admin_is_not_data(self):
        self.assertEqual(classify_field("IT Database Administrator (DBA)"),
                         "Infrastruktur dan Operasional IT")

    def test_developer(self):
        self.assertEqual(classify_field("PHP Developer"), "Pengembangan Perangkat Lunak")

    def test_unknown_title(self):
        self.assertEqual(classify_field("Mekanik Motor"), "Lainnya")


class CleaningTest(unittest.TestCase):
    def test_clean_text_strips_html_and_spaces(self):
        self.assertEqual(clean_text("<p>Halo&nbsp;\n\n  <b>dunia</b></p>"), "Halo dunia")

    def test_humanize_code(self):
        self.assertEqual(humanize_code("fullTime"), "Full Time")

    def test_safe_filename(self):
        self.assertEqual(safe_filename("Data dan AI"), "data_dan_ai")

    def test_job_url_pattern(self):
        self.assertTrue(JOB_URL_PATTERN.match("https://dealls.com/loker/php-developer~pt-abc"))
        self.assertFalse(JOB_URL_PATTERN.match("https://dealls.com/loker/curated/677df4"))
        self.assertFalse(JOB_URL_PATTERN.match("https://dealls.com/loker/~"))


class NetworkLossTest(unittest.TestCase):
    """collect() harus berhenti kalau koneksi putus berturut-turut."""

    def setUp(self):
        import argparse
        import tempfile

        self.tmp = Path(tempfile.mkdtemp())
        self.args = argparse.Namespace(limit=10, keyword="", delay=0, offline=False,
                                       url="https://dealls.com/loker/x")
        jobs = [{"id": i, "slug": f"job-{i}", "role": f"Job {i}", "company": {"slug": "pt-a"}}
                for i in range(10)]
        patcher = mock.patch.object(main, "online_candidates", return_value=iter(jobs))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_three_connection_errors_in_a_row_abort_the_run(self):
        error = requests.exceptions.ConnectionError("getaddrinfo failed")
        with mock.patch.object(main, "fetch_with_retry", side_effect=error) as fetch:
            with self.assertRaises(requests.exceptions.ConnectionError):
                main.collect(self.args, session=None, html_dir=self.tmp)
        self.assertEqual(fetch.call_count, 3)

    def test_single_timeout_is_only_recorded(self):
        detail = {"role": "PHP Developer", "company": {"name": "PT A"}, "requirements": "PHP"}
        responses = [requests.exceptions.Timeout("slow")] + [("<html/>", detail)] * 9
        with mock.patch.object(main, "fetch_with_retry", side_effect=responses):
            records, _, failures, _ = main.collect(self.args, session=None, html_dir=self.tmp)
        self.assertEqual(len(records), 9)
        self.assertEqual(len(failures), 1)


if __name__ == "__main__":
    unittest.main()
