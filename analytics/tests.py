"""Analytics pages render real-shaped service data, and degrade when services fail."""

from django.urls import reverse

from servicedata.fake_replies import ORG_NAME, PageTestCase

PAGES = ("overview", "growth", "billing", "ai-usage", "engagement", "access")


class AnalyticsPageTests(PageTestCase):
    """Every analytics page, end to end through views, selectors and templates."""

    def test_pages_render_with_every_service_up(self) -> None:
        for name in PAGES:
            with self.subTest(page=name):
                response = self.client.get(reverse(name), {"days": 30})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["down"], [])

    def test_pages_render_with_every_service_down(self) -> None:
        self.fail_all()
        for name in PAGES:
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["down"])

    def test_overview_flags_past_due_renewal_and_ai_use(self) -> None:
        response = self.client.get(reverse("overview"))
        reasons = [(a["reason"], a["level"]) for a in response.context["attention"]]
        self.assertIn(("Subscription past_due", "red"), reasons)
        self.assertIn(("AI credits at 90% of allowance", "amber"), reasons)
        self.assertContains(response, ORG_NAME)

    def test_growth_funnel_counts_each_step(self) -> None:
        funnel = self.client.get(reverse("growth")).context["funnel"]
        reached = {step["label"]: step["n"] for step in funnel}
        self.assertEqual(reached["Signed up"], 1)
        self.assertEqual(reached["Invited a 2nd user"], 0)
        self.assertEqual(reached["Used AI"], 1)

    def test_engagement_rolls_members_up_to_orgs(self) -> None:
        row = self.client.get(reverse("engagement")).context["rows"][0]
        self.assertEqual((row["active_members"], row["items"], row["unread"]), (1, 5, 1))

    def test_ai_and_access_summaries(self) -> None:
        ai = self.client.get(reverse("ai-usage")).context["ai"]
        self.assertEqual(ai["run_failure_pct"], 25)
        access = self.client.get(reverse("access")).context["a"]
        self.assertEqual(access["deny_pct"], 25)
